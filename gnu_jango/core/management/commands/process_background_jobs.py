"""A bounded operator fallback for installations without a broker; never called by a user request."""
import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from gnu_jango.core.background import dispatch_due, execute_job, recover_expired
from gnu_jango.core.background_models import BackgroundJob


class Command(BaseCommand):
    help = "Inspect the outbox; --apply processes due jobs locally, --dispatch publishes IDs to Celery."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--apply", action="store_true")
        group.add_argument("--dispatch", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = min(1000, max(1, options["limit"]))
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
