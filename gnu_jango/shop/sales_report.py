"""매출현황 (youngcart adm/shop_admin/sale1.php, sale1today.php, sale1date.php, sale1month.php,
sale1year.php): order totals per day, month or year, or per order for one day, with the received
amount split by payment method.

youngcart adds od_receipt_price to the column of the order's od_settle_case (무통장, 가상계좌,
계좌이체, 신용카드, 간편결제 family, 휴대폰) and od_receipt_point to 포인트입금. Here a refund is
taken off what the method received (od_receipt_price - od_refund_price, as the settlement report
counts it) and refunds are shown on their own; a payment method youngcart does not list lands in
기타 so no money disappears from the totals.
"""

from datetime import date, timedelta

from django.db.models import Count, F, IntegerField, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncYear

from .models import ShopOrder

PERIOD_TODAY = "today"
PERIOD_DAY = "day"
PERIOD_MONTH = "month"
PERIOD_YEAR = "year"
PERIODS = (
    (PERIOD_TODAY, "일일 (주문별)"),
    (PERIOD_DAY, "일별"),
    (PERIOD_MONTH, "월별"),
    (PERIOD_YEAR, "연도별"),
)
MAX_DAY_SPAN = 400  # a day-by-day table of more than about a year is not readable
MAX_TODAY_ROWS = 1000

# (key, label, settle-case spellings, compared lower-case without spaces, "_" or "-")
METHODS = (
    ("bank", "무통장", ("bank", "무통장", "무통장입금")),
    ("vbank", "가상계좌", ("vbank", "virtualaccount", "가상계좌")),
    ("iche", "계좌이체", ("iche", "transfer", "계좌이체", "실시간계좌이체")),
    ("card", "카드", ("card", "creditcard", "카드", "신용카드")),
    (
        "easy",
        "간편결제",
        (
            "easypay", "간편결제", "kakaopay", "naverpay", "samsungpay", "tosspay", "lpay", "payco",
            "inicis_payco", "inicis_kakaopay", "카카오페이", "네이버페이", "삼성페이", "토스페이", "페이코",
        ),
    ),
    ("hp", "휴대폰", ("hp", "mobilephone", "휴대폰", "휴대폰결제")),
)
OTHER = ("other", "기타")
METHOD_COLUMNS = (*((key, label) for key, label, _names in METHODS), OTHER)


def _normalize(value):
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


_ALIASES = {_normalize(name): key for key, _label, names in METHODS for name in names}


def settle_method(settle_case):
    """The payment-method column of an od_settle_case ("other" for an unknown one; an order
    without a method recorded is a bank-deposit order, the model default)."""
    normalized = _normalize(settle_case)
    if not normalized:
        return "bank"
    return _ALIASES.get(normalized, OTHER[0])


def default_range(period, today):
    if period == PERIOD_TODAY:
        return today, today
    if period == PERIOD_DAY:
        return today.replace(day=1), today
    if period == PERIOD_MONTH:
        return today.replace(month=1, day=1), today
    return date(today.year - 9, 1, 1), today


def clamp_range(period, start, end, today):
    """The (start, end) the report covers: defaults for a missing bound, swapped when reversed,
    and a day-by-day span cut to MAX_DAY_SPAN days (the second value says it was cut)."""
    default_start, default_end = default_range(period, today)
    start = start or default_start
    end = end or default_end
    if period == PERIOD_TODAY:
        end = start
    if start > end:
        start, end = end, start
    cut = False
    if period == PERIOD_DAY and (end - start).days >= MAX_DAY_SPAN:
        start = end - timedelta(days=MAX_DAY_SPAN - 1)
        cut = True
    return start, end, cut


def _empty_row(label):
    return {
        "label": label,
        "order_count": 0,
        "order_price": 0,
        "coupon": 0,
        "methods": {key: 0 for key, _label in METHOD_COLUMNS},
        "point": 0,
        "cancel": 0,
        "refund": 0,
        "misu": 0,
        "receipt": 0,
    }


