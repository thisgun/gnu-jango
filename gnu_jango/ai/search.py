"""Hybrid retrieval: lexical results merged with semantic neighbours by reciprocal rank fusion.

Every entry point returns its lexical input unchanged when semantic search is off, when no
neighbour passes the similarity floor, or when the endpoint or vector query fails (logged as a
warning). Neighbours are always re-filtered through the caller's permission/on-sale queryset, so
semantic matching never shows a row that the lexical path would hide.
"""
import hashlib
import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, FloatField, Q, Value, When

from . import conf, store
from .client import get_provider
from .fields import pack, unpack
from .models import Embedding

logger = logging.getLogger(__name__)
RRF_K = 60
QUERY_CACHE_SECONDS = 300
SEMANTIC_LIMIT = 20
LEXICAL_POOL = 200
BACKOFF_KEY = "ai:embedding-endpoint:backoff:v1"
BACKOFF_SECONDS = 30
# Only the start of a query is embedded: unified search already refuses more than 200 characters,
# but product search takes any ?q=, and each new long query would be one more endpoint call.
MAX_QUERY_CHARS = 200


def reciprocal_rank_fusion(rankings, *, k=RRF_K):
    """``{key: sum(1 / (k + rank))}`` over ranked key lists (rank starts at 1)."""
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _active_provider():
    if not conf.semantic_search_requested():
        return None
    return get_provider(timeout=conf.query_timeout())


def _query_vector(provider, query):
    digest = hashlib.sha256(f"{provider.model}\0{provider.dimensions}\0{query}".encode("utf-8")).hexdigest()
    key = f"ai:query-embedding:v1:{digest}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached:
        return unpack(cached).tolist()
    vector = provider.embed([query])[0]
    try:
        cache.set(key, pack(vector), QUERY_CACHE_SECONDS)
    except Exception:
        logger.warning("Could not cache a query embedding.", exc_info=True)
    return vector


def _endpoint_recently_failed():
    try:
        return bool(cache.get(BACKOFF_KEY))
    except Exception:
        return False


def _remember_failure():
    try:
        cache.set(BACKOFF_KEY, 1, BACKOFF_SECONDS)
    except Exception:
        pass


def semantic_neighbours(kinds, query, *, limit=SEMANTIC_LIMIT):
    """``{kind: [(object_id, similarity)]}`` above the similarity floor; empty lists when off or on error.

    The query is embedded once for all kinds. After an endpoint failure, searches skip the
    endpoint for ``BACKOFF_SECONDS`` so a dead model does not add its timeout to every request.
    """
    found = {kind: [] for kind in kinds}
    provider = _active_provider()
    query = str(query or "").strip()[:MAX_QUERY_CHARS].strip()
    if provider is None or not query or not kinds or _endpoint_recently_failed():
        return found
    try:
        vector = _query_vector(provider, query)
    except Exception as exc:
        _remember_failure()
        logger.warning("Semantic search unavailable; using lexical results (error_type=%s).", type(exc).__name__)
        return found
    floor = conf.min_similarity()
    for kind in kinds:
        try:
            # A savepoint keeps a failed vector query from breaking the request's transaction.
            with transaction.atomic():
                rows = store.nearest(kind, vector, model=provider.model, dimensions=provider.dimensions,
                                     limit=limit * 3)
        except Exception as exc:
            logger.warning("Semantic search unavailable; using lexical results (kind=%s error_type=%s).",
                           kind, type(exc).__name__)
            continue
        found[kind] = [(object_id, similarity) for object_id, similarity in rows if similarity >= floor]
    return found


def semantic_matches(kind, query, *, limit=SEMANTIC_LIMIT):
    return semantic_neighbours((kind,), query, limit=limit)[kind]


