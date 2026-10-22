from django.db.models import Q


def post_body_match(request, term, queryset=None):
    """Use the same body permissions for literal, indexed and mixed-field search."""
    from gnu_jango.bbs.models import Post
    from gnu_jango.site_search.service import body_readable_posts

    if request is None:
        return Q(pk__in=[])
    readable = body_readable_posts(request, queryset if queryset is not None else Post.objects.all(), include_readable_secrets=True)
    return Q(wr_content__icontains=term) & Q(pk__in=readable.values("pk"))


def apply_text_search(queryset, term, fallback_query, *, request=None, fields=None):
    """Use the prepared index; retain literal search before a rebuild or for legacy fields."""
    if not str(term or "").strip():
        return queryset
    from gnu_jango.site_search.service import indexed_queryset
    from gnu_jango.site_search.indexing import terms

    kind = {"bbs.post": "post", "shop.shopproduct": "product"}.get(queryset.model._meta.label_lower)
    # Legacy callers promise substring matches, including a single Hangul letter
    # and partial ASCII product codes. Keep those on their permission-safe literal
    # path; the unified API supports indexed ASCII prefixes separately.
    literal = str(term).isascii() or not terms(term, 24)
    if kind and fields is not False and not literal:
        indexed = indexed_queryset(queryset, term, kind=kind, fields=fields or ("title", "body"), request=request)
        if indexed is not None:
            return indexed
    return queryset.filter(fallback_query)


def any_icontains(fields, term):
    query = Q()
    for field_name in fields:
        query |= Q(**{f"{field_name}__icontains": term})
    return query
