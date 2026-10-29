"""Permission-aware indexed retrieval shared by the unified and compatibility APIs."""
from datetime import timedelta
from math import log1p
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.models import BigIntegerField, BooleanField, Case, Exists, F, FilteredRelation, FloatField, Func, IntegerField, JSONField, OuterRef, Q, Subquery, Sum, TextField, Value, When
from django.db.models.functions import Coalesce, Concat, JSONObject, Length, Lower, Replace, Substr
from django.utils import timezone

from gnu_jango.api.access import readable_post_queryset
from gnu_jango.ai.client import semantic_search_enabled
from gnu_jango.api.shop_common import on_sale_products
from gnu_jango.bbs.models import Post
from gnu_jango.bbs.utils import get_pretty_url
from gnu_jango.core.models import ContentPage
from gnu_jango.docs_search.ranking import bm25_from_stats, bm25_scores
from gnu_jango.docs_search.service import _snippet, docs_group_id
from gnu_jango.users import point_ledger
from gnu_jango.users.models import User_Point
from gnu_jango.utils.users import is_admin

from .indexing import MAX_TEXT_CHARS, encoded, plain_text, posting_match, postgres_query, prefix_terms, terms, unready_kinds
from .models import SearchClickDaily, SearchDocument, SearchIndexState, SearchPosting, SearchSnapshot, SearchSnapshotPosting
from .vectors import vector_reference

CANDIDATE_LIMIT = 200
MAX_QUERY_TERMS = 24


def body_readable_posts(request, queryset, *, include_readable_secrets=False):
    queryset = readable_post_queryset(request, queryset)
    if not include_readable_secrets:
        queryset = queryset.exclude(wr_option__contains="secret")
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


def _matching_tokens(docs, query, *, allowed_body, fields=("title", "body"), snapshots=False):
    query_terms = terms(query, MAX_QUERY_TERMS)
    if not query_terms:
        return docs.none().annotate(_search_rank=Value(0.0), _body_allowed=Value(False))
    docs = docs.annotate(_body_allowed=Case(When(allowed_body, then=True), default=False, output_field=BooleanField()))
    if connections[docs.db].vendor == "postgresql":
        from django.contrib.postgres.search import SearchRank

        search = postgres_query(query_terms)
        docs = docs.alias(_title_vector=vector_reference("title_vector"),
                          _body_vector=vector_reference("body_vector"))
        # Keep title/body retrieval in separate branches. An OR containing the
        # permission subquery can force PostgreSQL to scan every token row.
        indexed = docs.model.objects.using(docs.db)
        branches = []
        title_rank, body_rank = Value(0.0), Value(0.0)
        if "title" in fields:
            branches.append(indexed.alias(_vector=vector_reference("title_vector")).filter(
                _vector=search).order_by().values("pk"))
            title_rank = SearchRank(vector_reference("title_vector"), search)
        if "body" in fields:
            branches.append(docs.filter(allowed_body, _body_vector=search).order_by().values("pk"))
            body_rank = Case(When(allowed_body, then=SearchRank(vector_reference("body_vector"), search)),
                             default=Value(0.0), output_field=FloatField())
        if not branches:
            return docs.none().annotate(_search_rank=Value(0.0))
        ids = branches[0].union(*branches[1:]) if len(branches) > 1 else branches[0]
        return docs.filter(pk__in=ids).annotate(_search_rank=title_rank * 4.0 + body_rank).order_by("-_search_rank", "-pk")

    def frequency(field):
        model, relation = (SearchSnapshotPosting, "snapshot_id") if snapshots else (SearchPosting, "document_id")
        match = model.objects.filter(posting_match(query_terms), **{relation: OuterRef("pk")}, field=field)
        return Coalesce(Subquery(match.order_by().values(relation).annotate(n=Sum("frequency")).values("n")[:1]), 0)

    # IN subqueries start at the term/field B-tree index instead of scanning source bodies.
    model, relation = (SearchSnapshotPosting, "snapshot_id") if snapshots else (SearchPosting, "document_id")
    title_ids = model.objects.filter(posting_match(query_terms), field="title").values(relation)
    body_ids = model.objects.filter(posting_match(query_terms), field="body").values(relation)
    matches = Q(pk__in=[])
    title_rank, body_rank = Value(0.0), Value(0.0)
    if "title" in fields:
        matches |= Q(pk__in=title_ids)
        title_rank = frequency("title") * 1.0
    if "body" in fields:
        matches |= allowed_body & Q(pk__in=body_ids)
        body_rank = Case(When(allowed_body, then=frequency("body") * 1.0), default=Value(0.0), output_field=FloatField())
    return docs.filter(matches).annotate(_search_rank=title_rank * 4.0 + body_rank).order_by("-_search_rank", "-pk")