def fuse_site_results(query, ranked, docs, allowed_body, *, result_type, docs_group):
    """Merge unified-search rows ``[(SearchDocument, score, type)]``; returns ``(rows, added)``.

    ``docs``/``allowed_body`` come from ``site_search.service.visible_documents``: the same board,
    read-level, on-sale and type filters as the lexical query. A handbook neighbour also needs a
    readable body, since its match came from the body text.
    """
    kinds = {"all": (Embedding.KIND_PRODUCT, Embedding.KIND_DOCS), "product": (Embedding.KIND_PRODUCT,),
             "document": (Embedding.KIND_DOCS,)}.get(result_type, ())
    if not kinds or _active_provider() is None:
        return ranked, 0
    kinds = tuple(kind for kind in kinds if docs_group or kind != Embedding.KIND_DOCS)
    neighbours = [
        (similarity, kind, object_id)
        for kind, matches in semantic_neighbours(kinds, query).items()
        for object_id, similarity in matches
    ]
    if not neighbours:
        return ranked, 0
    neighbours.sort(key=lambda item: -item[0])
    product_ids = [object_id for _, kind, object_id in neighbours if kind == Embedding.KIND_PRODUCT]
    post_ids = [int(object_id) for _, kind, object_id in neighbours if kind == Embedding.KIND_DOCS and object_id.isdigit()]
    condition = Q(pk__in=[])
    if product_ids:
        condition |= Q(kind="product", product_id__in=product_ids)
    if post_ids:
        condition |= Q(kind="post", post_id__in=post_ids, post__board__group__gr_id=docs_group)
    rows = docs.filter(condition).filter(allowed_body).only("pk", "kind", "title", "post_id", "product_id", "page_id")
    by_source = {("post", str(row.post_id)) if row.kind == "post" else ("product", str(row.product_id)): row
                 for row in rows}
    semantic = []
    for _, kind, object_id in neighbours:
        row = by_source.get(("post" if kind == Embedding.KIND_DOCS else "product", object_id))
        if row is not None:
            semantic.append(row)
    semantic = semantic[:SEMANTIC_LIMIT]
    if not semantic:
        return ranked, 0
    entries = {doc.pk: (doc, result_kind) for doc, _, result_kind in ranked}
    added = 0
    for row in semantic:
        if row.pk not in entries:
            entries[row.pk] = (row, "document" if row.kind == "post" else "product")
            added += 1
    lexical_order = [doc.pk for doc, _, _ in ranked]
    scores = reciprocal_rank_fusion([lexical_order, [row.pk for row in semantic]])
    position = {pk: index for index, pk in enumerate(lexical_order)}
    fused = sorted(entries, key=lambda pk: (-scores[pk], position.get(pk, len(position)), pk))
    return [(entries[pk][0], round(scores[pk], 6), entries[pk][1]) for pk in fused], added


def _bigrams(text):
    compact = "".join(str(text or "").lower().split())
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _closest_paragraph(paragraphs, query):
    """The paragraph sharing the most character bigrams with the question (first on ties)."""
    wanted = _bigrams(query)
    best = paragraphs[0]
    best_score = -1
    for paragraph in paragraphs:
        score = len(wanted & _bigrams(f"{paragraph.section} {paragraph.text}"))
        if score > best_score:
            best, best_score = paragraph, score
    return best


def fuse_docs_chapters(query, ranked, candidates):
    """Merge handbook ask chapters ``[(position, SearchDocument, score)]``.

    ``candidates`` are the paragraphs the asker may read (secret chapters already removed); a
    semantic chapter outside them is ignored. A chapter found only semantically is represented
    by its paragraph closest to the question.
    """
    if _active_provider() is None:
        return ranked
    paragraphs = {}
    first_position = {}
    for position, doc in enumerate(candidates):
        paragraphs.setdefault(doc.post_id, []).append(doc)
        first_position.setdefault(doc.post_id, position)
    semantic = [int(object_id) for object_id, _ in semantic_matches(Embedding.KIND_DOCS, query)
                if object_id.isdigit() and int(object_id) in paragraphs][:SEMANTIC_LIMIT]
    if not semantic:
        return ranked
    entries = {doc.post_id: (position, doc) for position, doc, _ in ranked}
    for post_id in semantic:
        if post_id not in entries:
            doc = _closest_paragraph(paragraphs[post_id], query)
            entries[post_id] = (first_position[post_id], doc)
    lexical_order = [doc.post_id for _, doc, _ in ranked]
    scores = reciprocal_rank_fusion([lexical_order, semantic])
    order = {post_id: index for index, post_id in enumerate(lexical_order)}
    fused = sorted(entries, key=lambda post_id: (-scores[post_id], order.get(post_id, len(order)), post_id))
    return [(entries[post_id][0], entries[post_id][1], round(scores[post_id], 6)) for post_id in fused]


def fuse_product_queryset(base, lexical, term):
    """Merge product search: ``lexical`` matches plus semantic neighbours inside ``base``.

    ``base`` is the storefront queryset before the text filter (on sale, visible category and any
    category filter), so neighbours obey the same visibility. The result carries a fused
    ``_search_rank`` that ``products_response`` orders by for relevance sorting.
    """
    if _active_provider() is None:
        return lexical
    matches = semantic_matches(Embedding.KIND_PRODUCT, term)
    if not matches:
        return lexical
    allowed = set(base.filter(pk__in=[object_id for object_id, _ in matches]).values_list("pk", flat=True))
    semantic = [object_id for object_id, _ in matches if object_id in allowed][:SEMANTIC_LIMIT]
    if not semantic:
        return lexical
    lexical_order = list(lexical.values_list("pk", flat=True)[:LEXICAL_POOL])
    scores = reciprocal_rank_fusion([lexical_order, semantic])
    rank = Case(*(When(pk=pk, then=Value(score)) for pk, score in scores.items()),
                default=Value(0.0), output_field=FloatField())
    return base.filter(Q(pk__in=lexical.values("pk")) | Q(pk__in=semantic)).annotate(_search_rank=rank)
