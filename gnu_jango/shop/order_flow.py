"""How the shop admin moves an order (youngcart adm/shop_admin/orderlistupdate.php and
orderformcartupdate.php): status changes, payment records and the admin cancellation that
refunds the payment before it cancels the order."""

import logging
from dataclasses import dataclass

from gnu_jango.shop.models import ShopOrder

logger = logging.getLogger(__name__)

STATUS_ORDERED = "주문"
STATUS_PAID = "입금"
STATUS_READY = "준비"
STATUS_SHIPPING = "배송"
STATUS_COMPLETED = "완료"
STATUS_CANCELLED = "취소"

# Older rows (and the API's own aliases) spell the statuses in English.
STATUS_ALIASES = {
    "order": STATUS_ORDERED,
    "ordered": STATUS_ORDERED,
    "pending": STATUS_ORDERED,
    "paid": STATUS_PAID,
    "payment": STATUS_PAID,
    "ready": STATUS_READY,
    "shipping": STATUS_SHIPPING,
    "delivery": STATUS_SHIPPING,
    "complete": STATUS_COMPLETED,
    "completed": STATUS_COMPLETED,
    "done": STATUS_COMPLETED,
    "cancel": STATUS_CANCELLED,
    "cancelled": STATUS_CANCELLED,
    "canceled": STATUS_CANCELLED,
}


@dataclass(frozen=True)
class StatusChange:
    """The outcome of one admin status change; falsy when the order was left as it was."""

    ok: bool
    message: str = ""
    manual_refund: bool = False

    def __bool__(self):
        return self.ok


def canonical_status(value):
    status = str(value or "").strip()
    return STATUS_ALIASES.get(status.lower(), status)


def paid_amount(order):
    """What the customer has actually paid.

    An online-payment order waiting for its payment already carries the amount to pay in
    od_receipt_price (the PG confirmation checks it), so while it is 주문 nothing is paid yet; a
    bank-deposit order records a deposit only when it is entered."""
    from gnu_jango.api.shop_payments import settle_case_is_bank

    if canonical_status(order.od_status) == STATUS_ORDERED and not settle_case_is_bank(order.od_settle_case):
        return 0
    return max(0, int(order.od_receipt_price or 0))


def admin_cancel_order(order, reason="", *, actor=""):
    """Cancel an order from the admin.

    A Toss card / transfer / easy-pay payment is cancelled at Toss first and the order is left
    untouched when Toss does not confirm it; a paid bank deposit or virtual account is cancelled
    here and recorded as a refund the admin makes by hand. Stock, coupons and points go back once
    through the shared cancel path, and the payment stays on record (od_receipt_price) next to the
    refund (od_refund_price)."""
    from gnu_jango.api.shop_common import CANCELLED_STATUSES
    from gnu_jango.api.shop_payments import (
        PaymentCancelError,
        cancel_pending_toss_vbank,
        order_paid_through_toss,
        record_payment_raw_log,
        settle_case_is_bank,
        settle_case_is_vbank,
        toss_api_cancel_payment,
    )
    from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits
    from gnu_jango.shop.inventory import order_history_line

    current = ShopOrder.objects.filter(pk=order.pk).first()
    if current is None:
        return StatusChange(False, "주문을 찾을 수 없습니다.")
    if str(current.od_status or "") in CANCELLED_STATUSES:
        return StatusChange(False, "이미 취소된 주문입니다.")

    paid = paid_amount(current)
    note = ""
    manual_refund = False
    pg_cancelled = False
    vbank_waiting = False
    if paid <= 0:
        if settle_case_is_vbank(current.od_settle_case) and current.od_tno:
            # the customer could still deposit into the issued account: close it first
            if cancel_pending_toss_vbank(current, reason or "쇼핑몰 운영자 취소") is not None:
                return StatusChange(
                    False, "토스페이먼츠 가상계좌를 취소하지 못해 주문을 그대로 두었습니다. 잠시 후 다시 시도하세요."
                )
            vbank_waiting = True
    elif order_paid_through_toss(current):
        try:
            canceled = toss_api_cancel_payment(current, reason or "쇼핑몰 운영자 승인 취소")
        except PaymentCancelError as exc:
            return StatusChange(False, f"결제 취소에 실패해 주문을 취소하지 않았습니다. {exc}")
        record_payment_raw_log(
            current, current.od_id, "toss", current.od_tno, {"toss_cancel": canceled}, prefix="toss-cancel"
        )
        note = f" PG {current.od_settle_case or '결제'} 승인취소 처리"
        pg_cancelled = True
    else:
        manual_refund = True
        if settle_case_is_bank(current.od_settle_case):
            note = " 무통장 환불 필요 (수동)"
        elif settle_case_is_vbank(current.od_settle_case):
            note = " 가상계좌 환불 필요 (수동)"
        else:
            note = f" PG({current.od_pg or '-'}) 승인취소 필요 (수동)"

    history = order_history_line(f"주문취소 처리{note}{f' - {reason}' if reason else ''}", actor)
    try:
        cancel_order_and_refund_benefits(current, "", refund_price=paid, history=history)
    except Exception:
        if not pg_cancelled:
            raise
        # the money went back already: the admin has to finish the order by hand
        logger.exception("order %s: Toss cancelled the payment but the local cancellation failed", current.od_id)
        return StatusChange(False, "PG 결제는 승인취소됐지만 주문을 취소 상태로 바꾸지 못했습니다. 주문을 확인해 주세요.")
    if vbank_waiting:
        ShopOrder.objects.filter(pk=current.pk).update(od_vbank_status="CANCELED")

    if manual_refund:
        message = f"주문 {current.od_id}을(를) 취소했습니다. 결제금액 {paid:,}원은 직접 환불해야 합니다.{note}"
    elif paid:
        message = f"주문 {current.od_id}을(를) 취소하고 결제금액 {paid:,}원을 PG에서 승인취소했습니다."
    else:
        message = f"주문 {current.od_id}을(를) 취소했습니다."
    return StatusChange(True, message, manual_refund=manual_refund)
