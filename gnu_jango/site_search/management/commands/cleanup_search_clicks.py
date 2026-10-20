from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.site_search.models import SearchClickDaily


class Command(BaseCommand):
    help = "Delete daily search click aggregates older than the retention window (default 90 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("--days must be positive")
        count, _ = SearchClickDaily.objects.filter(day__lt=timezone.localdate() - timedelta(days=options["days"])).delete()
        self.stdout.write(f"Deleted {count} expired click aggregates.")
