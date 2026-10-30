"""매출 이상 징후: one month's sales so far compared with the three months before, by fixed rules.

Every finding comes from the order table and the rules below; nothing here calls a model. The
optional AI briefing (gnu_jango.ai.sales_insights) only puts these findings into words.

Counting follows the 매출현황 report (sales_report): an order belongs to the local day of
od_datetime, the received amount is od_receipt_price - od_refund_price, and the payment method
comes from od_settle_case. An order in a cancelled/returned/sold-out status counts as a cancel,
not as an order.
"""

from datetime import date, timedelta
from statistics import median

from django.db.models import Count, F, IntegerField, Q, Sum
from django.db.models.functions import TruncDate

from gnu_jango.utils.date_ranges import local_days

from .models import ShopOrder
from .order_statuses import INACTIVE_LINE_STATUSES
from .sales_report import METHOD_COLUMNS, settle_method

BASELINE_MONTHS = 3
# Fewer orders than this in the baseline months: too little history to call anything unusual.
MIN_BASELINE_ORDERS = 10
# Pace and refunds need this many finished days in the month; one or two days are mostly noise.
MIN_COMPLETE_DAYS = 3
# Month-to-date receipts this far from the baseline pace (fraction).
PACE_CHANGE = 0.3
PACE_HIGH = 0.5
# A day whose receipts sit this many robust standard deviations above the baseline days.
SPIKE_Z = 3.5
# "No orders today" only matters where the baseline median is at least this many orders a day.
QUIET_DAY_MIN_MEDIAN = 3
MAX_DAY_FINDINGS = 5
CANCEL_RATE_POINTS = 0.10
CANCEL_RATE_HIGH_POINTS = 0.20
MIN_CANCELS = 5
REFUND_RATIO = 2.0
MIN_REFUND = 50_000
# A payment method with this share of the baseline orders that has had none for this many days.
METHOD_SILENT_DAYS = 7
METHOD_MIN_SHARE = 0.10
METHOD_MIN_ORDERS = 5
METHOD_WINDOW_MIN_ORDERS = 3
AOV_CHANGE = 0.3
MIN_AOV_ORDERS = 10

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
SEVERITY_LABELS = {"high": "주의", "medium": "확인", "info": "참고"}
METHOD_LABELS = dict(METHOD_COLUMNS)


def month_start(value):
    return value.replace(day=1)


def _shift_months(first_day, months):
    month_index = first_day.year * 12 + first_day.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _empty_day():
    return {"orders": 0, "cancels": 0, "receipt": 0, "refund": 0, "methods": {}}


def daily_sales(start, end):
    """``{date: {"orders", "cancels", "receipt", "refund", "methods": {method: orders}}}``."""
    cancelled = Q(od_status__in=INACTIVE_LINE_STATUSES)
    rows = (
        ShopOrder.objects.filter(local_days("od_datetime", start, end))
        .annotate(day=TruncDate("od_datetime"))
        .values("day", "od_settle_case")
        .annotate(
            orders=Count("pk", filter=~cancelled),
            cancels=Count("pk", filter=cancelled),
            receipt=Sum(F("od_receipt_price") - F("od_refund_price"), output_field=IntegerField()),
            refund=Sum("od_refund_price"),
        )
    )
    days = {}
    for row in rows:
        day = days.setdefault(row["day"], _empty_day())
        day["orders"] += row["orders"]
        day["cancels"] += row["cancels"]
        day["receipt"] += row["receipt"] or 0
        day["refund"] += row["refund"] or 0
        method = settle_method(row["od_settle_case"])
        day["methods"][method] = day["methods"].get(method, 0) + row["orders"]
    return days


def _totals(days, start, end):
    total = _empty_day()
    for day, values in days.items():
        if start <= day <= end:
            for key in ("orders", "cancels", "receipt", "refund"):
                total[key] += values[key]
            for method, count in values["methods"].items():
                total["methods"][method] = total["methods"].get(method, 0) + count
    return total


def _span(start, end):
    return (end - start).days + 1


def _percent(fraction):
    return round(fraction * 100)


def _finding(key, severity, title, detail, **numbers):
    return {"key": key, "severity": severity, "severity_label": SEVERITY_LABELS[severity], "title": title,
            "detail": detail, "numbers": numbers}


