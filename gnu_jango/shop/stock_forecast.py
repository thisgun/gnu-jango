"""재고 소진 예측: when each product runs out and how much to reorder, from its own sales history.

Pure rules, no model. A product's units sold per local day over the last ``window`` finished
days (yesterday backwards) give the demand ``d`` (mean) and its spread ``sigma`` (stdev).
With lead time ``L`` and cover days ``C``:

    safety        = Z_SERVICE * sigma * sqrt(L)
    reorder point = d * L + safety
    days left     = stock / d
    suggested     = max(0, ceil(d * (L + C) + safety - stock))

Sales are counted like the other sales reports: a line counts unless its status is in
order_statuses.INACTIVE_LINE_STATUSES, on the local day of the order (od_datetime). The forecast
stays at product level: a cart line names its option only as free text (ct_option), which does not
map reliably onto the option stock records.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, stdev
from typing import Callable

from django.db.models import Sum
from django.db.models.functions import TruncDate

from gnu_jango.utils.date_ranges import local_days

from .models import ShopOrderItem, ShopProduct
from .order_statuses import INACTIVE_LINE_STATUSES

WINDOWS = (14, 28, 56)
DEFAULT_WINDOW = 28
LEAD_DAYS_RANGE = (1, 60)
DEFAULT_LEAD_DAYS = 7
COVER_DAYS_RANGE = (1, 90)
DEFAULT_COVER_DAYS = 14
# One-sided 95% service level.
Z_SERVICE = 1.65
RECENT_DAYS = 7
TREND_UP = 1.3
TREND_DOWN = 0.7

NO_SALES = "판매 없음"
TREND_LABELS = {"up": "증가", "down": "감소", "flat": "비슷"}


@dataclass(frozen=True)
class Settings:
    window: int = DEFAULT_WINDOW
    lead_days: int = DEFAULT_LEAD_DAYS
    cover_days: int = DEFAULT_COVER_DAYS


@dataclass(frozen=True)
class Demand:
    """The numbers a status rule looks at."""

    stock: int
    daily: float
    days_left: float
    reorder_point: float
    lead_days: int


@dataclass(frozen=True)
class StatusRule:
    label: str
    badge: str
    applies: Callable[[Demand], bool]


# First matching rule wins, so the order is the urgency order.
STATUS_RULES = (
    StatusRule("품절", "danger", lambda demand: demand.stock <= 0),
    StatusRule("품절 임박", "danger", lambda demand: demand.days_left <= demand.lead_days),
    StatusRule("발주 필요", "warning", lambda demand: demand.stock <= demand.reorder_point),
    StatusRule("여유", "success", lambda demand: True),
)
NO_SALES_BADGE = "info"
STATUS_BADGES = {rule.label: rule.badge for rule in STATUS_RULES} | {NO_SALES: NO_SALES_BADGE}
STATUS_ORDER = {label: index for index, label in enumerate([*STATUS_BADGES])}


@dataclass(frozen=True)
class ProductForecast:
    it_id: str
    name: str
    stock: int
    window_units: int
    daily: float
    recent_units: int
    days_left: float | None
    reorder_point: float | None
    suggested: int
    status: str
    trend: str

    @property
    def badge(self):
        return STATUS_BADGES[self.status]

    @property
    def trend_label(self):
        return TREND_LABELS.get(self.trend, "")


def clamp(value, bounds, default):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return min(max(number, bounds[0]), bounds[1])


def parse_settings(params):
    """``Settings`` from query parameters; anything missing or out of range falls back or is clamped."""
    window = clamp(params.get("window"), (min(WINDOWS), max(WINDOWS)), DEFAULT_WINDOW)
    return Settings(
        window=window if window in WINDOWS else DEFAULT_WINDOW,
        lead_days=clamp(params.get("lead"), LEAD_DAYS_RANGE, DEFAULT_LEAD_DAYS),
        cover_days=clamp(params.get("cover"), COVER_DAYS_RANGE, DEFAULT_COVER_DAYS),
    )


def _trend(recent_mean, daily):
    ratio = recent_mean / daily
    if ratio >= TREND_UP:
        return "up"
    if ratio <= TREND_DOWN:
        return "down"
    return "flat"


def forecast_product(it_id, name, stock, series, settings):
    """Forecast of one product; ``series`` is its units per day, oldest day first."""
    window_units = sum(series)
    if window_units <= 0:
        return ProductForecast(it_id, name, stock, 0, 0.0, 0, None, None, 0, NO_SALES, "")
    daily = mean(series)
    sigma = stdev(series) if len(series) > 1 else 0.0
    safety = Z_SERVICE * sigma * math.sqrt(settings.lead_days)
    reorder_point = daily * settings.lead_days + safety
    days_left = max(stock, 0) / daily
    demand = Demand(stock, daily, days_left, reorder_point, settings.lead_days)
    status = next(rule.label for rule in STATUS_RULES if rule.applies(demand))
    need = daily * (settings.lead_days + settings.cover_days) + safety - stock
    recent = series[-RECENT_DAYS:]
    return ProductForecast(
        it_id, name, stock, window_units, daily, sum(recent), days_left, reorder_point,
        max(0, math.ceil(need)), status, _trend(mean(recent), daily),
    )


def urgency_key(forecast):
    days_left = forecast.days_left if forecast.days_left is not None else math.inf
    return STATUS_ORDER[forecast.status], days_left, forecast.name


def sales_series(today, window):
    """``{it_id: [units per day, oldest first]}`` for the ``window`` finished days before ``today``."""
    last = today - timedelta(days=1)
    first = last - timedelta(days=window - 1)
    rows = (
        ShopOrderItem.objects.filter(local_days("order__od_datetime", first, last))
        .exclude(ct_status__in=INACTIVE_LINE_STATUSES)
        .annotate(day=TruncDate("order__od_datetime"))
        .values("it_id", "day")
        .annotate(units=Sum("ct_qty"))
    )
    series = defaultdict(lambda: [0] * window)
    for row in rows:
        day = row["day"]
        if isinstance(day, date) and first <= day <= last:
            series[row["it_id"]][(day - first).days] += row["units"] or 0
    return series


def forecast_all(today, settings):
    """Every product on sale, most urgent first."""
    series = sales_series(today, settings.window)
    empty = [0] * settings.window
    products = ShopProduct.objects.filter(it_use="1").values_list("it_id", "it_name", "it_stock_qty")
    forecasts = [
        forecast_product(it_id, name, stock or 0, series.get(it_id, empty), settings)
        for it_id, name, stock in products
    ]
    return sorted(forecasts, key=urgency_key)


def status_counts(forecasts):
    counts = dict.fromkeys(STATUS_BADGES, 0)
    for forecast in forecasts:
        counts[forecast.status] += 1
    return counts