def _active_snapshot_documents(docs, query, *, allowed_body, fields):
    """Join the active row once instead of repeating correlated rank subqueries."""
    generations = SearchIndexState.objects.using(docs.db).exclude(active_generation="").values("active_generation")
    docs = docs.alias(_live=FilteredRelation("snapshots", condition=Q(
        snapshots__generation__in=Subquery(generations),
    ))).filter(_live__isnull=False).annotate(
        _body_allowed=Case(When(allowed_body, then=True), default=False, output_field=BooleanField()),
        _search_title_tokens=F("_live__title_tokens"), _search_body_tokens=F("_live__body_tokens"),
    )
    query_terms = terms(query, MAX_QUERY_TERMS)
    if not query_terms:
        return docs.none().annotate(_search_rank=Value(0.0))
    title_rank, body_rank = Value(0.0), Value(0.0)
    if connections[docs.db].vendor == "postgresql":
        from django.contrib.postgres.search import SearchRank
        search = postgres_query(query_terms)
        branches = []
        for field in fields:
            hits = SearchSnapshot.objects.using(docs.db).alias(_vector=vector_reference(f"{field}_vector")).filter(
                _vector=search,
            )
            if field == "body":
                hits = hits.filter(document_id__in=docs.filter(allowed_body).values("pk"))
            branches.append(hits.order_by().values("pk"))
        if not branches:
            return docs.none().annotate(_search_rank=Value(0.0))
        ids = branches[0].union(*branches[1:]) if len(branches) > 1 else branches[0]
        docs = docs.filter(_live__pk__in=ids)
        if "title" in fields:
            title_rank = SearchRank(vector_reference("_live__title_vector"), search)
        if "body" in fields:
            body_rank = Case(When(allowed_body, then=SearchRank(vector_reference("_live__body_vector"), search)),
                             default=Value(0.0), output_field=FloatField())
    else:
        matches = Q(pk__in=[])
        ranks = {}
        for field in fields:
            postings = SearchSnapshotPosting.objects.using(docs.db).filter(posting_match(query_terms), field=field)
            ids = postings.filter(snapshot__generation__in=Subquery(generations)).values("snapshot__document_id")
            matches |= Q(pk__in=ids) & (allowed_body if field == "body" else Q())
            frequency = postings.filter(snapshot_id=OuterRef("_live__pk")).order_by().values("snapshot_id").annotate(n=Sum("frequency"))
            ranks[field] = Coalesce(Subquery(frequency.values("n")[:1]), 0) * 1.0
        docs = docs.filter(matches)
        title_rank = ranks.get("title", title_rank)
        if "body" in ranks:
            body_rank = Case(When(allowed_body, then=ranks["body"]), default=Value(0.0), output_field=FloatField())
    return docs.annotate(_search_rank=title_rank * 4.0 + body_rank).order_by("-_search_rank", "-pk")


def matching_documents(docs, query, *, allowed_body, fields=("title", "body")):
    active_kinds = set(SearchIndexState.objects.using(docs.db).exclude(active_generation="").values_list("kind", flat=True))
    if {"post", "product", "page"} <= active_kinds:
        return _active_snapshot_documents(docs, query, allowed_body=allowed_body, fields=fields)
    # Bootstrap and a partially upgraded index retain the compatibility path.
    active = SearchSnapshot.objects.filter(generation__in=SearchIndexState.objects.exclude(
        active_generation="",
    ).values("active_generation"))
    mode = Exists(SearchIndexState.objects.filter(kind=OuterRef("kind")).exclude(active_generation=""))
    docs = docs.alias(_uses_snapshot=mode)
    legacy = _matching_tokens(docs.filter(_uses_snapshot=False), query, allowed_body=allowed_body, fields=fields)
    snapshots = _matching_tokens(active.filter(document_id__in=docs.values("pk")), query,
        allowed_body=Q(document_id__in=docs.filter(allowed_body).values("pk")), fields=fields, snapshots=True)
    snapshot = active.filter(document_id=OuterRef("pk"))
    return docs.filter(Q(pk__in=legacy.values("pk")) | Q(pk__in=snapshots.values("document_id"))).annotate(
        _body_allowed=Case(When(allowed_body, then=True), default=False, output_field=BooleanField()),
        _search_rank=Case(When(_uses_snapshot=True, then=Subquery(snapshots.filter(
            document_id=OuterRef("pk")).values("_search_rank")[:1])),
            default=Subquery(legacy.filter(pk=OuterRef("pk")).values("_search_rank")[:1]), output_field=FloatField()),
        _search_title_tokens=Case(When(_uses_snapshot=True, then=Subquery(snapshot.values("title_tokens")[:1])),
                                 default=F("title_tokens"), output_field=TextField()),
        _search_body_tokens=Case(When(_uses_snapshot=True, then=Subquery(snapshot.values("body_tokens")[:1])),
                                default=F("body_tokens"), output_field=TextField()),
    ).order_by("-_search_rank", "-pk")


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
    matches = Q(pk__in=hits.values(f"{kind}_id"))
    if kind == "post" and "body" in fields:
        # Secret bodies never enter the shared index. Preserve the legacy
        # author's/unlocked-session literal search through live read permissions.
        secrets = body_readable_posts(request, queryset, include_readable_secrets=True).filter(
            wr_option__contains="secret", wr_content__icontains=query,
        )
        matches |= Q(pk__in=secrets.values("pk"))
    return queryset.filter(matches).annotate(
        _search_rank=Coalesce(Subquery(hits.filter(**{f"{kind}_id": OuterRef("pk")}).values("_search_rank")[:1]),
                              Value(0.0), output_field=FloatField()),
    ).order_by("-_search_rank", "-pk")


