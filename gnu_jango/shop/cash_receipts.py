"""Cash receipts (현금영수증) asked for after the order (youngcart shop/taxsave.php and the PG's
taxsave_result.php), issued, cancelled and recorded by the admin.

A paid bank deposit, virtual account or account transfer order (de_taxsave_use / de_taxsave_types
for the customer) can get a receipt for what was paid in cash minus refunds. It is issued at once
through the Toss cash receipt API when Toss keys are set and the order was paid through Toss or by
bank deposit (youngcart's toss taxsave_result.php issues for 무통장 too); any other order is
recorded as a request the admin issues by hand (현금영수증 요청 (수동 발급)).

Storage (no new columns): od_cash_request / od_cash_type say a receipt was asked for, od_cash_no is
the approval number once issued and od_cash_res its receipt link. Toss's answer, with the
receiptKey needed to cancel it, is a ShopOrderData log ("tcr-"). The identification number of a
manual request is kept, sealed (shop/sealed_values.py), in its own ShopOrderData row ("crq-")
only until the receipt is issued or the request ends, because the admin needs it to issue; a Toss
request never stores it.
"""

import json
import logging
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from gnu_jango.shop.cash_receipt_toss import (
    TOSS_RECEIPT_TYPES,
    CashReceiptApiError,
    cancel_toss_cash_receipt,
    issue_toss_cash_receipt,
    toss_cash_receipts_enabled,
)
from gnu_jango.shop.models import ShopOrder, ShopOrderData
from gnu_jango.shop.sealed_values import seal, unseal
from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES

logger = logging.getLogger(__name__)

CASH_RECEIPT_TYPE_LABELS = TOSS_RECEIPT_TYPES
REQUEST_LOG_PREFIX = "crq-"
TOSS_ISSUE_LOG_PREFIX = "tcr"  # record_payment_raw_log names it "tcr-pay-<od_id>-<receiptKey>"
TOSS_CANCEL_LOG_PREFIX = "tcrc"
REQUEST_LOG_PG = "cash_receipt"
IDENTITY_SEAL_SALT = "cash_receipt_identity"

STATE_ISSUED = "issued"
STATE_CANCEL_NEEDED = "cancel_needed"
STATE_REQUESTED = "requested"
STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"

KIND_TOSS = "toss"  # issued with the cash receipt API here: cancelled with its receiptKey
KIND_PAYMENT = "payment"  # issued by Toss with the payment (transfer / virtual account checkout)
KIND_MANUAL = "manual"  # issued outside (Hometax, another PG) and recorded by the admin


