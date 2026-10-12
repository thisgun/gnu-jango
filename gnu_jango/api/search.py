from django.db.models import Q


def apply_text_search(queryset, term, fallback_query):
    """Keep Gnuboard's literal, case-insensitive substring search on every database."""
    if not str(term or "").strip():
        return queryset
    return queryset.filter(fallback_query)


def any_icontains(fields, term):
    query = Q()
    for field_name in fields:
        query |= Q(**{f"{field_name}__icontains": term})
    return query