def popular_terms():
    key = "site-search:popular:v1"
    words = cache.get(key)
    if words is None:
        from gnu_jango.core.search_privacy import popular_keyword_rows
        words = [(row["keyword"], row["cnt"]) for row in popular_keyword_rows(days=7, limit=50)]
        cache.set(key, words, 60)
    return words


def _postgres_scoring_fields(hits, query_terms):
    # Keep raw token fields as SQL aliases, not SELECT columns. Send only query
    # frequencies and document lengths for the bounded candidate pool to Python.
    hits = hits.alias(_search_title_tokens=F("_search_title_tokens"), _search_body_tokens=F("_search_body_tokens"))
    prefixes = prefix_terms(query_terms)
    stats = {}
    for field in ("title", "body"):
        name = f"_search_{field}_tokens"
        token_text = F(name)
        frequencies = JSONObject(**{
            encoded(term): Func(token_text, Value(r"(?<!\S)" + encoded(term) + ("[0-9a-f]*" if term in prefixes else "") + r"(?!\S)"),
                                function="REGEXP_COUNT", output_field=IntegerField()) for term in sorted(set(query_terms))
        })
        length = Case(When(**{name: "", "then": Value(0)}),
                      default=Length(token_text) - Length(Replace(token_text, Value(" "), Value(""))) + 1,
                      output_field=IntegerField())
        if field == "body":
            frequencies = Case(When(_body_allowed=True, then=frequencies), default=Value({}, output_field=JSONField()))
            length = Case(When(_body_allowed=True, then=length), default=Value(0), output_field=IntegerField())
        stats[f"_search_{field}_stats"] = frequencies
        stats[f"_search_{field}_length"] = length
    return hits.annotate(**stats)


