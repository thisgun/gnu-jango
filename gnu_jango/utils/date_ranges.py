"""Local-day filters on datetime columns, written as ranges an index on the column can serve.

``field__date__gte=day`` selects the same rows, but wraps every row's column in a date conversion,
so the database scans the whole table (on SQLite 118 ms against 1 ms for 5,000 orders).
"""
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def day_start(day):
    """The first moment of the local day ``day`` (aware when USE_TZ is on)."""
    moment = datetime.combine(day, time.min)
    return timezone.make_aware(moment) if settings.USE_TZ else moment


def local_days(field, start=None, end=None):
    """``Q`` for ``field`` on the local days ``start`` to ``end``, both inclusive; either may be None.

    The first and last dates a form accepts are left unbounded: they select everything anyway, and
    0001-01-01 00:00 east of UTC is year 0 in UTC, which the database adapter cannot store.
    """
    condition = Q()
    if start is not None and start > date.min:
        condition &= Q(**{f"{field}__gte": day_start(start)})
    if end is not None and end < date.max:
        condition &= Q(**{f"{field}__lt": day_start(end + timedelta(days=1))})
    return condition


def period_days(value, today):
    """``(start, end)`` of an admin date-period choice ("today", "7d", "month", "year"); else None."""
    if value == "today":
        return today, today
    if value == "7d":
        return today - timedelta(days=6), None
    if value == "month":
        first = today.replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if value == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return None