def _pace(current, baseline, elapsed, baseline_days):
    expected = round(baseline["receipt"] / baseline_days * elapsed)
    if expected <= 0:
        return []
    change = (current["receipt"] - expected) / expected
    if abs(change) < PACE_CHANGE:
        return []
    if change >= 2:
        # "444490% 많습니다" reads worse than a ratio
        title = f"입금액이 평소의 약 {round(current['receipt'] / expected):,}배입니다"
    else:
        title = f"입금액이 평소보다 {abs(_percent(change))}% {'많습니다' if change > 0 else '적습니다'}"
    return [_finding(
        "pace", "high" if abs(change) >= PACE_HIGH else "medium",
        title,
        f"{elapsed}일 동안 입금 {current['receipt']:,}원, 직전 {BASELINE_MONTHS}개월의 같은 일수 평균 {expected:,}원",
        receipt=current["receipt"], expected=expected, change_percent=_percent(change), days=elapsed,
    )]


def _robust_scale(values, center):
    deviations = [abs(value - center) for value in values]
    scale = 1.4826 * median(deviations)
    if scale <= 0:
        # Mostly-equal days (e.g. many days without orders): fall back to the mean deviation.
        scale = sum(deviations) / len(deviations)
    return scale


def _days(current_days, baseline_days, start, end, base_start, base_end, today):
    base_dates = [base_start + timedelta(days=offset) for offset in range(_span(base_start, base_end))]
    receipts = [baseline_days.get(day, _empty_day())["receipt"] for day in base_dates]
    orders = [baseline_days.get(day, _empty_day())["orders"] for day in base_dates]
    center, order_center, busiest = median(receipts), median(orders), max(receipts)
    scale = _robust_scale(receipts, center)
    findings = []
    for offset in range(_span(start, end)):
        day = start + timedelta(days=offset)
        values = current_days.get(day, _empty_day())
        # In a quiet shop most baseline days are 0 won, so every sale is far above the median;
        # a spike must also beat the busiest baseline day.
        if values["receipt"] > busiest:
            # A perfectly flat baseline has no spread to measure against: twice its level is a spike.
            if scale > 0:
                z = (values["receipt"] - center) / scale
            else:
                z = SPIKE_Z * values["receipt"] / (2 * max(busiest, 1))
            if z >= SPIKE_Z:
                findings.append((z, _finding(
                    "day_spike", "medium", f"{day.isoformat()} 입금액 급증",
                    f"입금 {values['receipt']:,}원, 직전 {BASELINE_MONTHS}개월 중 가장 많았던 날 {busiest:,}원",
                    date=day.isoformat(), receipt=values["receipt"], baseline_busiest=busiest,
                )))
        # today is not over yet, so an empty today proves nothing
        if day < today and order_center >= QUIET_DAY_MIN_MEDIAN and values["orders"] == 0:
            findings.append((float("inf"), _finding(
                "quiet_day", "high", f"{day.isoformat()} 주문 없음",
                f"평소 하루 주문 중앙값은 {round(order_center)}건입니다",
                date=day.isoformat(), median_orders=round(order_center),
            )))
    findings.sort(key=lambda item: -item[0])
    return [finding for _z, finding in findings[:MAX_DAY_FINDINGS]]


def _cancel_rate(current, baseline):
    current_all = current["orders"] + current["cancels"]
    baseline_all = baseline["orders"] + baseline["cancels"]
    if current["cancels"] < MIN_CANCELS or not current_all or not baseline_all:
        return []
    rate, base_rate = current["cancels"] / current_all, baseline["cancels"] / baseline_all
    points = rate - base_rate
    if points < CANCEL_RATE_POINTS:
        return []
    return [_finding(
        "cancel_rate", "high" if points >= CANCEL_RATE_HIGH_POINTS else "medium",
        f"취소율이 {_percent(base_rate)}%에서 {_percent(rate)}%로 올랐습니다",
        f"주문 {current_all:,}건 중 취소 {current['cancels']:,}건",
        cancel_percent=_percent(rate), baseline_cancel_percent=_percent(base_rate), cancels=current["cancels"],
        orders=current_all,
    )]


def _refunds(current, baseline, elapsed, baseline_days):
    expected = round(baseline["refund"] / baseline_days * elapsed)
    if current["refund"] < MIN_REFUND or current["refund"] < REFUND_RATIO * max(expected, 1):
        return []
    return [_finding(
        "refund", "medium", "환불이 평소보다 많습니다",
        f"환불 {current['refund']:,}원, 직전 {BASELINE_MONTHS}개월의 같은 일수 평균 {expected:,}원",
        refund=current["refund"], expected=expected,
    )]


