"""Synthetic load fixture guarded to disposable local databases."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections, transaction

from gnu_jango.core.models import ContentPage
from gnu_jango.site_search.indexing import encoded, source_text, terms, tokenizer_version
from gnu_jango.site_search.maintenance import SOURCES, index_health
from gnu_jango.site_search.models import SearchDocument, SearchIndexState, SearchSnapshot, SearchSnapshotPosting
from gnu_jango.site_search.service import ranked_results


def timed_search(query):
    start = time.perf_counter()
    rows, meta = ranked_results(SimpleNamespace(user=None, session={}), query, page=1, limit=20)
    return {"ms": round((time.perf_counter() - start) * 1000, 2), "ids": [row["id"] for row in rows[:3]],
            "total": meta["total"], "truncated": meta["truncated"]}


def summary(samples):
    values = sorted(s["ms"] for s in samples)
    import math
    return {"count": len(values), "mean_ms": round(statistics.mean(values), 2),
            "p95_ms": values[math.ceil(len(values) * .95) - 1], "max_ms": values[-1]}


class Command(BaseCommand):
    help = "Seed/measure/remove synthetic search data ONLY in a named empty disposable local database."

    def add_arguments(self, parser):
        parser.add_argument("--documents", type=int, default=10000)
        parser.add_argument("--concurrency", type=int, default=4)
        parser.add_argument("--repeats", type=int, default=3)
        parser.add_argument("--max-p95-ms", type=int, default=2000)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--allow-isolated-db", action="store_true")

    def handle(self, *args, **options):
        db = connection.settings_dict
        local_pg = connection.vendor == "postgresql" and db["HOST"] in {"localhost", "127.0.0.1"} and str(db["NAME"]).startswith("gnu_jango_search_bench_")
        local_sqlite = connection.vendor == "sqlite" and Path(db["NAME"]).name.startswith("search-benchmark-")
        if not options["allow_isolated_db"] or not (local_pg or local_sqlite):
            raise CommandError("Requires --allow-isolated-db and a disposable local gnu_jango_search_bench_* / search-benchmark-* DB")
        if (not 1000 <= options["documents"] <= 50000 or not 1 <= options["concurrency"] <= 8
                or not 1 <= options["repeats"] <= 5 or options["max_p95_ms"] < 1):
            raise CommandError("documents=1000..50000, concurrency=1..8, repeats=1..5")
        if SearchDocument.objects.exists() or SearchIndexState.objects.exists() or any(model.objects.exists() for model in SOURCES.values()):
            raise CommandError("Refusing a nonempty source/index database")
        prefix, generation = "bench-" + uuid.uuid4().hex[:8], uuid.uuid4().hex
        created = False
        report = {"documents": options["documents"], "database_vendor": connection.vendor,
                  "concurrency": options["concurrency"], "synthetic": True, "cold_start_verified": False}
        try:
            created = True
            self.seed(prefix, generation, options["documents"])
            targets = [n * (options["documents"] - 1) // 19 for n in range(20)]
            cases, hits = [], 0
            for index in targets:
                code = f"benchid{index:05}x"
                for query in (code, code[:-1], code[:-1].upper(), f"문서는 {code}", f"{code} 조회 방법"):
                    result = timed_search(query)
                    hit = f"{prefix}-{index:05}" in result["ids"]
                    hits += hit
                    cases.append({"query": query, "hit_top3": hit, "ms": result["ms"]})
            report["quality"] = {"cases": len(cases), "hits_top3": hits, "rate": hits / len(cases)}
            timed_search("검색")  # warmup, excluded
            report["broad_sequential"] = summary([timed_search("검색") for _ in range(options["repeats"])])
            def worker(_):
                try:
                    return timed_search("검색")
                finally:
                    connections.close_all()
            def writer():
                try:
                    page = ContentPage.objects.get(pk=f"{prefix}-00000")
                    for n in range(10):
                        page.co_content = f"동시 수정 본문 {n}"
                        page.save(update_fields=["co_content"])
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=options["concurrency"] + 1) as pool:
                write = pool.submit(writer)
                samples = list(pool.map(worker, range(options["concurrency"] * options["repeats"])))
                write.result()
            report["broad_concurrent"] = summary(samples)
            report["broad_total"] = samples[-1]["total"]
            report["candidate_truncated"] = samples[-1]["truncated"]
            report["index_after_concurrent_writes"] = index_health()
            report["latency_budget_ms"] = options["max_p95_ms"]
            report["passed"] = (hits == len(cases) and report["index_after_concurrent_writes"]["ready"]
                                and report["broad_concurrent"]["p95_ms"] <= options["max_p95_ms"]
                                and report["broad_sequential"]["p95_ms"] <= options["max_p95_ms"])
        finally:
            if created:
                ContentPage.objects.filter(co_id__startswith=prefix + "-").delete()
                SearchIndexState.objects.filter(active_generation=generation).delete()
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report, ensure_ascii=False))
        if not report["passed"]:
            raise CommandError("Synthetic search benchmark acceptance failed")

    def seed(self, prefix, generation, count):
        version = tokenizer_version()
        for start in range(0, count, 200):
            sources, docs, snapshots = [], [], []
            for index in range(start, min(start + 200, count)):
                sources.append(ContentPage(co_id=f"{prefix}-{index:05}", co_subject=f"검색 부하 문서 benchid{index:05}x",
                    co_content="공통 설명과 검색 설정 안내. " * (1000 if index % 100 == 0 else 2)))
            with transaction.atomic():
                ContentPage.objects.bulk_create(sources, batch_size=200)
                for source in sources:
                    title, body = source_text(source, "page")
                    digest = hashlib.sha256(f"{version}\0{title}\0{body}".encode()).hexdigest()
                    docs.append(SearchDocument(kind="page", page_id=source.pk, title=title, tokenizer=version, fingerprint=digest,
                        title_tokens=" ".join(map(encoded, terms(title, 256))), body_tokens=" ".join(map(encoded, terms(body, 4096)))))
                SearchDocument.objects.bulk_create(docs, batch_size=200)
                snapshots = SearchSnapshot.objects.bulk_create([SearchSnapshot(document=doc, generation=generation,
                    title_tokens=doc.title_tokens, body_tokens=doc.body_tokens, tokenizer=version, fingerprint=doc.fingerprint) for doc in docs], batch_size=200)
                if connection.vendor != "postgresql":
                    postings = [SearchSnapshotPosting(snapshot=snapshot, field=field, term=bytes.fromhex(token[1:]).decode(), frequency=n)
                                for snapshot in snapshots for field, text in (("title", snapshot.title_tokens), ("body", snapshot.body_tokens))
                                for token, n in Counter(text.split()).items()]
                    SearchSnapshotPosting.objects.bulk_create(postings, batch_size=500)
        SearchIndexState.objects.bulk_create([SearchIndexState(kind=kind, ready=True, tokenizer=version, active_generation=generation) for kind in SOURCES])
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("ANALYZE site_search_searchsnapshot")
