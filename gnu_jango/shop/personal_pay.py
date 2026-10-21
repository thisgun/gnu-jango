"""Personal pay (youngcart 개인결제): the state of a request and how a payment is recorded.

youngcart shop/personalpayformupdate.php records a PG payment on the request (pp_tno, pp_receipt_price,
pp_receipt_time ...) and, when the request belongs to an order, adds the amount to that order and
moves it to 입금 once nothing is owed. This module does the same for a Toss payment and for a bank
deposit the shop admin confirms (adm/shop_admin/personalpayformupdate.php).

The amount always comes from pp_price on the server; the client never says how much is paid.
"""

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder, ShopPersonalPay

STATE_PAID = "paid"
STATE_PROCESSING = "processing"
STATE_AWAITING_DEPOSIT = "awaiting_deposit"
STATE_READY = "ready"
STATE_LABELS = {
    STATE_PAID: "결제 완료",
    STATE_PROCESSING: "결제 처리 중",
    STATE_AWAITING_DEPOSIT: "입금 확인 대기",
    STATE_READY: "결제 대기",
}

SETTLE_BANK = "무통장"
BANK_SETTLE_CASES = {SETTLE_BANK, "무통장입금"}
METHOD_BANK = "bank"
# Toss Payments "method" values (Korean in API v1, English constants in the SDK) -> youngcart pp_settle_case
TOSS_METHOD_SETTLE_CASES = {
    "카드": "신용카드",
    "card": "신용카드",
    "계좌이체": "계좌이체",
    "transfer": "계좌이체",
    "휴대폰": "휴대폰",
    "mobile_phone": "휴대폰",
    "간편결제": "간편결제",
    "easy_pay": "간편결제",
}
# Toss orderId: 6-64 characters of letters, digits, "-", "_" and "=". The prefix keeps a personal pay
# from ever sharing an orderId with a shop order (both are numeric in youngcart).
TOSS_ORDER_PREFIX = "pp-"
TOSS_ORDER_ID_RE = re.compile(r"[A-Za-z0-9_=-]{6,64}")

MESSAGE_NO_AMOUNT = "결제할 금액이 없는 개인결제입니다."
MESSAGE_ALREADY_PAID = "이미 결제하신 개인결제 내역입니다."
MESSAGE_INACTIVE = "사용하지 않는 개인결제입니다."
MESSAGE_AWAITING_DEPOSIT = "무통장입금 확인을 기다리는 개인결제입니다. 입금이 확인되면 결제가 완료됩니다."
MESSAGE_AMOUNT_CHANGED = "개인결제 금액이 바뀌었습니다. 결제 화면을 다시 열어 주세요."


def is_paid(item):
    return item.pp_price > 0 and item.pp_receipt_price >= item.pp_price


def amount_due(item):
    """What is still to be paid (pp_price less a part the shop already recorded)."""
    return max(0, int(item.pp_price or 0) - int(item.pp_receipt_price or 0))


def has_transaction(item):
    return bool(item.pp_tno or item.pp_app_no)


def is_awaiting_deposit(item):
    """The customer chose 무통장입금 and named the depositor; the shop has not confirmed the deposit."""
    return (
        not is_paid(item)
        and not has_transaction(item)
        and str(item.pp_settle_case or "").strip() in BANK_SETTLE_CASES
        and bool(str(item.pp_deposit_name or "").strip())
        and bool(str(item.pp_bank_account or "").strip())
    )


def payment_state(item):
    if is_paid(item):
        return STATE_PAID
    if has_transaction(item):
        return STATE_PROCESSING
    if is_awaiting_deposit(item):
        return STATE_AWAITING_DEPOSIT
    return STATE_READY


def checkout_block_reason(item, method):
    """Why ``item`` cannot be paid with ``method`` ("bank" or an online method), "" when it can.

    A bank deposit can be re-entered (another account or depositor) while it waits for the shop;
    an online payment then is refused so the same request is not paid twice."""
    if not item.active:
        return MESSAGE_INACTIVE
    if item.pp_price <= 0:
        # YoungCart personalpayform.php loads only requests with an amount
        return MESSAGE_NO_AMOUNT
    state = payment_state(item)
    if state in {STATE_PAID, STATE_PROCESSING}:
        return MESSAGE_ALREADY_PAID
    if state == STATE_AWAITING_DEPOSIT and method != METHOD_BANK:
        return MESSAGE_AWAITING_DEPOSIT
    return ""


def toss_order_id(item):
    """The Toss orderId of ``item`` ("" when its pp_id cannot be one)."""
    order_id = f"{TOSS_ORDER_PREFIX}{item.pp_id}"
    return order_id if TOSS_ORDER_ID_RE.fullmatch(order_id) else ""


def toss_settle_case(method):
    normalized = str(method or "").strip().lower().replace(" ", "_")
    return TOSS_METHOD_SETTLE_CASES.get(normalized, str(method or "").strip()[:50] or "신용카드")


def receipt_time_label(value=None):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S") if value else timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")


