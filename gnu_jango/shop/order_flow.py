"""How the shop admin moves an order (youngcart adm/shop_admin/orderlistupdate.php and
orderformcartupdate.php): status changes, payment records and the admin cancellation that
refunds the payment before it cancels the order."""

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder, ShopOrderItem, ShopProduct

logger = logging.getLogger(__name__)

STATUS_ORDERED = "주문"
STATUS_PAID = "입금"
STATUS_READY = "준비"
STATUS_SHIPPING = "배송"
STATUS_COMPLETED = "완료"
STATUS_CANCELLED = "취소"

# youngcart adm/shop_admin/orderlist.php: the states an operator moves an order through.
# 반품/품절 (returns, sold out) are line-level outcomes youngcart reaches through
# orderformcartupdate.php; this admin has no returns flow yet.
ADMIN_ORDER_STATUSES = (STATUS_ORDERED, STATUS_PAID, STATUS_READY, STATUS_SHIPPING, STATUS_COMPLETED, STATUS_CANCELLED)
NEXT_STATUS = {
    STATUS_ORDERED: STATUS_PAID,
    STATUS_PAID: STATUS_READY,
    STATUS_READY: STATUS_SHIPPING,
    STATUS_SHIPPING: STATUS_COMPLETED,
}
CANCELLABLE_STATUSES = {STATUS_ORDERED, STATUS_PAID, STATUS_READY}

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


def transition_error(order, target, *, invoice=None, delivery_company=None):
    """Why ``order`` cannot move to ``target`` ("" when it can), following youngcart
    orderlistupdate.php: 주문→입금 (bank deposit only), 입금→준비, 준비→배송 (with an invoice),
    배송→완료, and a cancellation while the order is 주문, 입금 or 준비 (later it is a return).

    ``invoice`` / ``delivery_company`` are the values about to be saved (the order form);
    otherwise the stored ones are checked."""
    from gnu_jango.api.shop_payments import settle_case_is_bank

    current = canonical_status(order.od_status)
    if target not in ADMIN_ORDER_STATUSES:
        return "알 수 없는 주문 상태입니다."
    if current == STATUS_CANCELLED:
        return "취소된 주문은 다른 상태로 되돌릴 수 없습니다."
    if target == current:
        return f"이미 '{current}' 상태입니다."
    if target == STATUS_CANCELLED:
        if current not in CANCELLABLE_STATUSES:
            return f"'{current}' 상태의 주문은 취소할 수 없습니다. 주문·입금·준비 상태에서만 취소할 수 있습니다."
        return ""
    expected = NEXT_STATUS.get(current)
    if expected != target:
        if not expected:
            return f"'{current or '-'}' 상태의 주문은 다른 상태로 바꿀 수 없습니다."
        also_cancel = " 또는 '취소'" if current in CANCELLABLE_STATUSES else ""
        return f"'{current}' 상태에서는 '{expected}'{also_cancel}(으)로만 바꿀 수 있습니다."
    if target == STATUS_PAID and not settle_case_is_bank(order.od_settle_case):
        return "무통장입금 주문만 입금 처리할 수 있습니다. PG 결제는 결제 승인으로 입금됩니다."
    if target == STATUS_SHIPPING:
        invoice = order.od_invoice if invoice is None else invoice
        delivery_company = order.od_delivery_company if delivery_company is None else delivery_company
        if not str(invoice or "").strip() or not str(delivery_company or "").strip():
            return "배송회사와 운송장번호를 먼저 입력하세요."
    return ""


def allowed_targets(order):
    """The statuses the admin may pick for ``order`` (the order form's choices)."""
    # the carrier and invoice can be entered in the same form, so 배송 is offered and checked on save
    return [
        status
        for status in ADMIN_ORDER_STATUSES
        if not transition_error(order, status, invoice="-", delivery_company="-")
    ]


def order_cart_coupon(order):
    """The product coupons of the order (youngcart od_cart_coupon), from its coupon logs."""
    from gnu_jango.shop.order_coupons import order_coupon_totals

    return order_coupon_totals(order).cart


def order_misu(order):
    """youngcart get_order_info od_misu: what is still owed, never below zero.

    (goods - cancelled goods + shipping) - coupons - (paid + points used - refunded)"""
    total = (
        int(order.od_cart_price or 0)
        - int(order.od_cancel_price or 0)
        + int(order.od_send_cost or 0)
        + int(order.od_send_cost2 or 0)
        - order_cart_coupon(order)
        - int(order.od_coupon or 0)
        - int(order.od_send_coupon or 0)
    )
    settled = paid_amount(order) + int(order.od_receipt_point or 0) - int(order.od_refund_price or 0)
    return max(0, total - settled)


def update_product_sales_quantity(order):
    """youngcart orderlistupdate.php 배송→완료: it_sum_qty of each product of the order becomes the
    quantity of all its completed lines."""
    product_ids = set(
        order.items.filter(ct_status=STATUS_COMPLETED, product__isnull=False).values_list("product_id", flat=True)
    )
    for product_id in product_ids:
        sold = (
            ShopOrderItem.objects.filter(product_id=product_id, ct_status=STATUS_COMPLETED).aggregate(qty=Sum("ct_qty"))["qty"]
            or 0
        )
        ShopProduct.objects.filter(pk=product_id).update(it_sum_qty=sold)


