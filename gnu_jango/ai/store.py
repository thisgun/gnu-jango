"""Nearest-neighbour lookup over stored embeddings.

PostgreSQL with pgvector: cosine distance on ``embedding::vector(<dimensions>)``; for 1024 dimensions
the partial HNSW index from migration 0001 serves the query. Other backends, and PostgreSQL
without pgvector (bytes column): the vectors of one (kind, model, dimensions) are decoded once
per process and scored with a Python dot product (vectors are stored normalised). Callers apply permission filters to the returned ids.
"""
import math
import operator
from array import array

from django.db import connections, transaction
from django.db.models import Count, Max

from .fields import vector_column
from .models import Embedding

_PORTABLE_CACHE = {}
HNSW_EF_SEARCH = 200


def normalize(vector):
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError("An embedding must be a finite, non-zero vector.")
    return [value / norm for value in vector]


def cosine(left, right):
    """Cosine similarity of two vectors of the same size (not necessarily normalised)."""
    dot = sum(map(operator.mul, left, right))
    norms = math.sqrt(sum(map(operator.mul, left, left))) * math.sqrt(sum(map(operator.mul, right, right)))
    return dot / norms if norms else 0.0


def rows(kind, *, model, dimensions, using="default"):
    return Embedding.objects.using(using).filter(kind=kind, model=model, dimensions=dimensions)


def nearest(kind, vector, *, model, dimensions, limit, using="default"):
    """Return up to ``limit`` ``(object_id, similarity)`` pairs, most similar first."""
    if limit <= 0 or len(vector) != dimensions:
        return []
    query = normalize(vector)
    if vector_column(connections[using], Embedding._meta.db_table):
        return _nearest_postgresql(kind, query, model=model, dimensions=dimensions, limit=limit, using=using)
    return _nearest_portable(kind, query, model=model, dimensions=dimensions, limit=limit, using=using)


def postgresql_queryset(kind, query, *, model, dimensions, limit, using="default"):
    """``(object_id, cosine distance)`` rows, ordered so the partial HNSW index can serve them."""
    from django.db.models.functions import Cast
    from pgvector.django import CosineDistance, VectorField

    # Same expression as the index: (embedding::vector(1024)) vector_cosine_ops WHERE dimensions = 1024.
    distance = CosineDistance(Cast("embedding", VectorField(dimensions=dimensions)), query)
    return (
        rows(kind, model=model, dimensions=dimensions, using=using)
        .annotate(_distance=distance)
        .order_by("_distance")
        .values_list("object_id", "_distance")[:limit]
    )


def _nearest_postgresql(kind, query, *, model, dimensions, limit, using):
    # One index serves every kind and model, which are filtered after the HNSW scan; widen the
    # candidate list (default ef_search 40) so a filtered kind still gets ``limit`` neighbours.
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute("SET LOCAL hnsw.ef_search = %s", [max(HNSW_EF_SEARCH, limit)])
        found = list(postgresql_queryset(kind, query, model=model, dimensions=dimensions, limit=limit, using=using))
    return [(object_id, 1.0 - float(value)) for object_id, value in found]


def _portable_vectors(kind, *, model, dimensions, using):
    queryset = rows(kind, model=model, dimensions=dimensions, using=using)
    # A save bumps updated_at, a delete changes the count; either rebuilds the decoded copy.
    state = queryset.aggregate(count=Count("pk"), changed=Max("updated_at"), last=Max("pk"))
    key = (using, kind, model, dimensions)
    fingerprint = (state["count"], state["changed"], state["last"])
    cached = _PORTABLE_CACHE.get(key)
    if cached and cached[0] == fingerprint:
        return cached[1]
    decoded = []
    for object_id, value in queryset.values_list("object_id", "embedding").iterator(chunk_size=500):
        if value is not None and len(value) == dimensions:
            decoded.append((object_id, array("f", value)))
    _PORTABLE_CACHE[key] = (fingerprint, decoded)
    return decoded


def _nearest_portable(kind, query, *, model, dimensions, limit, using):
    query = array("f", query)
    scored = [
        (object_id, float(sum(map(operator.mul, query, vector))))
        for object_id, vector in _portable_vectors(kind, model=model, dimensions=dimensions, using=using)
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]


def clear_cache():
    _PORTABLE_CACHE.clear()


def summary(using="default"):
    """Counts per kind and model, for the admin and ``check_search_health``."""
    queryset = Embedding.objects.using(using).values("kind", "model", "dimensions").annotate(
        count=Count("pk"), updated=Max("updated_at"),
    ).order_by("kind", "model", "dimensions")
    return [
        {**row, "updated": row["updated"].isoformat() if row["updated"] else None}
        for row in queryset
    ]