@transaction.atomic
def choose_bank_deposit(pp_id, *, bank_account, deposit_name):
    """Save the customer's 무통장입금 choice. Returns (personal pay, block reason)."""
    item = ShopPersonalPay.objects.select_for_update().filter(pk=pp_id).first()
    if item is None:
        return None, MESSAGE_INACTIVE
    reason = checkout_block_reason(item, METHOD_BANK)
    if reason:
        return item, reason
    item.pp_settle_case = SETTLE_BANK
    item.pp_bank_account = bank_account[:255]
    item.pp_deposit_name = deposit_name[:100]
    item.pp_pg = ""
    item.save(update_fields=["pp_settle_case", "pp_bank_account", "pp_deposit_name", "pp_pg"])
    return item, ""


@dataclass(frozen=True)
class Receipt:
    amount: int
    settle_case: str
    receipt_time: str
    pg: str = ""
    tno: str = ""
    app_no: str = ""
    bank_account: str | None = None
    deposit_name: str | None = None
    cash_no: str = ""


@transaction.atomic
def record_receipt(pp_id, receipt, *, method, actor=""):
    """Record a payment of ``pp_id`` and apply it to the linked order.

    Returns (personal pay, block reason): a request that was paid, cancelled or deactivated in the
    meantime is left alone and the reason comes back, so the caller can refund an online payment.
    Recording the same transaction again is a no-op (an idempotent confirm)."""
    item = ShopPersonalPay.objects.select_for_update().filter(pk=pp_id).first()
    if item is None:
        return None, MESSAGE_INACTIVE
    if receipt.tno and item.pp_tno == receipt.tno and is_paid(item):
        return item, ""
    reason = checkout_block_reason(item, method)
    if reason:
        return item, reason
    if receipt.amount != amount_due(item):
        return item, MESSAGE_AMOUNT_CHANGED
    item.pp_receipt_price = int(item.pp_receipt_price or 0) + receipt.amount
    item.pp_receipt_time = receipt.receipt_time
    item.pp_settle_case = receipt.settle_case[:50]
    item.pp_pg = receipt.pg[:50]
    fields = ["pp_receipt_price", "pp_receipt_time", "pp_settle_case", "pp_pg"]
    optional = (
        ("pp_tno", receipt.tno or None),
        ("pp_app_no", receipt.app_no or None),
        ("pp_bank_account", receipt.bank_account),
        ("pp_deposit_name", receipt.deposit_name),
    )
    for name, value in optional:
        if value is not None:
            setattr(item, name, str(value)[: ShopPersonalPay._meta.get_field(name).max_length])
            fields.append(name)
    if receipt.cash_no:
        item.pp_cash = 1
        item.pp_cash_no = receipt.cash_no[:255]
        fields += ["pp_cash", "pp_cash_no"]
    item.save(update_fields=fields)
    if item.order_id:
        apply_receipt_to_order(item, receipt, actor=actor)
    return item, ""


def apply_receipt_to_order(item, receipt, *, actor=""):
    """personalpayformupdate.php: the payment is added to the linked order, a note goes in its shop
    memo and a bank-deposit order that no longer owes anything moves to 입금."""
    from gnu_jango.api.shop_payments import settle_case_is_bank
    from gnu_jango.shop.order_flow import (
        STATUS_ORDERED,
        STATUS_PAID,
        canonical_status,
        move_order_status,
        order_misu,
    )

    from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES

    order = ShopOrder.objects.select_for_update().filter(pk=item.order_id).first()
    # a cancelled, returned or sold-out order is closed: its amounts are not reopened
    if order is None or canonical_status(order.od_status) in INACTIVE_LINE_STATUSES:
        return
    note = f"개인결제 {item.pp_id} 로 결제완료 - {receipt.receipt_time}"
    order.od_receipt_price = int(order.od_receipt_price or 0) + receipt.amount
    order.od_receipt_time = receipt.receipt_time
    order.od_shop_memo = f"{order.od_shop_memo}\n{note}" if order.od_shop_memo else note
    order.od_misu = order_misu(order)
    order.save(update_fields=["od_receipt_price", "od_receipt_time", "od_shop_memo", "od_misu"])
    if (
        order.od_misu == 0
        and canonical_status(order.od_status) == STATUS_ORDERED
        and settle_case_is_bank(order.od_settle_case)
    ):
        move_order_status(order, STATUS_PAID, actor=actor or f"개인결제 {item.pp_id}")


def confirm_bank_deposit(pp_id, *, actor=""):
    """The shop admin confirms the deposit of a 무통장입금 request: what is still owed is received now."""
    item = ShopPersonalPay.objects.filter(pk=pp_id).first()
    if item is None:
        return None, MESSAGE_INACTIVE
    if has_transaction(item):
        return item, MESSAGE_ALREADY_PAID
    settle_case = item.pp_settle_case if str(item.pp_settle_case or "").strip() in BANK_SETTLE_CASES else SETTLE_BANK
    receipt = Receipt(amount=amount_due(item), settle_case=settle_case, receipt_time=receipt_time_label())
    return record_receipt(pp_id, receipt, method=METHOD_BANK, actor=actor)
