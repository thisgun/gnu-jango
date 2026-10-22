import json
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from gnu_jango.core.models import NotificationWork
from gnu_jango.notifications.outbox import process_pending


class Command(BaseCommand):
    help = "Retry notification creation and deliver queued WebSocket hints. Default is read-only."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--watch", action="store_true", help="Run a dedicated worker until interrupted.")
        parser.add_argument("--interval", type=float, default=1)
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 500 or options["interval"] < 0.1:
            raise CommandError("Use limit 1..500 and interval >= 0.1 seconds.")
        if options["watch"] and not options["apply"]:
            raise CommandError("--watch requires --apply.")
        try:
            last_report = 0.0
            while True:
                if options["watch"]:
                    close_old_connections()
                report = process_pending(limit=options["limit"], dry_run=not options["apply"])
                if options["apply"]:
                    # Only completed work expires. Never discard failed/pending notifications.
                    removed, _ = NotificationWork.objects.filter(
                        pk__in=list(NotificationWork.objects.filter(
                            completed_at__lt=timezone.now() - timedelta(days=7),
                        ).values_list("pk", flat=True)[:500]),
                    ).delete()
                    report["pruned"] = removed
                now = time.monotonic()
                if not options["watch"] or report["completed"] or report["failed"] or now - last_report >= 60:
                    self.stdout.write(json.dumps(report))
                    last_report = now
                if not options["watch"]:
                    break
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            return
