import json
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from gnu_jango.api.v1_shop import (
    CANCELLED_STATUSES,
    ORDERED_STATUSES,
    PAID_STATUSES,
    cancel_pending_toss_vbank,
    restore_order_coupons_and_points,
)
from gnu_jango.shop.inventory import cancel_order_with_stock_restore
from gnu_jango.shop.models import ShopOrder


class Command(BaseCommand):
    help = "Cancel expired unpaid Toss virtual account orders and release reserved stock."

    def add_arguments(self, parser):
        parser.add_argument("--order-id", action="append", default=[], help="Limit to one or more order ids.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum number of pending orders to inspect.")
        parser.add_argument("--apply", action="store_true", help="Call Toss and update orders. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"] or 0)
        if limit < 1:
            raise CommandError("--limit must be a positive integer.")

        now = timezone.now()
        queryset = ShopOrder.objects.filter(
            od_pg__iexact="toss",
            od_vbank_status="WAITING_FOR_DEPOSIT",
        ).exclude(od_vbank_due_date="").order_by("od_vbank_due_date", "od_datetime")
        if options["order_id"]:
            order_ids = [str(item).strip() for item in options["order_id"] if str(item).strip()]
            queryset = queryset.filter(pk__in=order_ids)
        orders = list(queryset[:limit])

        summary = {
            "applied": bool(options["apply"]),
            "inspected": len(orders),
            "expired": 0,
            "cancelled": 0,
            "invalid_due_date": 0,
            "skipped": 0,
            "failed": 0,
            "samples": [],
        }
        failures = []

        for order in orders:
            due_date = self.parse_due_date(order.od_vbank_due_date)
            if due_date is None:
                summary["invalid_due_date"] += 1
                self.add_sample(summary, order, "invalid_due_date")
                continue
            if due_date > now:
                summary["skipped"] += 1
                continue
            summary["expired"] += 1
            if not options["apply"]:
                self.add_sample(summary, order, "planned")
                continue

            error = cancel_pending_toss_vbank(order, "Virtual account deposit deadline expired")
            if error:
                summary["failed"] += 1
                details = getattr(error, "data", {}) or {}
                reason = str(details.get("message") or details.get("detail") or f"HTTP {error.status_code}")
                failures.append({"order_id": order.od_id, "reason": reason})
                self.add_sample(summary, order, "provider_cancel_failed")
                continue

            with transaction.atomic():
                locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
                if not locked or str(locked.od_status or "") in CANCELLED_STATUSES:
                    summary["skipped"] += 1
                    self.add_sample(summary, order, "already_cancelled")
                    continue
                if str(locked.od_status or "") in PAID_STATUSES or str(locked.od_status or "") not in ORDERED_STATUSES:
                    summary["skipped"] += 1
                    self.add_sample(summary, order, "manual_review")
                    continue
                if locked.od_vbank_status != "WAITING_FOR_DEPOSIT":
                    summary["skipped"] += 1
                    self.add_sample(summary, order, "state_changed")
                    continue
                restore_order_coupons_and_points(locked)
                locked, _ = cancel_order_with_stock_restore(locked, "Toss virtual account deposit deadline expired")
                ShopOrder.objects.filter(pk=locked.pk).update(od_vbank_status="CANCELED")
            summary["cancelled"] += 1
            self.add_sample(summary, order, "cancelled")

        if options["json"]:
            self.stdout.write(json.dumps({**summary, "failures": failures[:20]}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Toss virtual account expiry: "
                f"inspected={summary['inspected']} expired={summary['expired']} "
                f"cancelled={summary['cancelled']} skipped={summary['skipped']} "
                f"invalid_due_date={summary['invalid_due_date']} failed={summary['failed']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )
            for failure in failures[:20]:
                self.stderr.write(f"{failure['order_id']}: {failure['reason']}")

        if failures:
            raise CommandError(f"Could not cancel {len(failures)} expired Toss virtual account order(s).")

    def parse_due_date(self, value):
        value = str(value or "").strip()
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            day = parse_date(value[:10])
            if day is None:
                return None
            parsed = datetime.combine(day, time.max)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def add_sample(self, summary, order, action):
        if len(summary["samples"]) >= 20:
            return
        summary["samples"].append({"order_id": order.od_id, "action": action})
