"""Order form rules from the shop settings: the hoped-for delivery date and the guest privacy notice.

YoungCart orderform.sub.php / orderformupdate.php: when "희망배송일사용" (de_hope_date_use) is on the
customer must pick a delivery date from "희망배송일지정" (de_hope_date_after) days after today for
seven days; when it is off a submitted date is ignored. "비회원 개인정보 수집 안내"
(de_guest_privacy) is the editor HTML a guest reads and agrees to before ordering.
"""

from datetime import date, timedelta

from django.utils import timezone

from gnu_jango.shop.inventory import StockAdjustmentError
from gnu_jango.shop.shop_options import shop_options
from gnu_jango.utils.sanitize import sanitize_html

HOPE_DATE_SPAN_DAYS = 7
HOPE_DATE_ERROR_CODE = "hope_date_invalid"


def hope_date_range(today=None):
    """``{"use", "after", "min", "max"}`` with ``min``/``max`` as YYYY-MM-DD in the server's local date."""
    opts = shop_options("de_hope_date_use", "de_hope_date_after")
    today = today or timezone.localdate()
    after = max(0, int(opts["de_hope_date_after"]))
    return {
        "use": bool(opts["de_hope_date_use"]),
        "after": after,
        "min": (today + timedelta(days=after)).isoformat(),
        "max": (today + timedelta(days=after + HOPE_DATE_SPAN_DAYS - 1)).isoformat(),
    }


def _parse_iso_date(value):
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def order_hope_date(data, today=None):
    """The date to store in ShopOrder.od_hope_date (None when the shop does not use it).

    Raises StockAdjustmentError (HTTP 400) when the shop uses it and the value breaks the rule.
    """
    rule = hope_date_range(today)
    if not rule["use"]:
        return None
    value = str(data.get("od_hope_date") or "").strip()
    if not value:
        raise StockAdjustmentError("희망배송일을 선택하여 주십시오.", code="hope_date_required")
    chosen = _parse_iso_date(value)
    if chosen is None:
        raise StockAdjustmentError("희망배송일이 올바르지 않습니다.", code=HOPE_DATE_ERROR_CODE)
    if not rule["min"] <= chosen.isoformat() <= rule["max"]:
        raise StockAdjustmentError(
            f"희망배송일은 {rule['min']} 부터 {rule['max']} 사이에서 선택해 주십시오.",
            code="hope_date_out_of_range",
            details={"min": rule["min"], "max": rule["max"]},
        )
    return chosen


def guest_privacy_html():
    """The guest privacy notice as sanitized HTML ("" when the administrator left it empty)."""
    raw = str(shop_options("de_guest_privacy")["de_guest_privacy"] or "").strip()
    return sanitize_html(raw).strip() if raw else ""
