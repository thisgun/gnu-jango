"""Permission-aware indexed retrieval shared by the unified and compatibility APIs."""
from datetime import timedelta
from functools import reduce
from math import log1p
from operator import or_
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.models import BigIntegerField, BooleanField, Case, Exists, FloatField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from gnu_jango.api.access import readable_post_queryset
from gnu_jango.api.shop_common import on_sale_products
from gnu_jango.bbs.models import Post
from gnu_jango.bbs.utils import get_pretty_url
from gnu_jango.core.models import ContentPage, SearchKeywordDaily
from gnu_jango.docs_search.ranking import bm25_scores
from gnu_jango.docs_search.service import _snippet, docs_group_id
from gnu_jango.users import point_ledger
from gnu_jango.users.models import User_Point
from gnu_jango.utils.users import is_admin

from .indexing import encoded, source_text, terms, unready_kinds
from .models import SearchClickDaily, SearchDocument, SearchPosting

CANDIDATE_LIMIT = 200
MAX_QUERY_TERMS = 24


def body_readable_posts(request, queryset):
    queryset = readable_post_queryset(request, queryset).exclude(wr_option__contains="secret")
    user = getattr(request, "user", None)
    if not point_ledger.points_enabled() or (user and is_admin(user)):
        return queryset
    free = Q(board__bo_read_point__gte=0)
    if not getattr(user, "is_authenticated", False):
        return queryset.filter(free)
    queryset = queryset.alias(_search_point_id=Case(
        When(legacy_wr_id__gt=0, then="legacy_wr_id"), default="pk", output_field=BigIntegerField(),
    ))
    paid = User_Point.objects.filter(
        user=user, po_rel_table=OuterRef("board__bo_table"), po_rel_action="읽기",
        po_rel_id=OuterRef("_search_point_id"),
    )
    return queryset.filter(free | Q(user=user) | Q(Exists(paid)))


def visible_documents(request, *, result_type="all", bo_table=""):
    from gnu_jango.api.v1_community import _searchable_boards

    boards = _searchable_boards(request)
    if bo_table:
        boards = boards.filter(bo_table=bo_table)
    posts = readable_post_queryset(request, Post.objects.filter(board__in=boards))
    public = Q(post_id__in=posts.values("pk"))
    if not bo_table:
        public |= Q(product_id__in=on_sale_products().values("pk")) | Q(page_id__in=ContentPage.objects.filter(co_use__gt=0).values("pk"))
    docs = SearchDocument.objects.filter(public)
    group = docs_group_id()
    manual = Q(kind="post", post__board__group__gr_id=group) if group else Q(pk__in=[])
    if result_type == "post":
        docs = docs.filter(kind="post").exclude(manual)
    elif result_type == "product":
        docs = docs.filter(kind="product")
    elif result_type == "document":
        docs = docs.filter(Q(kind="page") | manual)
    allowed_body = ~Q(kind="post") | Q(post_id__in=body_readable_posts(request, posts).values("pk"))
    return docs, allowed_body


def matching_documents(docs, query, *, allowed_body, fields=("title", "body")):
    query_terms = terms(query, MAX_QUERY_TERMS)
    if not query_terms:
        return docs.none().annotate(_search_rank=Value(0.0), _body_allowed=Value(False))
    docs = docs.annotate(_body_allowed=Case(When(allowed_body, then=True), default=False, output_field=BooleanField()))
    if connections[docs.db].vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        search = reduce(or_, [SearchQuery(encoded(term), config="simple", search_type="plain") for term in set(query_terms)])
        docs = docs.alias(_title_vector=SearchVector("title_tokens", config="simple"),
                          _body_vector=SearchVector("body_tokens", config="simple"))
        matches = Q(pk__in=[])
        title_rank, body_rank = Value(0.0), Value(0.0)
        if "title" in fields:
            matches |= Q(_title_vector=search)
            title_rank = SearchRank(SearchVector("title_tokens", config="simple"), search)
        if "body" in fields:
            matches |= allowed_body & Q(_body_vector=search)
            body_rank = Case(When(allowed_body, then=SearchRank(SearchVector("body_tokens", config="simple"), search)),
                             default=Value(0.0), output_field=FloatField())
        return docs.filter(matches).annotate(_search_rank=title_rank * 4.0 + body_rank).order_by("-_search_rank", "-pk")

    def frequency(field):
        match = SearchPosting.objects.filter(document_id=OuterRef("pk"), field=field, term__in=set(query_terms))
        return Coalesce(Subquery(match.order_by().values("document_id").annotate(n=Sum("frequency")).values("n")[:1]), 0)

    # IN subqueries start at the term/field B-tree index instead of scanning source bodies.
    title_ids = SearchPosting.objects.filter(field="title", term__in=set(query_terms)).values("document_id")
    body_ids = SearchPosting.objects.filter(field="body", term__in=set(query_terms)).values("document_id")
    matches = Q(pk__in=[])
    title_rank, body_rank = Value(0.0), Value(0.0)
    if "title" in fields:
        matches |= Q(pk__in=title_ids)
        title_rank = frequency("title") * 1.0
    if "body" in fields:
        matches |= allowed_body & Q(pk__in=body_ids)
        body_rank = Case(When(allowed_body, then=frequency("body") * 1.0), default=Value(0.0), output_field=FloatField())
    return docs.filter(matches).annotate(_search_rank=title_rank * 4.0 + body_rank).order_by("-_search_rank", "-pk")