def move_order_status(order, target, *, actor=""):
    """Move ``order`` one step along 주문→입금→준비→배송→완료 (not a cancellation), with the
    youngcart side effects: 입금 records the deposit (order_update_receipt), 배송 stamps the
    invoice time, 완료 updates the products' sales quantity. Lines follow the order and a paid
    line that leaves 완료 gives its purchase point back."""
    from gnu_jango.api.shop_common import CANCELLED_STATUSES
    from gnu_jango.shop.inventory import append_order_history, order_history_line
    from gnu_jango.shop.order_points import item_status_update, take_back_order_points

    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            return StatusChange(False, "주문을 찾을 수 없습니다.")
        error = transition_error(locked, target)
        if error:
            return StatusChange(False, error)
        previous = canonical_status(locked.od_status)
        now_label = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        fields = ["od_status", "od_misu", "od_mod_history"]
        # worked out from the amounts, not the stored od_misu (stale on some migrated orders)
        owed = order_misu(locked)
        locked.od_status = target
        if target == STATUS_PAID:
            # order_update_receipt: the amount owed is received now
            locked.od_receipt_price = int(locked.od_receipt_price or 0) + owed
            locked.od_receipt_time = now_label
            fields += ["od_receipt_price", "od_receipt_time"]
        if target == STATUS_SHIPPING and not locked.od_invoice_time:
            locked.od_invoice_time = now_label
            fields.append("od_invoice_time")
        locked.od_misu = order_misu(locked)
        locked.od_mod_history = append_order_history(
            locked.od_mod_history, order_history_line(f"주문상태 {previous}→{target} 처리", actor)
        )
        locked.save(update_fields=fields)
        locked.items.exclude(ct_status__in=CANCELLED_STATUSES).update(**item_status_update(target))
        # youngcart orderformcartupdate.php: a paid line that leaves 완료 gives its point back
        take_back_order_points(locked)
        if target == STATUS_COMPLETED:
            update_product_sales_quantity(locked)
    if target == STATUS_PAID:
        return StatusChange(True, f"주문 {locked.od_id}의 입금 {locked.od_receipt_price:,}원을 기록했습니다.")
    return StatusChange(True)


def admin_cancel_order(order, reason="", *, actor=""):
    """Cancel an order from the admin.

    A Toss card / transfer / easy-pay payment is cancelled at Toss first and the order is left
    untouched when Toss does not confirm it; a paid bank deposit or virtual account is cancelled
    here and recorded as a refund the admin makes by hand. Stock, coupons and points go back once
    through the shared cancel path, and the payment stays on record (od_receipt_price) next to the
    refund (od_refund_price)."""
    # The row stays locked from the checks through the PG call to the local cancel, so a status
    # move or a second cancel in between cannot slip past the checks or the refund amount. The
    # block is durable: once Toss has refunded, the cancellation commits on its own and cannot be
    # rolled back by whatever the caller's request does afterwards (the order form runs this after
    # its own transaction, see ShopOrderAdmin.change_view).
    with transaction.atomic(durable=True):
        current = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        return _cancel_locked_order(current, reason, actor)


def _cancel_locked_order(current, reason, actor):
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

    if current is None:
        return StatusChange(False, "주문을 찾을 수 없습니다.")
    if str(current.od_status or "") in CANCELLED_STATUSES:
        return StatusChange(False, "이미 취소된 주문입니다.")
    error = transition_error(current, STATUS_CANCELLED)
    if error:
        return StatusChange(False, error)

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
        note = f" PG {current.od_settle_case or '결제'} 승인취소 처리"
        pg_cancelled = True
        try:
            # a savepoint: a failed log write must not break the cancellation that follows
            with transaction.atomic():
                record_payment_raw_log(
                    current, current.od_id, "toss", current.od_tno, {"toss_cancel": canceled}, prefix="toss-cancel"
                )
        except Exception:  # noqa: BLE001 - Toss refunded already; the order must still be cancelled
            logger.exception("order %s: could not record the Toss cancel response", current.od_id)
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


def order_delete_block_reason(order):
    """Why the admin may not delete ``order`` ("" when it may).

    youngcart orderlistdelete.php deletes only 주문 orders; a cancelled order that was never paid
    has nothing left to give back, so it may go too. Anything paid, shipped or completed stays on record, and an
    order with an issued virtual account is cancelled first (that closes the account at Toss)."""
    from gnu_jango.api.shop_payments import settle_case_is_vbank

    status = canonical_status(order.od_status)
    if status == STATUS_CANCELLED:
        if int(order.od_receipt_price or 0) > 0 or int(order.od_refund_price or 0) > 0:
            # the payment and refund record (a manual refund may still be owed) stays
            return "결제·환불 기록이 있는 취소 주문은 삭제할 수 없습니다."
        return ""
    if status != STATUS_ORDERED:
        return f"'{status or '-'}' 상태의 주문은 삭제할 수 없습니다. 주문(미입금) 또는 취소된 주문만 삭제할 수 있습니다."
    if paid_amount(order) > 0:
        return "입금 기록이 있는 주문은 삭제할 수 없습니다. 먼저 취소하세요."
    if settle_case_is_vbank(order.od_settle_case) and order.od_tno:
        return "가상계좌가 발급된 주문은 먼저 취소한 뒤 삭제하세요."
    return ""


def delete_order(order, *, actor=""):
    """Delete an unpaid or cancelled order. An unpaid one is cancelled first through the shared
    cancel path, so its reserved stock, coupons and points come back before it disappears."""
    from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits
    from gnu_jango.shop.inventory import order_history_line

    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            return StatusChange(True)
        reason = order_delete_block_reason(locked)
        if reason:
            return StatusChange(False, reason)
        if canonical_status(locked.od_status) != STATUS_CANCELLED:
            cancel_order_and_refund_benefits(locked, "", history=order_history_line("주문삭제 전 취소 처리", actor))
        locked.delete()
    return StatusChange(True)
