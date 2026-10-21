"""Profile anonymous search without rendering pages or recording analytics."""
from collections import defaultdict
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connection

from gnu_jango.site_search import service
from gnu_jango.site_search.indexing import unready_kinds


def query_label(sql):
    if "gnu_jango_cache" in sql:
        return "shared_cache"
    if "wr_content" in sql:
        return "source_excerpt"
    if "site_search_searchdocument" in sql:
        return "count" if "COUNT(" in sql.upper() else "candidates"
    if "site_search_searchclickdaily" in sql:
        return "click_aggregate"
    if "site_search_searchindexstate" in sql:
        return "index_state"
    return "configuration_or_other"


class Command(BaseCommand):
    help = "Measure anonymous search wall/SQL time; reports no raw SQL, snippets, or credentials. Shared cache may be updated."

    def add_arguments(self, parser):
        parser.add_argument("--query", required=True)
        parser.add_argument("--repeat", type=int, default=3)
        parser.add_argument("--type", choices=("all", "post", "product", "document"), default="all")

    def handle(self, *args, **options):
        if not 2 <= len(options["query"]) <= 200 or not 1 <= options["repeat"] <= 10:
            raise CommandError("query must be 2..200 characters and repeat must be 1..10")
        kinds = {"all": ["post", "product", "page"], "post": ["post"], "product": ["product"], "document": ["post", "page"]}
        if not getattr(settings, "G5_SEARCH_ENABLED", True) or unready_kinds(kinds[options["type"]]):
            raise CommandError("Search index is not ready for this result type")
        samples = []
        original = service.hydrate_results
        for iteration in range(options["repeat"]):
            queries, stages = [], {}
            def record(execute, sql, params, many, context):
                start = time.perf_counter()
                try:
                    return execute(sql, params, many, context)
                finally:
                    queries.append({"label": query_label(sql), "ms": (time.perf_counter() - start) * 1000,
                                    "fingerprint": hashlib.sha256(sql.encode()).hexdigest()[:12], "sql_chars": len(sql)})
            def hydrate(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    stages["hydrate_ms"] = round((time.perf_counter() - start) * 1000, 2)
            start = time.perf_counter()
            with connection.execute_wrapper(record), patch.object(service, "hydrate_results", side_effect=hydrate):
                rows, meta = service.ranked_results(SimpleNamespace(user=None, session={}), options["query"],
                                                   result_type=options["type"], page=1, limit=20)
            elapsed = (time.perf_counter() - start) * 1000
            labels = defaultdict(lambda: {"count": 0, "ms": 0})
            for query in queries:
                labels[query["label"]]["count"] += 1
                labels[query["label"]]["ms"] += query["ms"]
            samples.append({"iteration": iteration, "wall_ms": round(elapsed, 2),
                            "sql_ms": round(sum(q["ms"] for q in queries), 2), "sql_count": len(queries),
                            "total": meta["total"], "returned": len(rows), **stages,
                            "by_label": {key: {**value, "ms": round(value["ms"], 2)} for key, value in labels.items()},
                            "slowest": [{**q, "ms": round(q["ms"], 2)} for q in sorted(queries, key=lambda q: -q["ms"])[:3]]})
        self.stdout.write(json.dumps({"database_vendor": connection.vendor, "samples": samples}, ensure_ascii=False))
