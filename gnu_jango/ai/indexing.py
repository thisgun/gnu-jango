"""Incremental embedding builds. Runs from ``build_embeddings`` only, never on a request."""
import hashlib
import logging

from django.db import transaction

from . import sources
from .models import Embedding
from .store import normalize

logger = logging.getLogger(__name__)
KINDS = (Embedding.KIND_DOCS, Embedding.KIND_PRODUCT)


def text_hash(provider, text):
    return hashlib.sha256(f"{provider.model}\0{provider.dimensions}\0{text}".encode("utf-8")).hexdigest()


def build(kind, provider, *, rebuild=False, limit=None, dry_run=False):
    """Embed new or changed rows of ``kind`` and delete rows whose source is gone or hidden.

    ``limit`` caps how many texts are sent this run; the rest are reported as ``deferred`` and
    picked up by the next run. Batches are saved as they finish, so a provider failure keeps the
    work already done and the error propagates to the caller.
    """
    wanted = {object_id: (text, board_id) for object_id, text, board_id in sources.eligible(kind)}
    existing = dict(Embedding.objects.filter(kind=kind).values_list("object_id", "text_hash"))
    stale = sorted(set(existing) - set(wanted))
    pending = []
    for object_id, (text, board_id) in wanted.items():
        digest = text_hash(provider, text)
        if rebuild or existing.get(object_id) != digest:
            pending.append((object_id, text, board_id, digest))
    deferred = 0
    if limit is not None and len(pending) > limit:
        deferred = len(pending) - limit
        pending = pending[:limit]
    report = {
        "kind": kind, "eligible": len(wanted), "embedded": 0, "unchanged": len(wanted) - len(pending) - deferred,
        "pruned": len(stale), "deferred": deferred,
    }
    if dry_run:
        report["would_embed"] = len(pending)
        return report
    if stale:
        Embedding.objects.filter(kind=kind, object_id__in=stale).delete()
    batch_size = max(1, int(getattr(provider, "batch_size", 16) or 16))
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        vectors = provider.embed([text for _, text, _, _ in batch])
        if len(vectors) != len(batch):
            raise ValueError("The embedding provider returned a different number of vectors.")
        with transaction.atomic():
            for (object_id, _, board_id, digest), vector in zip(batch, vectors):
                Embedding.objects.update_or_create(kind=kind, object_id=object_id, defaults={
                    "board_id": board_id, "model": provider.model, "dimensions": provider.dimensions,
                    "text_hash": digest, "embedding": normalize(vector),
                })
        report["embedded"] += len(batch)
    return report
