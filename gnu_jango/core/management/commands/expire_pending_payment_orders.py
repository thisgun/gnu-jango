import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gnu_jango.api.v1_shop import (
    CANCELLED_STATUSES,
    ORDER_STATUS_ORDERED,
    cancel_order_and_refund_benefits,
    settle_case_is_bank,
)
from gnu_jango.shop.models import ShopOrder

DEFAULT_GRACE_MINUTES = 120


class Command(BaseCommand):
    help = (
        "Cancel online-payment orders whose payment was never completed (the customer left the "
        "payment window) and give back their stock, points and coupons. Bank-transfer orders and "
        "issued virtual accounts are not touched. Run it from cron, e.g. every 30 minutes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=DEFAULT_GRACE_MINUTES,
            help=f"Only orders older than this many minutes (default {DEFAULT_GRACE_MINUTES}).",
        )
        parser.add_argument("--limit", type=int, default=200, help="Maximum number of orders to inspect.")
        parser.add_argument("--apply", action="store_true", help="Cancel the orders. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        minutes = int(options["minutes"])
        limit = int(options["limit"])
        if minutes < 1 or limit < 1:
            raise CommandError("--minutes and --limit must be positive integers.")

        cutoff = timezone.now() - timedelta(minutes=minutes)
        candidates = (
            ShopOrder.objects.filter(od_status=ORDER_STATUS_ORDERED, od_tno="", od_datetime__lt=cutoff)
            .exclude(od_vbank_status="WAITING_FOR_DEPOSIT")
            .order_by("od_datetime")
        )
        orders = [order for order in candidates[: limit * 2] if not settle_case_is_bank(order.od_settle_case)][:limit]

        summary = {"applied": bool(options["apply"]), "minutes": minutes, "expired": len(orders), "cancelled": 0, "skipped": 0, "samples": []}
        for order in orders:
            if not options["apply"]:
                self._sample(summary, order, "planned")
                continue
            with transaction.atomic():
                locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
                if (
                    not locked
                    or str(locked.od_status or "") in CANCELLED_STATUSES
                    or locked.od_status != ORDER_STATUS_ORDERED
                    or locked.od_tno
                ):
                    summary["skipped"] += 1
                    self._sample(summary, order, "state_changed")
                    continue
                cancel_order_and_refund_benefits(locked, "결제가 완료되지 않아 자동 취소되었습니다.")
            summary["cancelled"] += 1
            self._sample(summary, order, "cancelled")

        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Pending payment expiry: "
                f"expired={summary['expired']} cancelled={summary['cancelled']} skipped={summary['skipped']} "
                f"minutes={minutes} mode={'apply' if options['apply'] else 'dry-run'}"
            )

    def _sample(self, summary, order, action):
        if len(summary["samples"]) < 20:
            summary["samples"].append({"order_id": order.od_id, "settle_case": order.od_settle_case, "action": action})
