"""Similar products from the stored product embeddings (optional, G5_AI_SIMILAR_PRODUCTS).

The product's own stored vector is the query, so a product page never calls the embedding
endpoint. A product without an embedding for the configured model (not built yet, or built with
another model) gets no similar products. Neighbours are re-filtered through the caller's
storefront queryset, so a hidden or off-sale product is never recommended.
"""
import hashlib
import json
import logging

from django.core.cache import cache
from django.db import transaction

from . import conf, store
from .client import get_provider
from .models import Embedding

logger = logging.getLogger(__name__)
SIMILAR_LIMIT = 4
# Neighbours fetched and cached per product, enough for the limit plus excluded related products.
NEIGHBOUR_POOL = 30
NEIGHBOUR_CACHE_SECONDS = 60 * 60


def similar_products(product, base, *, exclude=(), limit=SIMILAR_LIMIT):
    """Up to ``limit`` products of ``base`` closest to ``product``, most similar first.

    ``exclude`` ids (the admin's related products) and ``product`` itself are skipped; neighbours
    under G5_AI_SIMILAR_MIN_SIMILARITY are dropped. Any failure is logged and returns [].
    """
    if limit <= 0 or not conf.similar_products_requested():
        return []
    provider = get_provider()
    if provider is None:
        return []
    skip = {str(product.pk), *(str(item) for item in exclude)}
    try:
        # A savepoint keeps a failed vector query from breaking the request's transaction.
        with transaction.atomic():
            neighbours = _neighbours(product, provider, limit * 3 + len(skip))
    except Exception as exc:
        logger.warning("Similar products unavailable (product=%s error_type=%s).", product.pk, type(exc).__name__)
        return []
    floor = conf.similar_min_similarity()
    ranked = [object_id for object_id, similarity in neighbours if object_id not in skip and similarity >= floor]
    if not ranked:
        return []
    allowed = {item.pk: item for item in base.filter(pk__in=ranked)}
    return [allowed[object_id] for object_id in ranked if object_id in allowed][:limit]


def _neighbours(product, provider, pool):
    """``[(object_id, similarity)]`` nearest to the product's stored vector, cached per vector state.

    Scoring every stored vector costs about 50 microseconds a row on the portable (SQLite) path,
    a quarter of a second per page view for 5,000 products, and the answer only changes when an
    embedding does, so it is kept under the kind's fingerprint for an hour.
    """
    pool = max(pool, NEIGHBOUR_POOL)
    state = store.fingerprint(Embedding.KIND_PRODUCT, model=provider.model, dimensions=provider.dimensions)
    digest = hashlib.sha256(
        json.dumps([provider.model, provider.dimensions, str(product.pk), pool, state], default=str).encode("utf-8")
    ).hexdigest()
    key = f"ai:similar:v1:{digest}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    vector = (
        store.rows(Embedding.KIND_PRODUCT, model=provider.model, dimensions=provider.dimensions)
        .filter(object_id=str(product.pk))
        .values_list("embedding", flat=True)
        .first()
    )
    neighbours = [] if vector is None else store.nearest(
        Embedding.KIND_PRODUCT, [float(value) for value in vector], model=provider.model,
        dimensions=provider.dimensions, limit=pool,
    )
    try:
        cache.set(key, neighbours, NEIGHBOUR_CACHE_SECONDS)
    except Exception:
        logger.warning("Similar products not cached.", exc_info=True)
    return neighbours
