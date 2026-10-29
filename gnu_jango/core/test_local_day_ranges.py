"""Local-day filters select a datetime range, so an index on the column can serve them."""
from datetime import date, datetime, timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.db.models.lookups import GreaterThanOrEqual, LessThan
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.sales_anomalies import daily_sales
from gnu_jango.shop.sales_report import PERIOD_DAY, sales_table
from gnu_jango.utils.date_ranges import local_days, period_days

OCTOBER_1 = date(2026, 10, 1)
OCTOBER_2 = date(2026, 10, 2)


def local(*parts):
    return timezone.make_aware(datetime(*parts))


def order_at(od_id, moment, amount=10_000):
    return ShopOrder.objects.create(
        od_id=od_id, od_name="홍길동", od_email="buyer@example.test", od_hp="010-0000-0000",
        od_datetime=moment, od_status="입금", od_settle_case="무통장",
        od_cart_price=amount, od_receipt_price=amount,
    )


def boundary_orders():
    order_at("1", local(2026, 9, 30, 23, 59, 59))  # the day before
    order_at("2", local(2026, 10, 1, 0, 0))  # first moment of the first day
    order_at("3", local(2026, 10, 2, 23, 59, 59, 999999))  # last moment of the last day
    order_at("4", local(2026, 10, 3, 0, 0))  # the day after


def ids(condition):
    return list(ShopOrder.objects.filter(condition).order_by("od_id").values_list("od_id", flat=True))


def test_local_days_include_both_whole_days_and_nothing_else(db):
    boundary_orders()
    assert ids(local_days("od_datetime", OCTOBER_1, OCTOBER_2)) == ["2", "3"]
    assert ids(local_days("od_datetime", start=OCTOBER_2)) == ["3", "4"]
    assert ids(local_days("od_datetime", end=OCTOBER_1)) == ["1", "2"]
    assert ids(local_days("od_datetime")) == ["1", "2", "3", "4"]


def test_local_days_compare_the_column_itself():
    # field__date wraps every row's column in a date conversion, which no index can serve
    where = ShopOrder.objects.filter(local_days("od_datetime", OCTOBER_1, OCTOBER_2)).query.where
    lookups = sorted(where.leaves(), key=lambda lookup: lookup.lookup_name)
    assert [type(lookup) for lookup in lookups] == [GreaterThanOrEqual, LessThan]
    assert all(lookup.lhs.target.name == "od_datetime" for lookup in lookups)
    assert lookups[1].rhs - lookups[0].rhs == timedelta(days=2)


def test_the_extreme_dates_a_form_accepts_do_not_overflow(db):
    # 0001-01-01 00:00 in Seoul is still year 0 in UTC; such a bound selects everything anyway
    boundary_orders()
    assert len(ids(local_days("od_datetime", date.min, date.max))) == 4


@pytest.mark.parametrize(("value", "expected"), [
    ("today", (date(2026, 2, 14), date(2026, 2, 14))),
    ("7d", (date(2026, 2, 8), None)),
    ("month", (date(2026, 2, 1), date(2026, 2, 28))),
    ("year", (date(2026, 1, 1), date(2026, 12, 31))),
    ("bogus", None),
    (None, None),
])
def test_period_days(value, expected):
    assert period_days(value, date(2026, 2, 14)) == expected


def test_december_ends_on_the_last_day_of_the_year():
    assert period_days("month", date(2026, 12, 9)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_the_sales_report_and_the_anomaly_days_count_the_same_orders(db):
    boundary_orders()
    assert sales_table(PERIOD_DAY, OCTOBER_1, OCTOBER_2)["total"]["order_count"] == 2
    days = daily_sales(OCTOBER_1, OCTOBER_2)
    assert sorted(days) == [OCTOBER_1, OCTOBER_2]
    assert sum(day["orders"] for day in days.values()) == 2


@pytest.mark.parametrize("value", ["today", "7d", "month", "year"])
def test_the_admin_date_period_filters_use_the_same_ranges(db, admin_user, value):
    from gnu_jango.core.admin._common import AdminDatePeriodFilter
    from gnu_jango.shop.admin._common import DatePeriodFilter

    LogEntry.objects.create(user=admin_user, action_flag=1, object_repr="x",
                            action_time=timezone.now() - timedelta(days=400))
    LogEntry.objects.create(user=admin_user, action_flag=1, object_repr="y", action_time=timezone.now())
    for base in (AdminDatePeriodFilter, DatePeriodFilter):
        period = type("Period", (base,), {"field_name": "action_time"})
        chosen = period(None, {"date_period": [value]}, LogEntry, None)
        assert list(chosen.queryset(None, LogEntry.objects.all()).values_list("object_repr", flat=True)) == ["y"]
