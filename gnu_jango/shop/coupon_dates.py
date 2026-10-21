"""Coupon validity dates."""
from datetime import date, timedelta

# YoungCart computes the end with PHP strtotime, so an absurd imported period (cz_period
# 2147483647 for "no limit") still gives a date; Python's date stops at 9999-12-31.
LAST_COUPON_DAY = date.max


def coupon_end_date(start, days):
    """The last valid day of a coupon valid for ``days`` days from ``start`` (start included).

    A period of 0 or less ends on ``start`` (ajax.coupondownload.php: ``$period < 0 → 0``);
    one past the calendar's end is capped at 9999-12-31 instead of overflowing.
    """
    try:
        span = max(0, int(days or 0) - 1)
    except (TypeError, ValueError):
        span = 0
    if span > (LAST_COUPON_DAY - start).days:
        return LAST_COUPON_DAY
    return start + timedelta(days=span)
