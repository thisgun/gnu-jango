"""Send the shop's alert messages that are due: 가격 인하 알림, 재입고 SMS (automatic) and 장바구니 알림 메일."""

import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.shop.cart_reminders import DEFAULT_BATCH_LIMIT as CART_LIMIT
from gnu_jango.shop.cart_reminders import reminder_options, send_due_cart_reminders
from gnu_jango.shop.price_alerts import DEFAULT_BATCH_LIMIT as PRICE_LIMIT
from gnu_jango.shop.price_alerts import price_alerts_enabled, send_due_price_alerts
from gnu_jango.shop.restock import SEND_LIMIT as RESTOCK_LIMIT
from gnu_jango.shop.restock import send_due_restock_sms
from gnu_jango.shop.shop_options import shop_options


class Command(BaseCommand):
    help = (
        "Send due price-drop alerts (de_price_alert_use), restock SMS (de_stock_sms_auto) and cart "
        "reminder mails (de_cart_reminder_use); each kind runs only while its shop setting is on. "
        "Without --apply, count what is due without sending."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Send. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")
        parser.add_argument(
            "--limit", type=int, default=0,
            help=f"Maximum messages of each kind in one run (default {PRICE_LIMIT} price alerts, "
                 f"{RESTOCK_LIMIT} SMS, {CART_LIMIT} cart mails).",
        )

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 0:
            raise CommandError("--limit must not be negative.")
        dry_run = not options["apply"]
        summary = {"dry_run": dry_run, "price_alerts": None, "restock_sms": None, "cart_reminders": None}
        if price_alerts_enabled():
            summary["price_alerts"] = send_due_price_alerts(dry_run=dry_run, limit=limit or PRICE_LIMIT)
        if shop_options("de_stock_sms_auto")["de_stock_sms_auto"]:
            summary["restock_sms"] = send_due_restock_sms(dry_run=dry_run, limit=min(limit or RESTOCK_LIMIT, RESTOCK_LIMIT))
        if reminder_options()["enabled"]:
            summary["cart_reminders"] = send_due_cart_reminders(dry_run=dry_run, limit=limit or CART_LIMIT)
        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
            return
        for kind in ("price_alerts", "restock_sms", "cart_reminders"):
            self.stdout.write(f"{kind}: {summary[kind] if summary[kind] is not None else 'off'}")
