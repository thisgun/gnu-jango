"""재고 소진 예측: when each product runs out and how much to reorder, from its own sales history.

Pure rules, no model. A product's units sold per local day over the last ``window`` finished
days (yesterday backwards) give the demand ``d`` (mean) and its spread ``sigma`` (stdev).
With lead time ``L`` and cover days ``C``:

    safety        = Z_SERVICE * sigma * sqrt(L)
    reorder point = d * L + safety
    days left     = stock / d
    suggested     = max(0, ceil(d * (L + C) + safety - stock))

Sales are counted like 상품판매순위: a line counts unless admin._common.sold_line_q() leaves it
out, on the local day of the order (od_datetime).

The forecast stays at product level, with the stock a buyer can still order: the sum of the
in-use choice options' stock when the product has options (an order takes stock off the option
only), else ``it_stock_qty``. A product that is flagged sold out, or has no stock, is 품절 even when
it sold nothing in the window. Without stock, its demand is taken over the days up to its last sale
(at least ``MIN_DEMAND_DAYS`` from the window start): the sales-free days since are the stockout,
not a lack of demand. A flagged product is one the shop stopped selling, so it gets no reorder
suggestion. Stock still at the 9999 a new product or option starts with was never entered, and one
such option leaves the product orderable without limit, so it gets no days left or suggestion.
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

from .admin._common import sold_line_q
from .models import ShopOrderItem, ShopProduct
from .product_options import DEFAULT_OPTION_STOCK
from .stock_bulk import option_rows

UNTRACKED_STOCK = ShopProduct._meta.get_field("it_stock_qty").default

WINDOWS = (14, 28, 56)
DEFAULT_WINDOW = 28
LEAD_DAYS_RANGE = (1, 60)
DEFAULT_LEAD_DAYS = 7
COVER_DAYS_RANGE = (1, 90)
DEFAULT_COVER_DAYS = 14
# One-sided 95% service level.
Z_SERVICE = 1.65
RECENT_DAYS = 7
MIN_DEMAND_DAYS = 14
MAX_PARAM = 10**6
TREND_UP = 1.3
TREND_DOWN = 0.7

NO_SALES = "판매 없음"
UNTRACKED = "재고 미설정"
TREND_LABELS = {"up": "증가", "down": "감소", "flat": "비슷"}


@dataclass(frozen=True)
class Settings:
    window: int = DEFAULT_WINDOW
    lead_days: int = DEFAULT_LEAD_DAYS
    cover_days: int = DEFAULT_COVER_DAYS


@dataclass(frozen=True)
class StockLevel:
    """What a buyer can still order: ``quantity`` in stock, ``flagged_sold_out`` when the shop
    marked it 품절, ``untracked`` when the quantity is still the default nobody entered."""

    quantity: int
    flagged_sold_out: bool = False
    untracked: bool = False

    @property
    def is_out(self):
        return self.flagged_sold_out or self.quantity <= 0


@dataclass(frozen=True)
class Demand:
    """The numbers a status rule looks at."""

    level: StockLevel
    window_units: int
    days_left: float
    suggested: int
    lead_days: int


@dataclass(frozen=True)
class StatusRule:
    label: str
    badge: str
    rank: int
    applies: Callable[[Demand], bool]


# First matching rule wins. ``rank`` is the order the page lists them in: what needs action first.
STATUS_RULES = (
    StatusRule("품절", "danger", 0, lambda demand: demand.level.is_out),
    StatusRule(UNTRACKED, "neutral", 5, lambda demand: demand.level.untracked),
    StatusRule(NO_SALES, "info", 4, lambda demand: demand.window_units <= 0),
    StatusRule("품절 임박", "danger", 1, lambda demand: demand.days_left <= demand.lead_days),
    StatusRule("발주 필요", "warning", 2, lambda demand: demand.suggested > 0),
    StatusRule("여유", "success", 3, lambda demand: True),
)
_BY_RANK = sorted(STATUS_RULES, key=lambda rule: rule.rank)
STATUS_BADGES = {rule.label: rule.badge for rule in _BY_RANK}
STATUS_ORDER = {rule.label: rule.rank for rule in STATUS_RULES}


@dataclass(frozen=True)
class ProductForecast:
    it_id: str
    name: str
    stock: int | None
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
    window = clamp(params.get("window"), (0, MAX_PARAM), DEFAULT_WINDOW)
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


def _days_until_last_sale(series):
    last_sale = max((day for day, units in enumerate(series, 1) if units), default=0)
    return series[:max(last_sale, MIN_DEMAND_DAYS)]


def forecast_product(it_id, name, level, series, settings):
    """Forecast of one product; ``series`` is its units per day, oldest day first."""
    used = _days_until_last_sale(series) if level.is_out else series
    daily = mean(used) if used else 0.0
    sigma = stdev(used) if len(used) > 1 else 0.0
    safety = Z_SERVICE * sigma * math.sqrt(settings.lead_days)
    sellable = 0 if level.is_out else level.quantity
    need = daily * (settings.lead_days + settings.cover_days) + safety - sellable
    suggested = max(0, math.ceil(need)) if daily else 0
    days_left = sellable / daily if daily else math.inf
    demand = Demand(level, sum(series), days_left, suggested, settings.lead_days)
    status = next(rule.label for rule in STATUS_RULES if rule.applies(demand))
    has_levels = daily > 0 and status != UNTRACKED and not level.flagged_sold_out
    return ProductForecast(
        it_id, name,
        stock=None if level.untracked else level.quantity,
        window_units=demand.window_units,
        daily=daily,
        recent_units=sum(series[-RECENT_DAYS:]),
        days_left=days_left if has_levels else None,
        reorder_point=daily * settings.lead_days + safety if has_levels else None,
        suggested=suggested if has_levels else 0,
        status=status,
        trend=_trend(mean(used[-RECENT_DAYS:]), daily) if daily and not level.is_out else "",
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
        .filter(sold_line_q())
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


def stock_level(product):
    choices = [
        record for io_type, _io_id, record in option_rows(product)
        if io_type == 0 and _int(record.get("io_use"), 1) == 1
    ]
    flagged = product.it_soldout == "1"
    if not choices:
        quantity = product.it_stock_qty or 0
        return StockLevel(quantity, flagged, quantity == UNTRACKED_STOCK)
    quantities = [max(_int(record.get("io_stock_qty"), 0), 0) for record in choices]
    return StockLevel(sum(quantities), flagged, any(q == DEFAULT_OPTION_STOCK for q in quantities))


def _int(value, default):
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def forecast_all(today, settings):
    """Every product on sale, most urgent first."""
    series = sales_series(today, settings.window)
    empty = [0] * settings.window
    products = ShopProduct.objects.filter(it_use="1").only("it_id", "it_name", "it_stock_qty", "it_soldout", "options")
    forecasts = [
        forecast_product(p.it_id, p.it_name, stock_level(p), series.get(p.it_id, empty), settings)
        for p in products
    ]
    return sorted(forecasts, key=urgency_key)


def status_counts(forecasts):
    counts = dict.fromkeys(STATUS_BADGES, 0)
    for forecast in forecasts:
        counts[forecast.status] += 1
    return counts
