import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from gnu_jango.api.shop_nicepay import NICEPAY_REFUSAL, expire_refused_nicepay_vbank
from gnu_jango.api.shop_payments import (
    cancel_pending_vbank,
    pg_label,
    record_payment_raw_log,
    refresh_pending_vbank,
)
from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits, close_cancelled_order_payment
from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.order_flow import canonical_status
from gnu_jango.shop.order_statuses import STATUS_ORDERED
from gnu_jango.shop.vbank_due import parse_vbank_due_date

logger = logging.getLogger(__name__)

WAITING = "WAITING_FOR_DEPOSIT"
# The PGs whose accounts this shop can close (shop_payments.cancel_pending_vbank).
EXPIRING_PGS = ("toss", "nicepay")
# A deposit made just before the deadline can reach the PG's lookup and the shop's notification
# endpoint a little later; the order waits this long past the deadline before it is closed.
DEFAULT_GRACE_MINUTES = 30
# NICEPAY may refuse to close an account whose deadline has passed. Banks take no deposit after
# the deadline, so a day after it, with the lookup still finding no deposit, the order is cancelled
# here anyway; a deposit that arrives regardless is kept for a refund (shop_nicepay).
LOCAL_EXPIRY_AFTER = timedelta(hours=24)
REASON = "가상계좌 입금 기한이 지나 자동 취소되었습니다."
COUNTED_ACTIONS = {"cancelled", "expired_locally", "settled"}
LISTED = 20


def waiting_for_deposit(order):
    return canonical_status(order.od_status) == STATUS_ORDERED and order.od_vbank_status == WAITING


def nicepay_refusal(error):
    """What NICEPAY answered when it refused to close the account; None for any other error."""
    errors = (getattr(error, "data", None) or {}).get("errors")
    return errors.get(NICEPAY_REFUSAL) if isinstance(errors, dict) else None


def error_reason(error):
    details = getattr(error, "data", None) or {}
    return str(details.get("message") or details.get("detail") or f"HTTP {error.status_code}")


