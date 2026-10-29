"""Shop product search fields (YoungCart shop/search.php qname / qexplan / qid / qbasic)."""
from django.db.models import Q

from gnu_jango.ai.client import semantic_search_enabled

from .search import apply_text_search

# selector -> product column; search.php searches it_explan2, the tag-free copy of it_explan
PRODUCT_SEARCH_FIELDS = (
    ("qname", "it_name"),
    ("qexplan", "it_explan"),
    ("qid", "it_id"),
    ("qbasic", "it_basic"),
)
_TRUE = {"1", "on", "true", "y", "yes"}


def selected_product_search_fields(params):
    """The columns the shopper ticked; none ticked means all of them (search.php ``$search_all``)."""
    chosen = [field for key, field in PRODUCT_SEARCH_FIELDS if str(params.get(key) or "").strip().lower() in _TRUE]
    return chosen or [field for _key, field in PRODUCT_SEARCH_FIELDS]


def literal_product_search_q(term, fields):
    """search.php: every space-separated word must appear in one of the chosen columns."""
    query = Q()
    for word in str(term or "").split():
        word_query = Q()
        for field in fields:
            word_query |= Q(**{f"{field}__icontains": word})
        query &= word_query
    return query


def search_products(queryset, term, params):
    fields = selected_product_search_fields(params)
    fallback = literal_product_search_q(term, fields)
    every_field = len(fields) == len(PRODUCT_SEARCH_FIELDS)
    if every_field:
        # the prepared index covers the name (title) and the other columns (body)
        lexical = apply_text_search(queryset, term, fallback)
        if not semantic_search_enabled():
            return lexical
        # Optional (G5_AI_SEMANTIC_SEARCH): add on-sale products found by meaning, not words.
        from gnu_jango.ai.search import fuse_product_queryset
        return fuse_product_queryset(queryset, lexical, term)
    if fields == ["it_name"]:
        return apply_text_search(queryset, term, fallback, fields=("title",))
    # the index body mixes code, summary and description, so a narrower choice reads the columns
    return apply_text_search(queryset, term, fallback, fields=False)
