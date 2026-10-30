"""Charge the 정기구독 subscriptions that are due (shop/subscriptions.py run_scheduled)."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from gnu_jango.shop.subscriptions import run_scheduled


class Command(BaseCommand):
    help = (
        "Charge the subscriptions due today with their registered cards (Toss billing), settle charges "
        "whose answer was lost, send the upcoming-charge notices and drop unfinished card registrations. "
        "Does nothing while subscriptions are switched off. Without --apply, count only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100, help="Maximum subscriptions to charge in one run.")
        parser.add_argument("--date", default="", help="Charge as of this date (YYYY-MM-DD; default today).")
        parser.add_argument("--apply", action="store_true", help="Charge. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("--limit must be positive.")
        today = None
        if options["date"]:
            today = parse_date(options["date"])
            if today is None:
                raise CommandError("--date must be YYYY-MM-DD.")
        summary = run_scheduled(today=today, apply=bool(options["apply"]), limit=limit)
        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
            return
        self.stdout.write(
            "Subscriptions: enabled={enabled} due={due} charged={charged} failed={failed} skipped={skipped} "
            "pending={pending} review={review} notices={notices} mode={mode}".format(
                **summary, mode="apply" if summary["applied"] else "dry-run"
            )
        )
