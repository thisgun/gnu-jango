import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from gnu_jango.api.shop_payments import cancel_pending_vbank, refresh_pending_vbank
from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits, close_cancelled_order_payment
from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.order_flow import canonical_status
from gnu_jango.shop.order_statuses import STATUS_ORDERED
from gnu_jango.shop.vbank_due import parse_vbank_due_date

WAITING = "WAITING_FOR_DEPOSIT"
# The PGs whose accounts this shop can close (shop_payments.cancel_pending_vbank).
EXPIRING_PGS = ("toss", "nicepay")
# A deposit made just before the deadline can reach the PG's lookup and the shop's notification
# endpoint a little later; the order waits this long past the deadline before it is closed.
DEFAULT_GRACE_MINUTES = 30
REASON = "가상계좌 입금 기한이 지나 자동 취소되었습니다."
COUNTED_ACTIONS = {"cancelled", "settled", "failed"}


def waiting_for_deposit(order):
    return canonical_status(order.od_status) == STATUS_ORDERED and order.od_vbank_status == WAITING


class Command(BaseCommand):
    help = (
        "Close the Toss and NICEPAY virtual accounts whose deposit deadline has passed, then cancel "
        "their orders and give back the stock, coupons and points they held."
    )

    def add_arguments(self, parser):
        parser.add_argument("--order-id", action="append", default=[], help="Limit to one or more order ids.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum number of pending orders to inspect.")
        parser.add_argument(
            "--grace-minutes",
            type=int,
            default=DEFAULT_GRACE_MINUTES,
            help=f"Wait this long past the deadline for a late deposit notice (default {DEFAULT_GRACE_MINUTES}).",
        )
        parser.add_argument("--apply", action="store_true", help="Call the PG and update orders. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"] or 0)
        grace = int(options["grace_minutes"])
        if limit < 1 or grace < 0:
            raise CommandError("--limit must be positive and --grace-minutes must not be negative.")

        cutoff = timezone.now() - timedelta(minutes=grace)
        pgs = Q()
        for pg in EXPIRING_PGS:
            pgs |= Q(od_pg__iexact=pg)
        # od_vbank_due_date holds two text formats, so it cannot order the rows; the account is
        # issued with the order, so the oldest orders are the first to expire.
        queryset = (
            ShopOrder.objects.filter(pgs, od_vbank_status=WAITING)
            .exclude(od_vbank_due_date="")
            .order_by("od_datetime", "od_id")
        )
        if options["order_id"]:
            order_ids = [str(item).strip() for item in options["order_id"] if str(item).strip()]
            queryset = queryset.filter(pk__in=order_ids)
        orders = list(queryset[:limit])

        summary = {
            "applied": bool(options["apply"]),
            "inspected": len(orders),
            "expired": 0,
            "cancelled": 0,
            "settled": 0,
            "invalid_due_date": 0,
            "skipped": 0,
            "failed": 0,
            "samples": [],
        }
        failures = []

        for order in orders:
            due_date = parse_vbank_due_date(order.od_vbank_due_date)
            if due_date is None:
                summary["invalid_due_date"] += 1
                self.add_sample(summary, order, "invalid_due_date")
                continue
            if due_date > cutoff:
                summary["skipped"] += 1
                continue
            summary["expired"] += 1
            if not waiting_for_deposit(order):
                summary["skipped"] += 1
                self.add_sample(summary, order, "manual_review")
                continue
            if not options["apply"]:
                self.add_sample(summary, order, "planned")
                continue
            action = self.expire(order, failures)
            summary[action if action in COUNTED_ACTIONS else "skipped"] += 1
            self.add_sample(summary, order, action)

        if options["json"]:
            self.stdout.write(json.dumps({**summary, "failures": failures[:20]}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Virtual account expiry: "
                f"inspected={summary['inspected']} expired={summary['expired']} "
                f"cancelled={summary['cancelled']} settled={summary['settled']} skipped={summary['skipped']} "
                f"invalid_due_date={summary['invalid_due_date']} failed={summary['failed']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )
            for failure in failures[:20]:
                self.stderr.write(f"{failure['order_id']}: {failure['reason']}")

        if failures:
            raise CommandError(f"Could not expire {len(failures)} virtual account order(s).")

    def expire(self, order, failures):
        """Close one expired account at its PG, then cancel the order. Returns the sample action."""
        error = refresh_pending_vbank(order)
        if error:
            self.add_failure(failures, order, error)
            return "failed"
        order.refresh_from_db()
        if not waiting_for_deposit(order):
            # the PG reported a deposit (the order is now paid) or an account it already closed
            return "settled"

        error = cancel_pending_vbank(order, REASON)
        if error:
            self.add_failure(failures, order, error)
            return "failed"

        with transaction.atomic():
            locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
            if not locked or not waiting_for_deposit(locked):
                return "state_changed"
            cancelled, _ = cancel_order_and_refund_benefits(locked, REASON)
            close_cancelled_order_payment(cancelled)
        return "cancelled"

    def add_failure(self, failures, order, error):
        details = getattr(error, "data", {}) or {}
        reason = str(details.get("message") or details.get("detail") or f"HTTP {error.status_code}")
        failures.append({"order_id": order.od_id, "reason": reason})

    def add_sample(self, summary, order, action):
        if len(summary["samples"]) >= 20:
            return
        summary["samples"].append({"order_id": order.od_id, "pg": order.od_pg, "action": action})