class Command(BaseCommand):
    help = (
        "Close the Toss and NICEPAY virtual accounts whose deposit deadline has passed, then cancel "
        "their orders and give back the stock, coupons and points they held."
    )

    def add_arguments(self, parser):
        parser.add_argument("--order-id", action="append", default=[], help="Limit to one or more order ids.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum number of overdue orders to close.")
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

        summary = {
            "applied": bool(options["apply"]),
            "inspected": 0,
            "expired": 0,
            "cancelled": 0,
            "expired_locally": 0,
            "settled": 0,
            "skipped": 0,
            "stuck": 0,
            "invalid_due_date": 0,
            "manual_review": 0,
            "failed": 0,
            "needs_review": 0,
            "samples": [],
        }
        failures = []

        overdue = self.overdue_orders(options, timezone.now() - timedelta(minutes=grace), summary)
        for due_date, order in overdue[:limit]:
            summary["expired"] += 1
            if not options["apply"]:
                self.add_sample(summary, order, "planned")
                continue
            try:
                action, problem = self.expire(order, due_date)
            except Exception as exc:  # noqa: BLE001 - one order must not stop the others
                logger.exception("order %s: the virtual account expiry failed", order.od_id)
                action, problem = "failed", f"{type(exc).__name__}: {exc}"
            if action in COUNTED_ACTIONS:
                summary[action] += 1
            else:
                needs_review = action == "needs_review"
                summary["failed"] += 1
                summary["needs_review"] += int(needs_review)
                failures.append({"order_id": order.od_id, "reason": problem, "needs_review": needs_review})
            self.add_sample(summary, order, action)

        if options["json"]:
            self.stdout.write(json.dumps({**summary, "failures": failures[:LISTED]}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Virtual account expiry: "
                f"inspected={summary['inspected']} expired={summary['expired']} "
                f"cancelled={summary['cancelled']} expired_locally={summary['expired_locally']} "
                f"settled={summary['settled']} skipped={summary['skipped']} stuck={summary['stuck']} "
                f"invalid_due_date={summary['invalid_due_date']} manual_review={summary['manual_review']} "
                f"failed={summary['failed']} needs_review={summary['needs_review']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )
            for failure in failures[:LISTED]:
                self.stderr.write(f"{failure['order_id']}: {failure['reason']}")

        if failures:
            raise CommandError(f"Could not expire {len(failures)} virtual account order(s).")

    def overdue_orders(self, options, cutoff, summary):
        """(deadline, order) for the orders still waiting for a deposit past ``cutoff``, longest
        overdue first. A row that cannot be expired (an unreadable deadline, or an order no longer
        waiting although its account says so) is counted as stuck and never takes a place under
        --limit."""
        pgs = Q()
        for pg in EXPIRING_PGS:
            pgs |= Q(od_pg__iexact=pg)
        queryset = ShopOrder.objects.filter(pgs, od_vbank_status=WAITING).exclude(od_vbank_due_date="")
        order_ids = [str(item).strip() for item in options["order_id"] if str(item).strip()]
        if order_ids:
            queryset = queryset.filter(pk__in=order_ids)

        overdue = []
        for order in queryset.order_by("od_id").iterator():
            summary["inspected"] += 1
            due_date = parse_vbank_due_date(order.od_vbank_due_date)
            if due_date is None:
                summary["invalid_due_date"] += 1
                summary["stuck"] += 1
                self.add_sample(summary, order, "invalid_due_date")
            elif due_date > cutoff:
                summary["skipped"] += 1
            elif not waiting_for_deposit(order):
                summary["manual_review"] += 1
                summary["stuck"] += 1
                summary["skipped"] += 1
                self.add_sample(summary, order, "manual_review")
            else:
                overdue.append((due_date, order))
        return sorted(overdue, key=lambda item: (item[0], item[1].od_id))

    def expire(self, order, due_date):
        """Close one overdue account at its PG, then cancel the order: all under the order's lock,
        as the admin cancel does, so a deposit notification waits for the outcome. Returns the
        action and, for a failure, why."""
        with transaction.atomic():
            locked = ShopOrder.objects.select_for_update(of=("self",)).filter(pk=order.pk).first()
            if locked is None or not waiting_for_deposit(locked):
                return "settled", ""
            error = refresh_pending_vbank(locked)
            if error:
                return "failed", error_reason(error)
            locked.refresh_from_db()
            if not waiting_for_deposit(locked):
                # the PG reported a deposit (the order is now paid) or an account it already closed
                return "settled", ""

            action = "cancelled"
            error = cancel_pending_vbank(locked, REASON)
            refusal = nicepay_refusal(error)
            if refusal and timezone.now() >= due_date + LOCAL_EXPIRY_AFTER:
                action = "expired_locally"
                error = expire_refused_nicepay_vbank(locked, refusal)
            if error:
                return "failed", error_reason(error)

            locked.refresh_from_db()
            if not waiting_for_deposit(locked):
                return "needs_review", self.report_disagreement(locked)
            cancelled, _ = cancel_order_and_refund_benefits(locked, REASON)
            close_cancelled_order_payment(cancelled)
            if action == "expired_locally":
                cancelled.od_vbank_status = "EXPIRED"
                cancelled.save(update_fields=["od_vbank_status"])
        return action, ""

    def report_disagreement(self, order):
        """The PG closed the account, but the order moved on meanwhile: the shop and the PG disagree."""
        reason = (
            f"{pg_label(order.od_pg)} closed the virtual account, but the order is now "
            f"{order.od_status}/{order.od_vbank_status}. Reconcile it with the PG."
        )
        logger.error("order %s: %s", order.od_id, reason)
        record_payment_raw_log(
            order,
            order.od_id,
            str(order.od_pg or ""),
            str(order.od_tno or ""),
            {"vbank_expiry": reason, "od_status": order.od_status, "od_vbank_status": order.od_vbank_status},
            prefix="vbank-expiry-review",
        )
        return reason

    def add_sample(self, summary, order, action):
        if len(summary["samples"]) >= LISTED:
            return
        summary["samples"].append({"order_id": order.od_id, "pg": order.od_pg, "action": action})