def ranked_results(request, query, *, result_type="all", bo_table="", page=None, limit=20):
    from .feedback import query_hash

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
            _search_title_tokens=F("title_tokens"), _search_body_tokens=F("body_tokens"),
        ).order_by("-_search_rank", "-pk")
        total, fuzzy = hits.count(), True
    query_terms = terms(query, MAX_QUERY_TERMS)
    # REGEXP_COUNT is available from PostgreSQL 15. PostgreSQL 14 keeps the
    # equivalent Python token path while still using stored FTS vectors.
    postgres = connections[docs.db].vendor == "postgresql" and getattr(connections[docs.db], "pg_version", 0) >= 150000
    if postgres:
        hits = _postgres_scoring_fields(hits, query_terms)
    group = docs_group_id()
    candidates = list(hits.annotate(_manual=Case(
        When(post__board__group__gr_id=group, then=True), default=False, output_field=BooleanField(),
    )).only("pk", "kind", "title", "post_id", "product_id", "page_id")[:CANDIDATE_LIMIT])
    encoded_query = [encoded(term) for term in query_terms]
    if postgres:
        title_scores = bm25_from_stats([doc._search_title_stats for doc in candidates], [doc._search_title_length for doc in candidates], encoded_query)
        body_scores = bm25_from_stats([doc._search_body_stats for doc in candidates], [doc._search_body_length for doc in candidates], encoded_query)
    else:
        prefixes = {encoded(term) for term in prefix_terms(query_terms)}
        title_scores = bm25_scores([doc._search_title_tokens.split() for doc in candidates], encoded_query, prefixes=prefixes)
        body_scores = bm25_scores([doc._search_body_tokens.split() if doc._body_allowed else [] for doc in candidates], encoded_query, prefixes=prefixes)
    scores = [title * 4.0 + body for title, body in zip(title_scores, body_scores)]
    clicks = dict(SearchClickDaily.objects.filter(
        query_hash=query_hash(query), document__in=candidates,
        day__gte=timezone.localdate() - timedelta(days=29),
    ).values("document_id").annotate(n=Sum("count")).values_list("document_id", "n")) if candidates else {}
    popular = [(set(terms(word, MAX_QUERY_TERMS)), count) for word, count in popular_terms()]
    query_set = set(query_terms)
    ranked = []
    for doc, score in zip(candidates, scores):
        if fuzzy:
            score = float(doc._search_rank)
        if score <= 0:
            continue
        title_terms = set(terms(doc.title, 256))
        popularity = sum(count for word, count in popular if word & query_set and word & title_terms)
        multiplier = 1 + min(0.05, log1p(popularity) * 0.005) + min(0.1, log1p(clicks.get(doc.pk, 0)) * 0.02)
        kind = "document" if doc.kind == "page" or doc._manual else doc.kind
        ranked.append((doc, round(score * multiplier, 6), kind))
    ranked.sort(key=lambda item: (-item[1], item[2], str(getattr(item[0], f"{item[0].kind}_id"))))
    if semantic_search_enabled():
        # Optional (G5_AI_SEMANTIC_SEARCH): add permitted semantic neighbours by rank fusion.
        from gnu_jango.ai.search import fuse_site_results
        ranked, added = fuse_site_results(query, ranked, docs, body, result_type=result_type, docs_group=group)
        total += added
    meta = {"engine": "postgresql-fts" if connections[docs.db].vendor == "postgresql" else "inverted-index",
            "total": total, "candidate_limit": CANDIDATE_LIMIT, "truncated": total > CANDIDATE_LIMIT, "fuzzy": fuzzy}
    if page is not None:
        pages = max(1, (len(ranked) + limit - 1) // limit)
        page = min(max(page, 1), pages)
        meta.update(current_page=page, per_page=limit, total_pages=pages)
        ranked = ranked[(page - 1) * limit:page * limit]
    return hydrate_results(request, ranked, query, query_terms), meta


def hydrate_results(request, ranked, query, query_terms):
    from .feedback import click_token

    if not ranked:
        return []
    docs, body_allowed = visible_documents(request)
    def joined(prefix, fields):
        parts = []
        for field in fields:
            if parts:
                parts.append(Value(" "))
            parts.append(Substr(Coalesce(F(f"{prefix}__{field}"), Value(""), output_field=TextField()), 1, MAX_TEXT_CHARS))
        return Concat(*parts, output_field=TextField())
    body = Case(
        When(kind="post", then=F("post__wr_content")),
        When(kind="product", then=joined("product", (
            "it_id", "it_basic", "it_content", "it_explan", "it_brand", "it_model", "it_maker"))),
        default=joined("page", ("co_content", "co_mobile_content")), output_field=TextField(),
    )
    rows = docs.filter(pk__in=[doc.pk for doc, _, _ in ranked]).annotate(
        _preview=Case(When(body_allowed, then=Substr(body, 1, MAX_TEXT_CHARS)), default=Value(""), output_field=TextField()),
        _title=Case(When(kind="post", then=F("post__wr_subject")), When(kind="product", then=F("product__it_name")),
                    default=F("page__co_subject"), output_field=TextField()),
    ).values("pk", "_preview", "_title", "post__legacy_wr_id", "post__board__bo_table", "post__board__bo_subject", "product__it_price")
    details = {row["pk"]: row for row in rows}
    results = []
    for doc, score, result_type_name in ranked:
        row = details.get(doc.pk)
        if row is None:
            continue
        source_id = getattr(doc, f"{doc.kind}_id")
        if doc.kind == "post":
            url = get_pretty_url(row["post__board__bo_table"], row["post__legacy_wr_id"] or source_id)
            extra = {"bo_table": row["post__board__bo_table"], "bo_subject": row["post__board__bo_subject"]}
        elif doc.kind == "product":
            url, extra = f"/shop/products/{quote(str(source_id), safe='')}", {"price": row["product__it_price"]}
        else:
            url, extra = f"/content/{quote(str(source_id), safe='')}", {}
        results.append({"type": result_type_name, "id": str(source_id), "title": row["_title"],
                        "url": url, "snippet": _snippet(plain_text(row["_preview"]), query_terms), "score": score,
                        "click_token": click_token(query, doc.pk), **extra})
    return results
