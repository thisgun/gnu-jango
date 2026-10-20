from django.db.models import Q


def apply_text_search(queryset, term, fallback_query, *, request=None, fields=None):
    """Use the prepared index; retain literal search before a rebuild or for legacy fields."""
    if not str(term or "").strip():
        return queryset
    from gnu_jango.site_search.service import indexed_queryset

    kind = {"bbs.post": "post", "shop.shopproduct": "product"}.get(queryset.model._meta.label_lower)
    if kind and fields is not False:
        indexed = indexed_queryset(queryset, term, kind=kind, fields=fields or ("title", "body"), request=request)
        if indexed is not None:
            return indexed
    return queryset.filter(fallback_query)


def any_icontains(fields, term):
    query = Q()
    for field_name in fields:
        query |= Q(**{f"{field_name}__icontains": term})
    return query