def _add(row, values, method):
    row["order_count"] += values.get("order_count", 1)
    row["order_price"] += values["order_price"] or 0
    row["coupon"] += values["coupon"] or 0
    net = values["net"] or 0
    row["methods"][method] += net
    row["receipt"] += net
    row["point"] += values["point"] or 0
    row["cancel"] += values["cancel"] or 0
    row["refund"] += values["refund"] or 0
    row["misu"] += values["misu"] or 0


def _amount_expressions():
    return {
        "order_price": Sum(F("od_cart_price") + F("od_send_cost") + F("od_send_cost2"), output_field=IntegerField()),
        "coupon": Sum(F("od_coupon") + F("od_send_coupon"), output_field=IntegerField()),
        "net": Sum(F("od_receipt_price") - F("od_refund_price"), output_field=IntegerField()),
        "point": Sum("od_receipt_point"),
        "cancel": Sum("od_cancel_price"),
        "refund": Sum("od_refund_price"),
        "misu": Sum("od_misu"),
    }


def _with_display(row):
    keys = ("order_count", "order_price", "coupon", "point", "cancel", "refund", "misu", "receipt")
    row["display"] = {key: f"{row[key]:,}" for key in keys}
    row["method_cells"] = [{"key": key, "amount": row["methods"][key], "display": f"{row['methods'][key]:,}"} for key, _label in METHOD_COLUMNS]
    return row


def sales_table(period, start, end, orders=None):
    """{"rows", "total", "columns"} for ``period`` between ``start`` and ``end`` (dates)."""
    orders = ShopOrder.objects.all() if orders is None else orders
    orders = orders.filter(od_datetime__date__gte=start, od_datetime__date__lte=end)
    total = _empty_row("합계")
    if period == PERIOD_TODAY:
        rows = []
        for order in orders.order_by("-od_datetime", "-od_id")[:MAX_TODAY_ROWS].values(
            "od_id", "od_name", "od_settle_case", "od_status", "od_cart_price", "od_send_cost", "od_send_cost2",
            "od_coupon", "od_send_coupon", "od_receipt_price", "od_refund_price", "od_receipt_point",
            "od_cancel_price", "od_misu",
        ):
            values = {
                "order_price": order["od_cart_price"] + order["od_send_cost"] + order["od_send_cost2"],
                "coupon": order["od_coupon"] + order["od_send_coupon"],
                "net": order["od_receipt_price"] - order["od_refund_price"],
                "point": order["od_receipt_point"],
                "cancel": order["od_cancel_price"],
                "refund": order["od_refund_price"],
                "misu": order["od_misu"],
            }
            row = _empty_row(order["od_id"])
            row.update({"od_id": order["od_id"], "name": order["od_name"], "settle_case": order["od_settle_case"], "status": order["od_status"]})
            method = settle_method(order["od_settle_case"])
            _add(row, values, method)
            _add(total, values, method)
            rows.append(_with_display(row))
        return {"rows": rows, "total": _with_display(total), "columns": METHOD_COLUMNS}

    trunc = {PERIOD_DAY: TruncDate, PERIOD_MONTH: TruncMonth, PERIOD_YEAR: TruncYear}[period]("od_datetime")
    fmt = {PERIOD_DAY: "%Y-%m-%d", PERIOD_MONTH: "%Y-%m", PERIOD_YEAR: "%Y"}[period]
    grouped = {}
    for values in (
        orders.annotate(bucket=trunc)
        .values("bucket", "od_settle_case")
        .annotate(order_count=Count("pk"), **_amount_expressions())
        .order_by("bucket")
    ):
        bucket = values["bucket"]
        label = bucket.strftime(fmt) if bucket else "-"
        row = grouped.setdefault(label, _empty_row(label))
        if bucket and "date" not in row:
            row["date"] = bucket.date() if hasattr(bucket, "date") else bucket
        method = settle_method(values["od_settle_case"])
        _add(row, values, method)
        _add(total, values, method)
    rows = [_with_display(row) for _label, row in sorted(grouped.items(), reverse=True)]
    return {"rows": rows, "total": _with_display(total), "columns": METHOD_COLUMNS}
