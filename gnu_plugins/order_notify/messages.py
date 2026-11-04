"""The text of an order message: what happened, the order number, the amount, the buyer and a link
to the order in the admin. Plain text, the same for every channel (channels escapes it per service)."""

import re

from django.urls import NoReverseMatch, reverse

from gnu_jango.shop.notifications import order_totals, site_link

# Discord takes up to 2000 characters; the other services more.
MAX_TEXT_LENGTH = 1800
MAX_ITEM_NAME_LENGTH = 40
MAX_NAME_LENGTH = 30
# The buyer's name is typed by the customer: no line breaks (a forged second message line) and none
# of the characters Discord or Slack read as markup or links.
_BREAKS = re.compile(r"[\s\x00-\x1f\x7f  ]+")
_MARKUP = re.compile(r"[\[\]()<>`*_~|#@\\]")

TITLES = {
    "placed": "🛒 새 주문",
    "paid": "💳 결제 완료",
    "cancelled": "↩️ 취소·반품",
    "status": "📦 주문 상태 변경",
}
TEST_TEXT = "🔔 주문 알림 테스트\n이 채널로 새 주문, 결제 완료, 취소·반품 알림이 옵니다."


def plain(text, limit):
    """``text`` on one line, without markup characters, at most ``limit`` characters."""
    return _MARKUP.sub("", _BREAKS.sub(" ", str(text or ""))).strip()[:limit]


def mask_name(name):
    """홍길동 -> 홍*동, 김철 -> 김*, a single character -> *: the buyer stays recognisable to staff."""
    name = plain(name, MAX_NAME_LENGTH)
    if len(name) <= 1:
        return "*" if name else ""
    if len(name) == 2:
        return f"{name[0]}*"
    return f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"


def _items(order):
    names = list(order.items.order_by("ct_id").values_list("it_name", flat=True)[:2])
    if not names:
        return ""
    first = plain(names[0], MAX_ITEM_NAME_LENGTH)
    count = order.items.count()
    return f"{first} 외 {count - 1}건" if count > 1 else first


def _admin_link(order):
    try:
        return site_link(reverse("admin:shop_shoporder_change", args=[order.pk]))
    except NoReverseMatch:
        return ""


def build(order, event, *, old_status="", new_status="", full_name=False):
    total = order_totals(order)["total"]
    buyer = plain(order.od_name, MAX_NAME_LENGTH) if full_name else mask_name(order.od_name)
    details = [f"{total:,}원", plain(order.od_settle_case, MAX_NAME_LENGTH), buyer]
    lines = [f"{TITLES[event]} · {order.od_id}", " · ".join(part for part in details if part)]
    if event in ("cancelled", "status") and new_status:
        lines.append(f"{old_status or '-'} → {new_status}")
    items = _items(order)
    if items:
        lines.append(items)
    link = _admin_link(order)
    if link:
        lines.append(link)
    return "\n".join(lines)[:MAX_TEXT_LENGTH]
