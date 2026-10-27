"""A bounded operator fallback for installations without a broker; never called by a user request."""
import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.core.background import dispatch_due, execute_job, recover_expired
from gnu_jango.core.background_models import BackgroundJob


class Command(BaseCommand):
    help = (
        "Inspect the outbox; --apply processes due jobs locally, --dispatch publishes IDs to "
        "Celery, and --check alerts on dead or stale pending jobs."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--apply", action="store_true")
        group.add_argument("--dispatch", action="store_true")
        group.add_argument("--check", action="store_true", help="Exit non-zero when dead/stale jobs exist.")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-pending-minutes", type=int, default=15)

    def handle(self, *args, **options):
        limit = min(1000, max(1, options["limit"]))
        if options["check"]:
            self._check(int(options["max_pending_minutes"]))
            return
        if options["dispatch"]:
            result = dispatch_due(limit)
        elif options["apply"]:
            recover_expired(limit)
            ids = list(BackgroundJob.objects.filter(status="pending", available_at__lte=timezone.now())
                       .order_by("available_at").values_list("pk", flat=True)[:limit])
            result = {"jobs": [execute_job(job_id) for job_id in ids]}
        else:
            result = {status: BackgroundJob.objects.filter(status=status).count() for status, _ in BackgroundJob.STATUS}
        self.stdout.write(json.dumps(result))

    def _check(self, max_pending_minutes):
        max_pending_minutes = max(1, max_pending_minutes)
        now = timezone.now()
        stale_cutoff = now - timedelta(minutes=max_pending_minutes)
        pending = BackgroundJob.objects.filter(status="pending")
        dead = BackgroundJob.objects.filter(status="dead").count()
        stale = pending.filter(available_at__lte=stale_cutoff).count()
        oldest = pending.order_by("available_at").values_list("available_at", flat=True).first()
        oldest_age = int((now - oldest).total_seconds()) if oldest else 0
        result = {
            "ok": dead == 0 and stale == 0,
            "dead": dead,
            "stale_pending": stale,
            "pending": pending.count(),
            "oldest_pending_seconds": max(0, oldest_age),
            "max_pending_minutes": max_pending_minutes,
            "counts": {
                status: BackgroundJob.objects.filter(status=status).count()
                for status, _ in BackgroundJob.STATUS
            },
        }
        self.stdout.write(json.dumps(result))
        if not result["ok"]:
            raise CommandError("Background jobs need attention: dead or stale pending jobs exist.")
