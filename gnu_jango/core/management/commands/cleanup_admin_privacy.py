from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from gnu_jango.core.models import SearchKeyword, SearchKeywordDaily, VisitLog
from gnu_jango.core.privacy import ip_address_for_storage


class Command(BaseCommand):
    help = "Prune old admin analytics rows and optionally anonymize existing IP addresses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=getattr(settings, "ADMIN_VISIT_LOG_RETENTION_DAYS", 180),
            help="Keep analytics rows newer than this many days.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report counts without deleting rows.")
        parser.add_argument(
            "--anonymize-existing",
            action="store_true",
            help="Rewrite existing stored IP addresses with the current masking policy.",
        )

    def handle(self, *args, **options):
        days = max(int(options["days"]), 1)
        cutoff = timezone.now() - timedelta(days=days)
        dry_run = bool(options["dry_run"])

        visit_queryset = VisitLog.objects.filter(created_at__lt=cutoff)
        keyword_queryset = SearchKeyword.objects.filter(last_searched_at__lt=cutoff)
        daily_keyword_queryset = SearchKeywordDaily.objects.filter(day__lt=timezone.localdate() - timedelta(days=days))
        visit_count = visit_queryset.count()
        keyword_count = keyword_queryset.count()
        daily_keyword_count = daily_keyword_queryset.count()

        anonymized = 0
        if options["anonymize_existing"]:
            anonymized = self.anonymize_existing_ips(dry_run=dry_run)

        if not dry_run:
            visit_queryset.delete()
            keyword_queryset.delete()
            daily_keyword_queryset.delete()

        self.stdout.write(
            self.style.SUCCESS(
                "Admin privacy cleanup: "
                f"retention_days={days}, visits={visit_count}, "
                f"keywords={keyword_count}, daily_keyword_counts={daily_keyword_count}, anonymized={anonymized}, "
                f"dry_run={'yes' if dry_run else 'no'}"
            )
        )

    def anonymize_existing_ips(self, *, dry_run):
        updates = []
        for row in VisitLog.objects.exclude(ip_address__isnull=True).only("id", "ip_address").iterator():
            masked = ip_address_for_storage(row.ip_address)
            if masked != row.ip_address:
                row.ip_address = masked
                updates.append(row)
        for row in SearchKeyword.objects.exclude(last_ip_address__isnull=True).only("id", "last_ip_address").iterator():
            masked = ip_address_for_storage(row.last_ip_address)
            if masked != row.last_ip_address:
                row.last_ip_address = masked
                updates.append(row)

        if dry_run or not updates:
            return len(updates)

        visit_updates = [row for row in updates if isinstance(row, VisitLog)]
        keyword_updates = [row for row in updates if isinstance(row, SearchKeyword)]
        if visit_updates:
            VisitLog.objects.bulk_update(visit_updates, ["ip_address"], batch_size=500)
        if keyword_updates:
            SearchKeyword.objects.bulk_update(keyword_updates, ["last_ip_address"], batch_size=500)
        return len(updates)
