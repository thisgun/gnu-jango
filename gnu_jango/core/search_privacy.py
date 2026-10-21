"""Conservative rules for search analytics and explicitly curated public terms."""
import re

from django.conf import settings

_SENSITIVE = re.compile(
    r"[@:/\\]|[\x00-\x1f\x7f]|(?:\d[\s().-]*){6,}|"
    r"(?:비밀번호|패스워드|주민등록|계좌번호|카드번호|password|secret|token)", re.IGNORECASE,
)


def analytics_keyword(value):
    if _SENSITIVE.search(str(value or "")):
        return ""
    value = " ".join(str(value or "").split())
    if not 2 <= len(value) <= 200 or _SENSITIVE.search(value):
        return ""
    if not any(character.isalnum() for character in value):
        return ""
    return value


def public_keywords():
    # A frequency threshold alone cannot make an arbitrary personal question safe.
    values = getattr(settings, "G5_SEARCH_PUBLIC_KEYWORDS", ())
    if isinstance(values, str):
        values = values.split(",")
    return sorted({word for value in values if (word := analytics_keyword(value))})[:200]


def popular_keyword_rows(*, days, limit):
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from .models import SearchKeywordDaily

    approved = public_keywords()
    if not approved:
        return []
    return list(SearchKeywordDaily.objects.filter(
        day__gte=timezone.localdate() - timedelta(days=days - 1),
        source__in=("site", "shop", "api"), keyword__in=approved,
    ).values("keyword").annotate(cnt=Sum("count")).filter(
        cnt__gte=max(1, getattr(settings, "G5_SEARCH_PUBLIC_MIN_COUNT", 5)),
    ).order_by("-cnt", "keyword")[:limit])
