import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.core.background import replay
from gnu_jango.core.background_models import BackgroundJob


class Command(BaseCommand):
    help = "Inspect one dead-letter UUID. --apply requeues; --allow-uncertain acknowledges duplicate delivery risk."

    def add_arguments(self, parser):
        parser.add_argument("--id", required=True, type=str)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--allow-uncertain", action="store_true")

    def handle(self, *args, **options):
        import uuid
        try:
            job_id = uuid.UUID(options["id"])
        except ValueError:
            raise CommandError("Pass a valid job UUID.") from None
        job = BackgroundJob.objects.filter(pk=job_id).first()
        if job is None:
            raise CommandError("Job not found.")
        if options["apply"]:
            if not replay(job, allow_uncertain=options["allow_uncertain"]):
                raise CommandError("Job cannot be replayed: check status, retained payload and uncertain-delivery acknowledgement.")
            job.refresh_from_db()
        self.stdout.write(json.dumps({"id": str(job.pk), "kind": job.kind, "operation": job.operation, "status": job.status,
                                      "attempts": job.attempts, "error_code": job.error_code}))