class CashReceiptError(Exception):
    def __init__(self, message, code="cash_receipt_invalid", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class CashReceiptResult:
    message: str
    issued: bool = False  # issued now (False: recorded as a request for manual issuance)


def _history(order, text, actor):
    from gnu_jango.shop.inventory import append_order_history, order_history_line

    order.od_mod_history = append_order_history(order.od_mod_history, order_history_line(text, actor))


def _closed(order):
    from gnu_jango.shop.order_flow import canonical_status

    return canonical_status(order.od_status) in INACTIVE_LINE_STATUSES


def normalize_identity(cash_type, value):
    """The identification number Toss takes (digits): a business number (10 digits) for 지출증빙,
    a phone or cash receipt card number for 소득공제 (the checkout rule, api.v1_shop)."""
    if cash_type not in CASH_RECEIPT_TYPE_LABELS:
        raise CashReceiptError("현금영수증 종류를 소득공제 또는 지출증빙 중에서 고르세요.", "cash_receipt_type_invalid")
    digits = re.sub(r"\D+", "", str(value or ""))
    valid = len(digits) == 10 if cash_type == "expense" else 8 <= len(digits) <= 30
    if not valid:
        hint = "사업자등록번호 10자리" if cash_type == "expense" else "휴대폰번호 또는 현금영수증카드 번호"
        raise CashReceiptError(f"{hint}를 정확히 입력하세요.", "cash_receipt_identity_invalid")
    return digits


def mask_identity(value):
    digits = str(value or "")
    if len(digits) <= 6:
        return "*" * len(digits)
    return f"{digits[:3]}{'*' * (len(digits) - 7)}{digits[-4:]}"


def receipt_amounts(order):
    """(amount, tax-free part): the cash paid minus refunds (youngcart taxsave.php
    od_receipt_price - od_refund_price), held to the order's tax split when it has one
    (od_tax_mny + od_vat_mny + od_free_mny, which leaves out points). Personal pay receipts
    credited to the order (od_receipt_price) were paid on their own transactions; those paid by
    card, phone or easy pay are not cash and are left out."""
    from gnu_jango.api.shop_payments import settle_case_supports_cash_receipt
    from gnu_jango.shop.order_flow import paid_amount

    non_cash = sum(
        max(0, int(price or 0))
        for settle_case, price in order.personal_pays.values_list("pp_settle_case", "pp_receipt_price")
        if not settle_case_supports_cash_receipt(settle_case)
    )
    net = max(0, paid_amount(order) - non_cash - max(0, int(order.od_refund_price or 0)))
    split = sum(max(0, int(value or 0)) for value in (order.od_tax_mny, order.od_vat_mny, order.od_free_mny))
    amount = min(net, split) if split > 0 else net
    return amount, min(amount, max(0, int(order.od_free_mny or 0)))


def order_name(order):
    """youngcart get_goods full_name: the first product, "외 N건" for the rest."""
    names = list(order.items.order_by("pk").values_list("it_name", flat=True)[:1])
    count = order.items.count()
    first = str(names[0] if names else order.od_id)
    return (f"{first} 외 {count - 1}건" if count > 1 else first)[:100]


def pending_request(order):
    """The manual request row ({"cash_type", "identity", "identity_masked", ...}) or None. The
    identification number is stored sealed (shop/sealed_values.py) and opened only here."""
    row = ShopOrderData.objects.filter(log_id=f"{REQUEST_LOG_PREFIX}{order.od_id}"[:40]).first()
    if row is None:
        return None
    try:
        data = json.loads(row.dt_data or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    identity = unseal(data.pop("identity_sealed", ""), salt=IDENTITY_SEAL_SALT)
    return {**data, "identity": identity, "identity_masked": mask_identity(identity)}


def _drop_pending_request(order):
    ShopOrderData.objects.filter(log_id=f"{REQUEST_LOG_PREFIX}{order.od_id}"[:40]).delete()


def toss_issued_receipt(order):
    """Toss's answer for the receipt on the order issued with the cash receipt API (with its
    receiptKey), or None."""
    if not order.od_cash_no:
        return None
    for row in ShopOrderData.objects.filter(order_id=order.pk, log_id__startswith=f"{TOSS_ISSUE_LOG_PREFIX}-pay-").order_by(
        "-dt_time"
    ):
        try:
            receipt = json.loads(row.dt_data or "{}").get("toss_cash_receipt") or {}
        except (ValueError, AttributeError):
            continue
        if order.od_cash_no in {str(receipt.get("issueNumber") or ""), str(receipt.get("receiptKey") or "")}:
            return receipt
    return None


def issued_kind(order):
    if not order.od_cash_no:
        return ""
    if toss_issued_receipt(order):
        return KIND_TOSS
    if str(order.od_pg or "").strip().lower() == "toss" and order.od_tno:
        return KIND_PAYMENT
    return KIND_MANUAL


def eligibility_error(order, *, by_admin=False):
    """Why ``order`` cannot get a cash receipt now ("" when it can): youngcart shop_is_taxsave
    (the admin may issue whatever the settings say, like youngcart's super admin), paid in full."""
    from gnu_jango.api.shop_payments import settle_case_supports_cash_receipt
    from gnu_jango.shop.order_flow import order_misu, paid_amount
    from gnu_jango.shop.payment_options import cash_receipt_method_enabled

    if _closed(order):
        return "취소·반품된 주문은 현금영수증을 발급할 수 없습니다."
    if not settle_case_supports_cash_receipt(order.od_settle_case):
        return "현금영수증은 무통장입금·가상계좌·계좌이체 주문만 발급할 수 있습니다."
    if not by_admin and not cash_receipt_method_enabled(order.od_settle_case):
        return "이 결제수단은 현금영수증 발급을 받지 않습니다."
    if order.od_cash_no:
        return "이미 현금영수증이 발급되었습니다."
    if paid_amount(order) <= 0 or order_misu(order) > 0:
        return "결제를 마친 주문만 현금영수증을 발급할 수 있습니다."
    if receipt_amounts(order)[0] <= 0:
        return "현금영수증을 발급할 금액이 없습니다."
    return ""


def issues_through_toss(order):
    from gnu_jango.api.shop_payments import settle_case_is_bank

    return toss_cash_receipts_enabled() and (
        str(order.od_pg or "").strip().lower() == "toss" or settle_case_is_bank(order.od_settle_case)
    )


def receipt_state(order, *, by_admin=False):
    if order.od_cash_no:
        return STATE_CANCEL_NEEDED if _closed(order) else STATE_ISSUED
    if pending_request(order) is not None:
        return STATE_REQUESTED
    if eligibility_error(order, by_admin=by_admin):
        return STATE_REQUESTED if order.od_cash_request and not _closed(order) else STATE_UNAVAILABLE
    return STATE_AVAILABLE


def request_cash_receipt(order, cash_type, identity, *, actor="", by_admin=False):
    """Issue (or, without Toss, record for manual issuance) a cash receipt for ``order``.

    Raises CashReceiptError with the reason shown to the customer or the admin. The order row is
    locked from the checks through the Toss call to the save, in a durable transaction, so a
    second request waits and then finds the receipt issued."""
    cash_type = str(cash_type or "").strip()
    identity = normalize_identity(cash_type, identity)
    with transaction.atomic(durable=True):
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            raise CashReceiptError("주문을 찾을 수 없습니다.", "order_not_found", 404)
        error = eligibility_error(locked, by_admin=by_admin)
        if error:
            raise CashReceiptError(error, "cash_receipt_unavailable")
        if not by_admin and pending_request(locked) is not None:
            raise CashReceiptError("이미 현금영수증 발급을 신청했습니다. 발급되면 이 화면에 표시됩니다.", "cash_receipt_requested")
        if issues_through_toss(locked):
            return _issue_with_toss(locked, cash_type, identity, actor)
        return _record_manual_request(locked, cash_type, identity, actor, by_admin=by_admin)


def _toss_order_id(order):
    """youngcart sends od_id as the receipt's orderId; a receipt issued again after a cancel
    gets a fresh one."""
    issued_before = ShopOrderData.objects.filter(
        order_id=order.pk, log_id__startswith=f"{TOSS_ISSUE_LOG_PREFIX}-pay-"
    ).count()
    return order.od_id if not issued_before else f"{order.od_id}-r{issued_before}"[:64]


def _issue_with_toss(order, cash_type, identity, actor):
    from gnu_jango.api.shop_payments import record_payment_raw_log, safe_receipt_url

    amount, tax_free = receipt_amounts(order)
    try:
        receipt = issue_toss_cash_receipt(
            order_id=_toss_order_id(order),
            order_name=order_name(order),
            amount=amount,
            cash_type=cash_type,
            identity=identity,
            tax_free=tax_free,
        )
    except CashReceiptApiError as exc:
        raise CashReceiptError(str(exc), "cash_receipt_provider_rejected", 502) from exc
    number = str(receipt.get("issueNumber") or "").strip() or str(receipt["receiptKey"]).strip()
    try:
        with transaction.atomic():
            record_payment_raw_log(
                order, order.od_id, "toss", str(receipt["receiptKey"]), {"toss_cash_receipt": receipt}, prefix=TOSS_ISSUE_LOG_PREFIX
            )
            order.od_cash_request = True
            order.od_cash_type = cash_type
            order.od_cash_no = number[:255]
            order.od_cash_res = safe_receipt_url(receipt.get("receiptUrl"))
            in_progress = str(receipt.get("issueStatus") or "").upper() == "IN_PROGRESS"
            _history(
                order,
                f"현금영수증 발급 (토스페이먼츠, {CASH_RECEIPT_TYPE_LABELS[cash_type]}) {amount:,}원 승인번호 {order.od_cash_no}"
                + (" - 발급 진행 중" if in_progress else ""),
                actor,
            )
            order.save(update_fields=["od_cash_request", "od_cash_type", "od_cash_no", "od_cash_res", "od_mod_history"])
            _drop_pending_request(order)
    except Exception as exc:
        # youngcart taxsave_result.php: a receipt that could not be recorded is cancelled again
        logger.exception("order %s: Toss issued cash receipt %s but it could not be saved", order.od_id, number)
        try:
            cancel_toss_cash_receipt(receipt["receiptKey"])
        except CashReceiptApiError:
            logger.exception("order %s: could not cancel the unsaved cash receipt", order.od_id)
        raise CashReceiptError("현금영수증 발급 기록에 실패해 발급을 취소했습니다. 잠시 후 다시 시도하세요.", "cash_receipt_save_failed", 500) from exc
    return CashReceiptResult(f"현금영수증이 발급되었습니다. 승인번호 {order.od_cash_no}", issued=True)


def _record_manual_request(order, cash_type, identity, actor, *, by_admin):
    ShopOrderData.objects.update_or_create(
        log_id=f"{REQUEST_LOG_PREFIX}{order.od_id}"[:40],
        defaults={
            "order": order,
            "od_id": order.od_id,
            "user": order.user if order.user_id else None,
            "mb_id": order.user.get_username() if order.user_id else "",
            "dt_pg": REQUEST_LOG_PG,
            "dt_data": json.dumps(
                {
                    "cash_type": cash_type,
                    "identity_sealed": seal(identity, salt=IDENTITY_SEAL_SALT),
                    "requested_at": timezone.now().isoformat(),
                },
                ensure_ascii=False,
            ),
            "dt_time": timezone.now(),
        },
    )
    order.od_cash_request = True
    order.od_cash_type = cash_type
    who = "관리자 입력" if by_admin else "고객 신청"
    _history(order, f"현금영수증 요청 (수동 발급, {CASH_RECEIPT_TYPE_LABELS[cash_type]}, {who})", actor)
    order.save(update_fields=["od_cash_request", "od_cash_type", "od_mod_history"])
    return CashReceiptResult("현금영수증 발급 신청이 접수되었습니다. 발급되면 주문 상세에 승인번호가 표시됩니다.")


def mark_issued(order, number, receipt_url="", *, actor=""):
    """The admin records a receipt issued by hand (Hometax, another PG): approval number and,
    optionally, its receipt link. The kept identification number is deleted."""
    from gnu_jango.api.shop_payments import safe_receipt_url

    number = str(number or "").strip()
    if not number or len(number) > 100:
        raise CashReceiptError("현금영수증 승인번호를 입력하세요.")
    url = str(receipt_url or "").strip()
    if url and not safe_receipt_url(url):
        raise CashReceiptError("영수증 주소는 http:// 또는 https:// 로 시작해야 합니다.")
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
        if locked.od_cash_no:
            raise CashReceiptError("이미 현금영수증이 등록되어 있습니다. 먼저 취소 처리하세요.")
        if _closed(locked):
            raise CashReceiptError("취소·반품된 주문에는 현금영수증을 등록할 수 없습니다.")
        request = pending_request(locked) or {}
        locked.od_cash_request = True
        locked.od_cash_type = request.get("cash_type") or locked.od_cash_type or "income"
        locked.od_cash_no = number
        locked.od_cash_res = safe_receipt_url(url)
        _history(locked, f"현금영수증 발급 등록 (수동) 승인번호 {number}", actor)
        locked.save(update_fields=["od_cash_request", "od_cash_type", "od_cash_no", "od_cash_res", "od_mod_history"])
        _drop_pending_request(locked)
    return CashReceiptResult(f"현금영수증 승인번호 {number}을(를) 등록했습니다.", issued=True)


def withdraw_request(order, *, actor="", reason=""):
    """The admin turns a request down (or the customer's details were wrong): it can be asked again."""
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
        if locked.od_cash_no:
            raise CashReceiptError("발급된 현금영수증은 요청 취소가 아니라 발급 취소로 처리하세요.")
        _drop_pending_request(locked)
        locked.od_cash_request = False
        _history(locked, f"현금영수증 요청 취소{f' - {reason}' if reason else ''}", actor)
        locked.save(update_fields=["od_cash_request", "od_mod_history"])
    return CashReceiptResult("현금영수증 요청을 취소했습니다.")


def cancel_receipt(order, *, actor="", reason="", order_closed=False):
    """Cancel the issued receipt of ``order``: through Toss when it was issued with the cash
    receipt API here, otherwise recorded as cancelled (a payment-linked Toss receipt goes with the
    payment, a manual one is cancelled where it was issued). Raises CashReceiptError when Toss
    refuses; nothing changes then."""
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
        if not locked.od_cash_no:
            raise CashReceiptError("취소할 현금영수증이 없습니다.")
        kind = issued_kind(locked)
        number = locked.od_cash_no
        if kind == KIND_TOSS:
            receipt = toss_issued_receipt(locked)
            try:
                answer = cancel_toss_cash_receipt(receipt.get("receiptKey"))
            except CashReceiptApiError as exc:
                raise CashReceiptError(str(exc), "cash_receipt_provider_rejected", 502) from exc
            _record_cancel_answer(locked, receipt, answer)
            note = "토스페이먼츠 취소" + (" (이미 취소되어 있음)" if answer.get("already_canceled") else "")
        elif kind == KIND_PAYMENT and order_closed:
            note = "결제와 함께 발급된 토스페이먼츠 현금영수증 - 결제 취소로 함께 취소"
        elif kind == KIND_PAYMENT:
            note = "결제와 함께 발급된 토스페이먼츠 현금영수증 - 토스페이먼츠 상점관리자에서 취소, 기록만 반영"
        else:
            note = "수동 발급분 - 발급처에서 취소, 기록만 반영"
        locked.od_cash_no = ""
        locked.od_cash_res = ""
        locked.od_cash_request = False if not order_closed else locked.od_cash_request
        _history(locked, f"현금영수증 취소 승인번호 {number} ({note}){f' - {reason}' if reason else ''}", actor)
        locked.save(update_fields=["od_cash_no", "od_cash_res", "od_cash_request", "od_mod_history"])
        _drop_pending_request(locked)
    return CashReceiptResult(f"현금영수증 {number}을(를) 취소했습니다. ({note})")


def _record_cancel_answer(order, receipt, answer):
    from gnu_jango.api.shop_payments import record_payment_raw_log

    try:
        with transaction.atomic():
            record_payment_raw_log(
                order, order.od_id, "toss", str(receipt.get("receiptKey") or ""), {"toss_cash_receipt_cancel": answer},
                prefix=TOSS_CANCEL_LOG_PREFIX,
            )
    except Exception:  # noqa: BLE001 - Toss cancelled already; the order must still say so
        logger.exception("order %s: could not record the cash receipt cancel response", order.od_id)


def schedule_close_settlement(order):
    """Called when an order is cancelled or returned as a whole (api.v1_shop
    cancel_order_and_refund_benefits): once that commits, its cash receipt is cancelled (Toss) or
    flagged for a manual cancel, and a pending request is dropped with its identification number."""
    if not (order.od_cash_no or order.od_cash_request):
        return
    order_pk = order.pk
    transaction.on_commit(lambda: settle_receipt_after_close(order_pk))


def settle_receipt_after_close(order_pk):
    from gnu_jango.api.shop_payments import order_paid_through_toss

    try:
        order = ShopOrder.objects.filter(pk=order_pk).first()
        if order is None or not _closed(order):
            return
        _drop_pending_request(order)
        kind = issued_kind(order)
        if kind == KIND_TOSS or (kind == KIND_PAYMENT and order_paid_through_toss(order)):
            try:
                cancel_receipt(order, actor="system", reason="주문 취소·반품", order_closed=True)
            except CashReceiptError as exc:
                _flag_manual_cancel(order, str(exc))
        elif kind:
            _flag_manual_cancel(order, "")
    except Exception:  # noqa: BLE001 - runs after the cancellation committed; never break it
        logger.exception("order %s: settling the cash receipt after the cancellation failed", order_pk)


def _flag_manual_cancel(order, detail):
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
        _history(locked, f"현금영수증 취소 필요 (수동) 승인번호 {locked.od_cash_no}{f' - {detail}' if detail else ''}", "system")
        locked.save(update_fields=["od_mod_history"])


def partial_refund_note(order, refund):
    """The history note for a partial refund of an order with an issued receipt: the receipt
    keeps its amount and is corrected by hand (cancelled and issued again for the rest)."""
    if not order.od_cash_no or refund <= 0:
        return ""
    return f" 현금영수증 금액 조정 필요 (환불 {refund:,}원, 승인번호 {order.od_cash_no})"


def customer_payload(order):
    """What the order page needs to offer the request (order_payload's cash_receipt)."""
    state = receipt_state(order)
    amount, _ = receipt_amounts(order)
    reason = "" if state != STATE_UNAVAILABLE else eligibility_error(order)
    if state == STATE_AVAILABLE and order.od_cash_request:
        message = "주문할 때 신청한 현금영수증을 발급하려면 식별번호를 입력하세요."
    elif state == STATE_REQUESTED:
        message = "현금영수증 신청이 접수되었습니다. 발급되면 승인번호가 표시됩니다."
    elif state == STATE_ISSUED:
        message = f"현금영수증 승인번호 {order.od_cash_no}"
    else:
        message = reason
    return {
        "state": state,
        "can_request": state == STATE_AVAILABLE,
        "amount": amount if state == STATE_AVAILABLE else 0,
        "types": [{"value": value, "label": label} for value, label in CASH_RECEIPT_TYPE_LABELS.items()],
        "message": message,
        "request_url": f"/api/v1/shop/orders/{order.od_id}/cash-receipt" if state == STATE_AVAILABLE else "",
    }


def admin_summary(order):
    """The admin's view of the receipt: state, label, tone and what can be done."""
    state = receipt_state(order, by_admin=True)
    request = pending_request(order)
    kind = issued_kind(order)
    labels = {
        STATE_ISSUED: ("현금영수증 발급됨", "success"),
        STATE_CANCEL_NEEDED: ("현금영수증 취소 필요", "danger"),
        STATE_REQUESTED: ("현금영수증 요청 (수동 발급)", "warning"),
        STATE_AVAILABLE: ("현금영수증 발급 가능", "info"),
        STATE_UNAVAILABLE: ("현금영수증 대상 아님", "neutral"),
    }
    # a checkout request without a number (bank deposit) waits for the admin like a manual one
    label, tone = labels[STATE_REQUESTED if state == STATE_AVAILABLE and order.od_cash_request else state]
    amount, tax_free = receipt_amounts(order)
    return {
        "state": state,
        "label": label,
        "tone": tone,
        "kind": kind,
        "kind_label": {KIND_TOSS: "토스페이먼츠 발급", KIND_PAYMENT: "결제 시 토스페이먼츠 발급", KIND_MANUAL: "수동 등록"}.get(kind, ""),
        "number": order.od_cash_no,
        "url": order.od_cash_res if order.od_cash_res.startswith(("https://", "http://")) else "",
        "type_label": CASH_RECEIPT_TYPE_LABELS.get(order.od_cash_type, ""),
        "request": request,
        "request_identity": (request or {}).get("identity", ""),
        "request_type": (request or {}).get("cash_type", "") or order.od_cash_type,
        "checkout_request_without_number": bool(order.od_cash_request and not order.od_cash_no and request is None),
        "amount": amount,
        "tax_free": tax_free,
        "issue_error": eligibility_error(order, by_admin=True),
        "through_toss": issues_through_toss(order),
        "issued_amount": issued_amount(order),
        "needs_correction": needs_amount_correction(order),
    }


def issued_amount(order):
    """What a receipt issued through the Toss API here was issued for (None when unknown)."""
    receipt = toss_issued_receipt(order)
    try:
        return int(receipt["amount"]) if receipt and receipt.get("amount") is not None else None
    except (TypeError, ValueError):
        return None


def needs_amount_correction(order):
    """True when a refund after issuance left the receipt above what was paid in cash: it has to
    be cancelled and issued again for the rest (the number is not kept, so not automatically)."""
    if not order.od_cash_no or _closed(order):
        return False
    issued = issued_amount(order)
    return issued is not None and issued > receipt_amounts(order)[0]


def admin_risk(order):
    """A risk card for the order page when the receipt needs the admin, else None."""
    if order.od_cash_no and _closed(order):
        return {"label": "현금영수증 취소 필요", "value": order.od_cash_no, "tone": "danger", "hint": "취소·반품된 주문에 발급된 현금영수증이 남아 있습니다."}
    if needs_amount_correction(order):
        return {"label": "현금영수증 금액 조정 필요", "value": order.od_cash_no, "tone": "warning", "hint": "부분 환불 뒤 현금영수증 금액이 현금 결제액보다 큽니다. 취소한 뒤 남은 금액으로 다시 발급하세요."}
    if not order.od_cash_no and (order.od_cash_request or pending_request(order) is not None) and not _closed(order):
        return {"label": "현금영수증 요청 (수동 발급)", "value": CASH_RECEIPT_TYPE_LABELS.get(order.od_cash_type, "-"), "tone": "warning", "hint": "고객이 요청한 현금영수증을 발급하거나 승인번호를 등록하세요."}
    return None
