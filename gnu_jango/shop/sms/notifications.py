"""Shop texts, after youngcart: shop/orderformupdate.php (주문시 고객님께 / 관리자에게, and the bank
account for a 무통장 order), adm/shop_admin/orderlistupdate.php + conv_sms_contents (입금확인시 /
상품배송시) and the 회원가입시 slot of the shop settings.

Every text obeys cf_sms_use (SMS 사용 = 아이코드) and its de_sms_use<n> switch. Texts are queued with
transaction.on_commit so they leave only once the order or the status change is saved, and a
failure is logged (and noted in the order's admin memo), never raised.
"""

import logging

from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Concat
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder

from .service import mask_phone, render_template, send_message, sms_settings, status_label

logger = logging.getLogger(__name__)

SLOT_MEMBER_JOIN = 1
SLOT_ORDER_CUSTOMER = 2
SLOT_ORDER_ADMIN = 3
SLOT_PAID = 4
SLOT_SHIPPING = 5
STATUS_PAID = "입금"
STATUS_SHIPPING = "배송"
STATUS_SLOTS = {STATUS_PAID: SLOT_PAID, STATUS_SHIPPING: SLOT_SHIPPING}
STATUS_TITLES = {STATUS_PAID: "입금확인", STATUS_SHIPPING: "배송안내"}


def order_variables(order, current):
    """The youngcart replacement variables of an order text."""
    total = int(order.od_cart_price or 0) + int(order.od_send_cost or 0) + int(order.od_send_cost2 or 0)
    return {
        "이름": order.od_name,
        "보낸분": order.od_name,
        "받는분": order.od_b_name,
        "주문번호": order.od_id,
        "주문금액": f"{total:,}",
        "회원아이디": order.user.get_username() if order.user_id and order.user else "",
        "회사명": current.company_name,
        "입금액": f"{int(order.od_receipt_price or 0):,}",
        "택배회사": order.od_delivery_company,
        "운송장번호": order.od_invoice,
    }


def _bank_account_text(order, current):
    """orderformupdate.php: a 무통장 order also gets the account to pay into."""
    from gnu_jango.api.shop_payments import settle_case_is_bank

    owed = int(order.od_misu or 0)
    if not settle_case_is_bank(order.od_settle_case) or owed <= 0 or not order.od_bank_account:
        return ""
    return f"{order.od_name}님의 입금계좌입니다.\n금액:{owed:,}원\n계좌:{order.od_bank_account}\n{current.company_name}"


def _note_on_order(order, title, outcomes):
    """Keep a line in the admin memo, like the order mails do (no phone number in it)."""
    if not outcomes:
        return
    summary = ", ".join(f"{label} {mask_phone(phone)} {status_label(result)}" for label, phone, result in outcomes)
    note = f"{timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')} - SMS {title}: {summary}\n"
    ShopOrder.objects.filter(pk=order.pk).update(od_shop_memo=Concat(Value(note), "od_shop_memo"))


def _send_all(order, title, messages, current, *, background_parent=""):
    outcomes = []
    for label, phone, text in messages:
        result = send_message(phone, text, current=current, purpose=f"{title} {order.od_id} {label}", background_parent=background_parent)
        outcomes.append((label, phone, result))
    _note_on_order(order, title, outcomes)
    return outcomes


def send_order_placed_sms(order_id, *, background_parent=""):
    """주문시 고객님께 발송 (slot 2), 주문시 관리자에게 발송 (slot 3) and the bank account text."""
    current = sms_settings()
    if not current.enabled:
        return []
    order = ShopOrder.objects.filter(pk=order_id).select_related("user").first()
    if order is None:
        return []
    variables = order_variables(order, current)
    customer_on, customer_text = current.slot(SLOT_ORDER_CUSTOMER)
    admin_on, admin_text = current.slot(SLOT_ORDER_ADMIN)
    messages = []
    if customer_on and order.od_hp:
        messages.append(("고객", order.od_hp, render_template(customer_text, variables)))
    if admin_on and current.admin_hp:
        messages.append(("관리자", current.admin_hp, render_template(admin_text, variables)))
    account_text = _bank_account_text(order, current) if customer_on and order.od_hp else ""
    if account_text:
        messages.append(("입금계좌", order.od_hp, account_text))
    return _send_all(order, "주문안내", messages, current, background_parent=background_parent)


def send_order_status_sms(order_id, status, *, background_parent=""):
    """입금확인시 (slot 4) / 상품배송시 (slot 5) 고객님께 발송, with conv_sms_contents' variables."""
    slot = STATUS_SLOTS.get(status)
    current = sms_settings()
    if slot is None or not current.enabled:
        return []
    enabled, template = current.slot(slot)
    if not enabled:
        return []
    order = ShopOrder.objects.filter(pk=order_id).select_related("user").first()
    if order is None or not order.od_hp:
        return []
    text = render_template(template, order_variables(order, current))
    return _send_all(order, STATUS_TITLES[status], [("고객", order.od_hp, text)], current, background_parent=background_parent)


def send_member_join_sms(user_id, *, background_parent=""):
    """회원가입시 고객님께 발송 (slot 1) to the member's mobile number, when the member left one."""
    from django.contrib.auth import get_user_model

    current = sms_settings()
    enabled, template = current.slot(SLOT_MEMBER_JOIN)
    if not current.enabled or not enabled:
        return None
    user = get_user_model().objects.filter(pk=user_id).select_related("profile").first()
    profile = getattr(user, "profile", None) if user else None
    phone = str(getattr(profile, "user_hp", "") or "").strip()
    if not phone:
        return None
    name = getattr(profile, "realname", "") or getattr(profile, "nickname", "") or user.get_username()
    text = render_template(template, {"이름": name, "회원아이디": user.get_username(), "회사명": current.company_name})
    return send_message(phone, text, current=current, purpose=f"회원가입 {user.pk}", background_parent=background_parent)


def _run_safely(callback, *args):
    try:
        callback(*args)
    except Exception:  # noqa: BLE001 - never let a text break the shop flow
        logger.exception("Shop SMS callback %s failed for %s", callback.__name__, args)


def queue_order_placed_sms(order):
    from gnu_jango.core.background import enabled, enqueue
    if enabled():
        enqueue("sms_event", {"event": "order_placed", "args": [order.pk]}, dedupe_key=f"sms-order-placed:{order.pk}")
        return
    order_id = order.pk
    transaction.on_commit(lambda: _run_safely(send_order_placed_sms, order_id))


def queue_order_status_sms(order, status):
    if status not in STATUS_SLOTS:
        return
    from gnu_jango.core.background import enabled, enqueue
    if enabled():
        enqueue("sms_event", {"event": "order_status", "args": [order.pk, status]})
        return
    order_id = order.pk
    transaction.on_commit(lambda: _run_safely(send_order_status_sms, order_id, status))


def queue_member_join_sms(user):
    from gnu_jango.core.background import enabled, enqueue
    if enabled():
        enqueue("sms_event", {"event": "member_join", "args": [user.pk]}, dedupe_key=f"sms-member-join:{user.pk}")
        return
    user_id = user.pk
    transaction.on_commit(lambda: _run_safely(send_member_join_sms, user_id))