def indexed_queryset(queryset, query, *, kind, fields=("title", "body"), request=None):
    """Return None when a compatibility caller must retain its literal-search fallback."""
    if not getattr(settings, "G5_SEARCH_ENABLED", True) or unready_kinds([kind]):
        return None
    docs = SearchDocument.objects.filter(kind=kind)
    body = Q(pk__gt=0)
    if kind == "post":
        if request is None:
            return None
        body = Q(post_id__in=body_readable_posts(request, queryset).values("pk"))
    hits = matching_documents(docs, query, allowed_body=body, fields=fields)
    return queryset.filter(pk__in=hits.values(f"{kind}_id")).annotate(
        _search_rank=Subquery(hits.filter(**{f"{kind}_id": OuterRef("pk")}).values("_search_rank")[:1]),
    ).order_by("-_search_rank", "-pk")


def popular_terms():
    key = "site-search:popular:v1"
    words = cache.get(key)
    if words is None:
        rows = (SearchKeywordDaily.objects.filter(day__gte=timezone.localdate() - timedelta(days=6), source__in=("site", "shop", "api"))
                .exclude(keyword="").values("keyword").annotate(n=Sum("count")).order_by("-n", "keyword")[:50])
        words = [(row["keyword"], row["n"]) for row in rows]
        cache.set(key, words, 60)
    return words


def ranked_results(request, query, *, result_type="all", bo_table=""):
    from .feedback import click_token, query_hash

    docs, body = visible_documents(request, result_type=result_type, bo_table=bo_table)
    hits = matching_documents(docs, query, allowed_body=body)
    total = hits.count()
    fuzzy = False
    if not total and connections[docs.db].vendor == "postgresql" and getattr(settings, "G5_SEARCH_TRIGRAM", False):
        from django.contrib.postgres.lookups import TrigramSimilar
        from django.contrib.postgres.search import TrigramSimilarity

        hits = docs.filter(TrigramSimilar(Lower("title"), Value(query.lower()))).annotate(
            _search_rank=TrigramSimilarity(Lower("title"), Value(query.lower())),
            _body_allowed=Case(When(body, then=True), default=False, output_field=BooleanField()),
        ).order_by("-_search_rank", "-pk")
        total, fuzzy = hits.count(), True
    candidates = list(hits.select_related("post__board__group", "product", "page")[:CANDIDATE_LIMIT])
    query_terms = terms(query, MAX_QUERY_TERMS)
    scores = bm25_scores([
        doc.title_tokens.split() * 4 + (doc.body_tokens.split() if doc._body_allowed else [])
        for doc in candidates
    ], [encoded(term) for term in query_terms])
    clicks = dict(SearchClickDaily.objects.filter(
        query_hash=query_hash(query), document__in=candidates,
        day__gte=timezone.localdate() - timedelta(days=29),
    ).values("document_id").annotate(n=Sum("count")).values_list("document_id", "n")) if candidates else {}
    popular = [(set(terms(word, MAX_QUERY_TERMS)), count) for word, count in popular_terms()]
    query_set = set(query_terms)
    group = docs_group_id()
    results = []
    for doc, score in zip(candidates, scores):
        if fuzzy:
            score = float(doc._search_rank)
        if score <= 0:
            continue
        title_terms = set(terms(doc.title, 256))
        popularity = sum(count for word, count in popular if word & query_set and word & title_terms)
        multiplier = 1 + min(0.05, log1p(popularity) * 0.005) + min(0.1, log1p(clicks.get(doc.pk, 0)) * 0.02)
        source = getattr(doc, doc.kind)
        _, text = source_text(source, doc.kind)
        snippet = _snippet(text, query_terms) if doc._body_allowed else ""
        if doc.kind == "post":
            result_type_name = "document" if group and source.board.group and source.board.group.gr_id == group else "post"
            url = get_pretty_url(source.board.bo_table, source.legacy_wr_id or source.pk)
            extra = {"bo_table": source.board.bo_table, "bo_subject": source.board.bo_subject}
        elif doc.kind == "product":
            result_type_name, url = "product", f"/shop/products/{quote(str(source.pk), safe='')}"
            extra = {"price": source.it_price}
        else:
            result_type_name, url = "document", f"/content/{quote(str(source.pk), safe='')}"
            extra = {}
        results.append({"type": result_type_name, "id": str(source.pk), "title": doc.title,
                        "url": url, "snippet": snippet, "score": round(score * multiplier, 6),
                        "click_token": click_token(query, doc.pk), **extra})
    results.sort(key=lambda row: (-row["score"], row["type"], row["id"]))
    return results, {"engine": "postgresql-fts" if connections[docs.db].vendor == "postgresql" else "inverted-index",
                     "total": total, "candidate_limit": CANDIDATE_LIMIT, "truncated": total > CANDIDATE_LIMIT,
                     "fuzzy": fuzzy}
