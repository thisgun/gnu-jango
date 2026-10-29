import json
import time
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.ai.client import semantic_search_enabled
from gnu_jango.site_search.maintenance import SOURCES, audit_sources, index_health
from gnu_jango.site_search.service import ranked_results


class Command(BaseCommand):
    help = "Check readiness, durable pending work, snapshot consistency and anonymous search latency."

    def add_arguments(self, parser):
        parser.add_argument("--query", default="검색")
        parser.add_argument("--max-ms", type=int, default=2000)
        parser.add_argument("--audit-limit", type=int, default=25)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        if (not 2 <= len(options["query"]) <= 200 or "\x00" in options["query"] or options["max_ms"] < 1
                or not 0 <= options["audit_limit"] <= 200):
            raise CommandError("query must be 2..200 characters without NUL; max-ms must be positive")
        if not getattr(settings, "G5_SEARCH_ENABLED", True):
            self.stdout.write(json.dumps({"ready": True, "disabled": True}))
            return
        report = index_health()
        audited, mismatches = 0, 0
        if options["audit_limit"]:
            for kind in SOURCES:
                key = f"site-search:health-cursor:{kind}:v1"
                result = audit_sources(kind=kind, after=cache.get(key, ""), limit=options["audit_limit"])
                audited += result["scanned"]
                mismatches += result["mismatches"]
                cache.set(key, result["cursor"] if result["has_more"] else "", timeout=None)
        report.update(audited_sources=audited, source_mismatches=mismatches)
        if semantic_search_enabled():
            from gnu_jango.ai.store import summary
            report["embeddings"] = summary()
        report["ready"] = report["ready"] and not mismatches
        if report["ready"]:
            start = time.perf_counter()
            rows, _ = ranked_results(SimpleNamespace(user=None, session={}), options["query"], page=1, limit=1)
            report.update(search_ms=round((time.perf_counter() - start) * 1000, 2), returned=len(rows))
            report["ready"] = report["search_ms"] <= options["max_ms"]
        self.stdout.write(json.dumps(report))
        if not report["ready"]:
            raise CommandError("Search health failed; inspect readiness, pending repairs or latency")
