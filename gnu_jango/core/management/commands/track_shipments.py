"""Look up shipped orders at Delivery Tracker (shop/delivery_tracking.py)."""

import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.shop.delivery_tracking import due_orders, refresh_order_tracking
from gnu_jango.shop.delivery_tracking_settings import tracking_config
from gnu_jango.shop.order_points import run_save_order_points_safely

DEFAULT_LIMIT = 30
MAX_LIMIT = 200
# each lookup may take up to the client's 15 second timeout; stay inside a worker's minute
TIME_BUDGET_SECONDS = 45


class Command(BaseCommand):
    help = (
        "Look up 배송 orders with an invoice of a Delivery Tracker courier that are due (never looked up, "
        "invoice changed, called back by the webhook or past their next check) and record the tracking. "
        "Does nothing while tracking is off or the keys are missing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum orders to look up (default {DEFAULT_LIMIT}, at most {MAX_LIMIT}).",
        )
        parser.add_argument("--apply", action="store_true", help="Look the orders up. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 1 or limit > MAX_LIMIT:
            raise CommandError(f"--limit must be between 1 and {MAX_LIMIT}.")
        config = tracking_config()
        summary = {
            "enabled": config.enabled,
            "applied": bool(options["apply"]),
            "limit": limit,
            "inspected": 0,
            "updated": 0,
            "delivered": 0,
            "completed": 0,
            "not_found": 0,
            "failed": 0,
            "timed_out": False,
            "samples": [],
        }
        orders = (
            due_orders(now=timezone.now(), limit=limit, complete_on_delivered=config.complete_on_delivered)
            if config.enabled
            else []
        )
        summary["inspected"] = len(orders)
        started = time.monotonic()
        for order in orders:
            if not options["apply"]:
                self._sample(summary, order, "planned")
                continue
            if time.monotonic() - started >= TIME_BUDGET_SECONDS:
                summary["timed_out"] = True
                break
            try:
                result = refresh_order_tracking(order, config=config, pay_due_points=False)
            except Exception as exc:  # noqa: BLE001 - one bad order must not stop the batch
                summary["failed"] += 1
                self._sample(summary, order, f"failed:exception:{type(exc).__name__}")
                continue
            key = {"updated": "updated", "delivered": "delivered", "not_found": "not_found"}.get(result.status, "failed")
            summary[key] += 1
            if result.completed:
                summary["completed"] += 1
            self._sample(summary, order, result.status + (":completed" if result.completed else ""))
        if summary["completed"]:
            run_save_order_points_safely()  # once for the whole run, like the admin's bulk 완료
        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Shipment tracking: "
                f"enabled={summary['enabled']} inspected={summary['inspected']} updated={summary['updated']} "
                f"delivered={summary['delivered']} completed={summary['completed']} "
                f"not_found={summary['not_found']} failed={summary['failed']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )

    def _sample(self, summary, order, action):
        if len(summary["samples"]) < 20:
            summary["samples"].append({"order_id": order.od_id, "action": action})
