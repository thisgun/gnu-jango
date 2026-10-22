from datetime import timedelta
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gnu_jango.site_search.indexing import index_instance
from gnu_jango.site_search.maintenance import SOURCES
from gnu_jango.site_search.models import SearchIndexRetry


class Command(BaseCommand):
    help = "Retry bounded durable search work; dry run unless --apply. No raw source or exception text."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--database", default="default")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 200:
            raise CommandError("limit must be 1..200")
        using = options["database"]
        due = SearchIndexRetry.objects.using(using).filter(available_at__lte=timezone.now()).order_by("available_at", "pk")
        report = {"due": due.count(), "processed": 0, "repaired": 0, "missing": 0, "failed": 0, "applied": options["apply"]}
        for identity in list(due.values("pk", "kind", "source_id")[:options["limit"]]) if options["apply"] else []:
            with transaction.atomic(using=using):
                # Same order as a normal save: source, then retry. Locking the
                # retry first would deadlock a writer holding the source row.
                source = SOURCES[identity["kind"]].objects.using(using).select_for_update().filter(pk=identity["source_id"]).first()
                work = SearchIndexRetry.objects.using(using).select_for_update().filter(pk=identity["pk"], available_at__lte=timezone.now()).first()
                if work is None:
                    continue
                report["processed"] += 1
                if source is None:
                    work.delete(using=using)
                    report["missing"] += 1
                    continue
                try:
                    index_instance(source, work.kind, using=using)
                except Exception as exc:
                    work.attempts += 1
                    work.error_type = type(exc).__name__[:80]
                    work.available_at = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** min(work.attempts, 7)))
                    work.save(using=using, update_fields=["attempts", "error_type", "available_at"])
                    report["failed"] += 1
                else:
                    work.delete(using=using)
                    report["repaired"] += 1
        self.stdout.write(json.dumps(report))
        if report["failed"]:
            raise CommandError("Search repairs failed; retained for retry with backoff")