def _silent_methods(current_days, baseline, start, end):
    if _span(start, end) < METHOD_SILENT_DAYS or not baseline["orders"]:
        return []
    window_start = end - timedelta(days=METHOD_SILENT_DAYS - 1)
    window = _totals(current_days, window_start, end)
    if window["orders"] < METHOD_WINDOW_MIN_ORDERS:
        return []
    findings = []
    for method, count in sorted(baseline["methods"].items()):
        share = count / baseline["orders"]
        if count >= METHOD_MIN_ORDERS and share >= METHOD_MIN_SHARE and not window["methods"].get(method):
            label = METHOD_LABELS.get(method, method)
            findings.append(_finding(
                "method_silent", "high", f"{label} 주문이 {METHOD_SILENT_DAYS}일째 없습니다",
                f"평소 주문의 {_percent(share)}%가 {label}인데 최근 {METHOD_SILENT_DAYS}일 주문 "
                f"{window['orders']:,}건 중 0건입니다. 결제대행사 연동 상태를 확인해 보세요",
                method=label, baseline_share_percent=_percent(share), days=METHOD_SILENT_DAYS,
                recent_orders=window["orders"],
            ))
    return findings


def _average_order(current, baseline):
    if current["orders"] < MIN_AOV_ORDERS or baseline["orders"] < MIN_AOV_ORDERS:
        return []
    value, base_value = round(current["receipt"] / current["orders"]), round(baseline["receipt"] / baseline["orders"])
    if base_value <= 0:
        return []
    change = (value - base_value) / base_value
    if abs(change) < AOV_CHANGE:
        return []
    return [_finding(
        "average_order", "medium", f"객단가가 평소보다 {abs(_percent(change))}% {'높습니다' if change > 0 else '낮습니다'}",
        f"주문당 입금 {value:,}원, 직전 {BASELINE_MONTHS}개월 {base_value:,}원",
        average=value, baseline_average=base_value, change_percent=_percent(change),
    )]


def month_report(month, today):
    """The findings for ``month`` (any date in it) up to ``today``, most serious first.

    Returns {"month", "start", "end", "elapsed_days", "baseline_start", "baseline_end", "current",
    "baseline", "findings", "enough_history"}; amounts are won, counts are orders.
    """
    start = month_start(month)
    end = min(_shift_months(start, 1) - timedelta(days=1), today)
    base_start, base_end = _shift_months(start, -BASELINE_MONTHS), start - timedelta(days=1)
    report = {"month": start.strftime("%Y-%m"), "start": start, "end": end, "baseline_start": base_start,
              "baseline_end": base_end, "baseline_months": BASELINE_MONTHS, "findings": []}
    if end < start:
        report.update(elapsed_days=0, current=_empty_day(), baseline=_empty_day(), enough_history=False)
        return report
    current_days, baseline_days = daily_sales(start, end), daily_sales(base_start, base_end)
    current, baseline = _totals(current_days, start, end), _totals(baseline_days, base_start, base_end)
    elapsed, base_span = _span(start, end), _span(base_start, base_end)
    # Amounts are compared over finished days only: today's receipts are still coming in, so on
    # the 1st a whole-day expectation against a few hours of sales would always read as a slump.
    complete_end = end - timedelta(days=1) if end >= today else end
    complete_days = _span(start, complete_end) if complete_end >= start else 0
    complete = _totals(current_days, start, complete_end)
    enough = baseline["orders"] + baseline["cancels"] >= MIN_BASELINE_ORDERS
    report.update(elapsed_days=elapsed, current=current, baseline=baseline, enough_history=enough)
    if not enough:
        report["findings"].append(_finding(
            "history", "info", "비교할 과거 주문이 적습니다",
            f"직전 {BASELINE_MONTHS}개월 주문이 {baseline['orders'] + baseline['cancels']:,}건이라 "
            f"평소와 비교하지 않았습니다 (기준 {MIN_BASELINE_ORDERS}건)",
            baseline_orders=baseline["orders"] + baseline["cancels"], minimum=MIN_BASELINE_ORDERS,
        ))
        return report
    findings = [
        *_silent_methods(current_days, baseline, start, end),
        *(_pace(complete, baseline, complete_days, base_span) if complete_days >= MIN_COMPLETE_DAYS else []),
        *_cancel_rate(current, baseline),
        *(_refunds(complete, baseline, complete_days, base_span) if complete_days >= MIN_COMPLETE_DAYS else []),
        *_average_order(current, baseline),
        *_days(current_days, baseline_days, start, end, base_start, base_end, today),
    ]
    findings.sort(key=lambda finding: SEVERITY_ORDER[finding["severity"]])
    if not findings:
        findings.append(_finding("normal", "info", "평소와 다른 점을 찾지 못했습니다",
                                 f"입금 {current['receipt']:,}원, 주문 {current['orders']:,}건"))
    report["findings"] = findings
    return report
