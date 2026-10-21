from datetime import timedelta
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.site_search.models import SearchClickDaily


class Command(BaseCommand):
    help = "Delete daily search click aggregates older than the retention window (default 90 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("--days must be positive")
        rows = SearchClickDaily.objects.filter(day__lt=timezone.localdate() - timedelta(days=options["days"]))
        count = rows.count()
        if not options["dry_run"]:
            rows.delete()
        report = {"expired": count, "deleted": 0 if options["dry_run"] else count,
                  "retention_days": options["days"], "dry_run": options["dry_run"]}
        self.stdout.write(json.dumps(report) if options["json"] else str(report))
