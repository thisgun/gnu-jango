"""Bounded repair and read-only diagnostics; no source bodies in reports."""
import hashlib

from django.utils import timezone
from django.db.models import Count, F, FilteredRelation, OuterRef, Q, Subquery

from gnu_jango.bbs.models import Post
from gnu_jango.core.models import ContentPage
from gnu_jango.shop.models import ShopProduct

from .indexing import source_text, tokenizer_version
from .models import SearchDocument, SearchIndexState, SearchSnapshot

SOURCES = {"post": Post, "product": ShopProduct, "page": ContentPage}


def audit_sources(*, kind, using="default", limit=200, after="", enqueue=False):
    """One source and two index identities per row; resume with a typed PK cursor."""
    from .models import SearchIndexRetry
    model = SOURCES[kind]
    rows = model.objects.using(using).order_by("pk")
    if after:
        rows = rows.filter(pk__gt=after)
    version = tokenizer_version()
    generation = SearchIndexState.objects.using(using).filter(kind=kind).values("active_generation")[:1]
    docs = SearchDocument.objects.using(using).filter(**{f"{kind}_id": OuterRef("pk")})
    snapshots = SearchSnapshot.objects.using(using).filter(
        **{f"document__{kind}_id": OuterRef("pk")}, generation=Subquery(generation), tokenizer=version,
    )
    # Source and index fingerprints come from one statement/MVCC snapshot so a
    # concurrent ordinary save cannot create a false mismatch between SELECTs.
    rows = rows.annotate(_index_fingerprint=Subquery(docs.values("fingerprint")[:1]),
                         _snapshot_fingerprint=Subquery(snapshots.values("fingerprint")[:1]),
                         _active_generation=Subquery(generation))
    fields = {"post": ("wr_subject", "wr_content", "wr_option"),
              "product": ("it_name", "it_id", "it_basic", "it_content", "it_explan", "it_brand", "it_model", "it_maker"),
              "page": ("co_subject", "co_content", "co_mobile_content")}[kind]
    result = {"scanned": 0, "mismatches": 0, "enqueued": 0, "cursor": after}
    for source in rows.only("pk", *fields)[:limit].iterator(chunk_size=50):
        title, body = source_text(source, kind)
        digest = hashlib.sha256(f"{version}\0{title}\0{body}".encode()).hexdigest()
        mismatch = source._index_fingerprint != digest
        if source._active_generation:
            mismatch |= source._snapshot_fingerprint != digest
        result["scanned"] += 1
        result["cursor"] = str(source.pk)
        if mismatch:
            result["mismatches"] += 1
            if enqueue:
                SearchIndexRetry.objects.using(using).get_or_create(kind=kind, source_id=str(source.pk))
                result["enqueued"] += 1
    result["has_more"] = bool(result["scanned"] and rows.filter(pk__gt=result["cursor"]).exists())
    return result


def index_health(*, using="default"):
    from .models import SearchIndexRetry
    version = tokenizer_version()
    rows = list(SearchIndexState.objects.using(using).values(
        "kind", "ready", "tokenizer", "active_generation", "building_generation", "build_updated_at"))
    healthy = {r["kind"] for r in rows if r["ready"] and r["active_generation"] and r["tokenizer"] == version}
    stale = sum(bool(r["building_generation"] and (not r["build_updated_at"] or
                (timezone.now() - r["build_updated_at"]).total_seconds() > 1800)) for r in rows)
    generations = SearchIndexState.objects.using(using).exclude(active_generation="").values("active_generation")
    counts = SearchDocument.objects.using(using).alias(_active=FilteredRelation("snapshots", condition=Q(
        snapshots__generation__in=Subquery(generations),
    ))).aggregate(documents=Count("pk", distinct=True), active=Count("_active", distinct=True),
                  mismatches=Count("_active", filter=~Q(_active__fingerprint=F("fingerprint")), distinct=True))
    documents, active, mismatches = counts["documents"], counts["active"], counts["mismatches"]
    pending = SearchIndexRetry.objects.using(using).count()
    # Compare each source with its one-to-one document in the same statement;
    # normal concurrent inserts must not look like missing index rows.
    source_count_difference = sum(model.objects.using(using).filter(searchdocument__isnull=True).count() for model in SOURCES.values())
    return {"ready": set(SOURCES) <= healthy and not stale and not pending and documents == active and not mismatches and not source_count_difference,
            "unready_kinds": sorted(set(SOURCES) - healthy), "documents": documents, "active_snapshots": active,
            "pending": pending, "stale_builds": stale, "snapshot_mismatches": mismatches,
            "source_count_difference": source_count_difference,
            "source_audit_required": True}
