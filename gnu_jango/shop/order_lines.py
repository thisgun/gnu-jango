"""Line-level cancellations of a shop order: 취소, 반품 and 품절 of chosen order lines, with the
refund of what the customer overpaid (youngcart adm/shop_admin/orderformcartupdate.php and
orderpartcancelupdate.php).

The order is priced again the way youngcart lib/shop.lib.php get_order_info does it: only the
주문~완료 lines count, product coupons on cancelled lines drop out, the order and shipping coupons
are checked against their minimum again, and the shipping fee is worked out over the remaining
lines. What was paid beyond the new total goes back: a Toss card / transfer / easy-pay payment is
partially cancelled at Toss *before* anything changes here, any other payment is recorded as a
refund the admin makes by hand. When every line ends up cancelled the order is closed through the
shared cancel path (stock, coupons and points come back once).

Only some units of a line can change too: the line is split first (shop/order_line_split.py) and
the split-off copy goes through the same change."""

import copy
import hashlib
import logging
from dataclasses import dataclass, field, replace

from django.db.models import Sum

from django.db import transaction

from gnu_jango.shop.models import ShopCouponLog, ShopOrder, ShopPersonalPay, ShopReturnRequest
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.order_line_split import split_order_lines
from gnu_jango.shop.order_flow import (
    StatusChange,
    canonical_status,
    paid_amount,
    transition_error,
)
from gnu_jango.shop.order_statuses import (
    INACTIVE_LINE_STATUSES,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_ORDERED,
    STATUS_PAID,
    STATUS_READY,
    STATUS_RETURNED,
    STATUS_SHIPPING,
    STATUS_SOLD_OUT,
)

logger = logging.getLogger(__name__)

LINE_TARGETS = (STATUS_CANCELLED, STATUS_SOLD_OUT, STATUS_RETURNED)
# 취소 and 품절 are for goods not sent yet; goods that left the shop come back as 반품
LINE_SOURCES = {
    STATUS_CANCELLED: {STATUS_ORDERED, STATUS_PAID, STATUS_READY},
    STATUS_SOLD_OUT: {STATUS_ORDERED, STATUS_PAID, STATUS_READY},
    STATUS_RETURNED: {STATUS_SHIPPING, STATUS_COMPLETED},
}
REFUND_NONE = "none"
REFUND_TOSS = "toss"
REFUND_NICEPAY = "nicepay"
REFUND_MANUAL = "manual"


def line_amount(item):
    """youngcart: io_price × qty for a supplement line, (ct_price + io_price) × qty otherwise."""
    unit = int(item.io_price or 0) if int(item.io_type or 0) == 1 else int(item.ct_price or 0) + int(item.io_price or 0)
    return max(0, unit) * int(item.ct_qty or 0)


def line_label(item):
    option = str(item.ct_option or "").strip()
    return f"{item.it_name} / {option}" if option and option != item.it_name else str(item.it_name)


@dataclass(frozen=True)
class LineChangePlan:
    """What a line change does to the order (also shown to the admin before applying it)."""

    target: str
    lines: tuple
    all_inactive: bool
    order_status: str  # what the order becomes when every line is cancelled-type
    cart_price: int  # goods still ordered
    cancel_price: int  # goods cancelled, returned or sold out
    cart_coupon: int
    od_coupon: int
    send_coupon: int
    send_cost: int
    send_cost2: int
    total: int  # what the order costs now
    paid: int
    refunded: int  # refunded before this change
    refund: int  # cash going back now
    point_excess: int  # overpaid with points: adjusted by hand (youngcart keeps od_receipt_point)
    misu: int
    method: str
    note: str
    # the part of ``refund`` Toss gives back on the order's own payment (od_tno); the rest is a
    # manual refund (a non-Toss payment, or personal pay receipts credited to the order)
    pg_refund: int = 0
    full_pg_cancel: bool = False  # every line cancelled, nothing refunded yet: cancel the payment whole
    tax: dict = field(default_factory=dict)
    # the coupon logs whose discount changes: {log pk: new cp_price}
    coupon_log_prices: dict = field(default_factory=dict)
    # partial quantities: the lines split so only some of their units change (LineSplit)
    splits: tuple = ()
    # the return shipping fee kept back from ``refund`` (a customer's 단순변심 return, shop/returns.py)
    return_fee: int = 0

    @property
    def manual_refund(self):
        """What the admin pays back by hand."""
        return max(0, self.refund - self.pg_refund)

    @property
    def idempotency_key(self):
        """One refund: the same lines, target and amount never refund twice at Toss. A split-off
        line is named by the line it came from and its quantities: its own pk is new on every try
        (a refused try rolls the split back), so a retry after a lost Toss answer keeps the key."""
        splits = {split.new_pk: split for split in self.splits}
        line_ids = ",".join(
            f"s{split.original_pk}:{split.before}:{split.moved}" if (split := splits.get(item.pk)) else str(item.pk)
            for item in sorted(self.lines, key=lambda item: item.pk)
        )
        digest = hashlib.sha256(
            f"{self.target}|{line_ids}|{self.pg_refund}|{self.refund}|{self.refunded}".encode()
        ).hexdigest()[:24]
        return f"admin-part-{self.lines[0].order_id}-{digest}"


def kept_return_fees(order):
    """The return shipping fees the order's completed customer returns kept back (shop/returns.py).
    A fee kept while lines remained is charged as 추가배송비 (od_send_cost2), so it is part of the
    total until the last line goes; then nothing ships and the rest of the payment goes back, less
    these fees."""
    return int(
        ShopReturnRequest.objects.filter(
            order_id=order.pk, kind=ShopReturnRequest.KIND_RETURN, status=ShopReturnRequest.STATUS_COMPLETED
        ).aggregate(total=Sum("return_fee"))["total"]
        or 0
    )


def personal_pay_receipts(order):
    """What personal pay requests linked to the order paid into it (youngcart personalpayformupdate.php
    adds them to od_receipt_price). They were paid with their own transaction, never the order's."""
    return int(ShopPersonalPay.objects.filter(order_id=order.pk).aggregate(total=Sum("pp_receipt_price"))["total"] or 0)


def _refund_method(order, refund, *, paid, refunded, all_inactive):
    """(method, history note, Toss part, full cancel) of a refund of ``refund`` won.

    Through Toss goes at most what the order's own Toss payment still holds: personal pay
    receipts credited to the order were paid on other transactions, so that part is refunded by
    hand ("환불 필요 (수동, 개인결제분)")."""
    from gnu_jango.api.shop_nicepay import order_paid_through_nicepay
    from gnu_jango.api.shop_payments import order_paid_through_toss, settle_case_is_bank, settle_case_is_vbank

    if refund <= 0:
        return REFUND_NONE, "", 0, False
    if order_paid_through_toss(order) or order_paid_through_nicepay(order):
        own_payment = max(0, paid - personal_pay_receipts(order))
        pg_refund = min(refund, max(0, own_payment - refunded))
        manual = refund - pg_refund
        full = all_inactive and refunded == 0 and pg_refund == own_payment
        note = ""
        if pg_refund:
            note += f" PG {order.od_settle_case or '결제'} {'승인취소' if full else '부분취소'} {pg_refund:,}원"
        if manual:
            note += f" 환불 필요 (수동, 개인결제분) {manual:,}원"
        method = REFUND_NICEPAY if order_paid_through_nicepay(order) else REFUND_TOSS
        return (method if pg_refund else REFUND_MANUAL), note, pg_refund, full and pg_refund > 0
    if settle_case_is_bank(order.od_settle_case):
        return REFUND_MANUAL, f" 무통장 환불 필요 (수동) {refund:,}원", 0, False
    if settle_case_is_vbank(order.od_settle_case):
        return REFUND_MANUAL, f" 가상계좌 환불 필요 (수동) {refund:,}원", 0, False
    return REFUND_MANUAL, f" PG({order.od_pg or '-'}) 부분취소 필요 (수동) {refund:,}원", 0, False


def _capped_log_prices(logs, discounts, cap):
    """{log pk: discount} for ``logs``, the discounts taken in order until ``cap`` is used up."""
    prices = {}
    left = max(0, cap)
    for log, discount in zip(logs, discounts):
        prices[log.pk] = min(max(0, discount), left)
        left -= prices[log.pk]
    return prices


def _order_coupons(order, logs, cart_price, cart_coupon, send_cost):
    """get_order_info: the order coupon (cp_method 2) on goods after product coupons, and the
    shipping coupon (3) on the shipping fee, each only while its minimum still holds. Without a
    coupon record the stored discount is kept (capped by what it discounts).

    Returns (od_coupon, od_send_coupon, {coupon log pk: its new discount}): the logs are kept in
    step with the order (order_coupons.order_coupon_totals reads them when nothing is stored), so a
    dropped coupon cannot come back through its log."""
    from gnu_jango.api.shop_coupons import coupon_discount

    base = max(0, cart_price - cart_coupon)
    log_prices = {}
    order_logs = [log for log in logs if log.coupon_id and log.coupon and log.coupon.cp_method == 2]
    if order_logs:
        discounts = [coupon_discount(log.coupon, base) for log in order_logs]
        log_prices.update(_capped_log_prices(order_logs, discounts, base))
        od_coupon = sum(log_prices[log.pk] for log in order_logs)
    else:
        od_coupon = min(max(0, int(order.od_coupon or 0)), base)
    send_logs = [log for log in logs if log.coupon_id and log.coupon and log.coupon.cp_method == 3]
    if send_logs:
        discounts = [coupon_discount(log.coupon, send_cost, minimum_base=base - od_coupon) for log in send_logs]
        log_prices.update(_capped_log_prices(send_logs, discounts, send_cost))
        send_coupon = sum(log_prices[log.pk] for log in send_logs)
    else:
        send_coupon = min(max(0, int(order.od_send_coupon or 0)), send_cost)
    return od_coupon, send_coupon, log_prices


def _split_product_coupons(logs, items, splits, status_of):
    """The product coupon logs again for lines that kept only some units: a coupon on a split line
    stays on it (the line keeps the lower pk, so it stays its product's first line) but is judged
    again on what is left of the product, like an order coupon's minimum. Unchanged logs are
    returned as they are; changed ones as copies with the new cp_price."""
    from gnu_jango.api.shop_coupons import coupon_discount
    from gnu_jango.shop.order_coupons import cart_coupon_lines

    split_lines = {split.original_pk for split in splits}
    placed = cart_coupon_lines(logs, items)
    adjusted = []
    for log in logs:
        line = placed.get(log.pk)
        if line is None or line.pk not in split_lines:
            adjusted.append(log)
            continue
        base = sum(
            line_amount(item)
            for item in items
            if str(item.it_id) == str(line.it_id) and str(status_of(item) or "") not in INACTIVE_LINE_STATUSES
        )
        price = min(max(0, int(log.cp_price or 0)), coupon_discount(log.coupon, base))
        if price != int(log.cp_price or 0):
            log = copy.copy(log)
            log.cp_price = price
        adjusted.append(log)
    return adjusted


def _tax_amounts(order, active, coupon_by_line, *, send_cost, send_cost2, od_coupon, send_coupon, payable):
    from gnu_jango.shop.taxes import calculate_order_tax_amounts

    rows = [
        {
            "ct_qty": item.ct_qty,
            "ct_price": item.ct_price,
            "io_type": item.io_type,
            "io_price": item.io_price,
            "ct_notax": item.ct_notax,
            "cp_price": coupon_by_line.get(item.pk, 0),
        }
        for item in active
    ]
    amounts = calculate_order_tax_amounts(
        rows,
        send_cost=send_cost,
        send_cost2=send_cost2,
        order_coupon=od_coupon,
        send_coupon=send_coupon,
        receipt_point=int(order.od_receipt_point or 0),
        payable_amount=payable,
        mixed_tax_enabled=bool(order.od_tax_flag),
    )
    return {key: amounts[key] for key in ("od_tax_mny", "od_vat_mny", "od_free_mny")}


def _selection_error(order, selected, target):
    from gnu_jango.api.shop_payments import settle_case_is_bank

    status = canonical_status(order.od_status)
    if status in INACTIVE_LINE_STATUSES:
        return f"{status}된 주문은 상품 상태를 바꿀 수 없습니다."
    if target not in LINE_TARGETS:
        return "변경할 상태가 올바르지 않습니다."
    if not selected:
        return "처리할 상품을 하나 이상 선택하세요."
    if status == STATUS_ORDERED and not settle_case_is_bank(order.od_settle_case):
        # the PG (or the issued virtual account) still expects the original amount
        return "결제를 기다리는 PG·가상계좌 주문은 상품별로 바꿀 수 없습니다. 주문 전체를 취소하세요."
    for item in selected:
        current = canonical_status(item.ct_status)
        if current in INACTIVE_LINE_STATUSES:
            return f"이미 '{current}' 처리된 상품이 있습니다: {line_label(item)}"
        if current not in LINE_SOURCES[target]:
            hint = "배송·완료된 상품은 반품으로 처리하세요." if target != STATUS_RETURNED else "배송 전 상품은 취소 또는 품절로 처리하세요."
            return f"'{current}' 상태의 상품은 {target} 처리할 수 없습니다 ({line_label(item)}). {hint}"
    return ""


def plan_line_change(order, line_ids, target, *, splits=(), return_fee=0):
    """Work out what changing the lines ``line_ids`` of ``order`` to ``target`` does; returns
    (plan, "") or (None, the reason in Korean). Nothing is saved. ``splits`` names the lines
    split_order_lines split already (their product coupons are judged again). ``return_fee`` (반품
    only) is a return shipping fee the customer bears: it comes off the refund, never more than
    the refund."""
    from gnu_jango.shop.shipping import items_shipping_cost

    items = list(order.items.select_related("product").order_by("pk"))
    wanted = set()
    for value in line_ids:
        try:
            wanted.add(int(value))
        except (TypeError, ValueError):
            return None, "처리할 상품을 다시 선택하세요."
    selected = [item for item in items if item.pk in wanted]
    if len(selected) != len(wanted):
        return None, "이 주문의 상품이 아닌 줄이 있습니다. 화면을 새로 고친 뒤 다시 선택하세요."
    error = _selection_error(order, selected, target)
    if error:
        return None, error

    chosen = {item.pk for item in selected}

    def status_of(item):
        return target if item.pk in chosen else item.ct_status

    active = [item for item in items if str(status_of(item) or "") not in INACTIVE_LINE_STATUSES]
    inactive = [item for item in items if item not in active]
    all_inactive = not active
    cart_price = sum(line_amount(item) for item in active)
    cancel_price = sum(line_amount(item) for item in inactive)
    logs = list(order.coupon_logs.select_related("coupon"))
    stored_prices = {log.pk: int(log.cp_price or 0) for log in logs}
    if splits:
        logs = _split_product_coupons(logs, items, splits, status_of)
    # the same product coupon rule as order_misu and the order page (shop/order_coupons.py)
    coupons = order_coupon_totals(order, logs, items=items, status_of=status_of)
    cart_coupon = min(cart_price, coupons.cart)
    coupon_by_line = coupons.cart_by_line
    send_cost = (
        items_shipping_cost(
            {"it_id": item.it_id, "line_total": line_amount(item), "ct_qty": item.ct_qty, "ct_send_cost": item.ct_send_cost}
            for item in active
        )
        if active
        else 0
    )
    send_cost2 = int(order.od_send_cost2 or 0) if active else 0
    od_coupon, send_coupon, coupon_log_prices = (
        _order_coupons(order, logs, cart_price, cart_coupon, send_cost) if active else (0, 0, {})
    )
    total = max(0, cart_price + send_cost + send_cost2 - cart_coupon - od_coupon - send_coupon)

    paid = paid_amount(order)
    refunded = max(0, int(order.od_refund_price or 0))
    point = max(0, int(order.od_receipt_point or 0))
    refundable = max(0, paid - refunded)
    if all_inactive:
        # the whole rest goes back (less the return shipping fees earlier returns kept); the
        # points used go back to the member with the order
        refund, point_excess = max(0, refundable - kept_return_fees(order)), 0
    else:
        overpaid = paid + point - refunded - total
        refund = max(0, min(overpaid, refundable))
        point_excess = max(0, overpaid - refund)
    return_fee = min(max(0, int(return_fee or 0)), refund) if target == STATUS_RETURNED else 0
    if return_fee:
        refund -= return_fee
        if not all_inactive:
            # charged as 추가배송비 while lines remain, so a later change does not pay it back
            send_cost2 += return_fee
            total += return_fee
    misu = 0 if all_inactive else max(0, total - (paid + point - refunded - refund))
    method, note, pg_refund, full_pg_cancel = _refund_method(
        order, refund, paid=paid, refunded=refunded, all_inactive=all_inactive
    )
    if return_fee:
        note += f" 반품 배송비 {return_fee:,}원 차감"
    tax = (
        {"od_tax_mny": 0, "od_vat_mny": 0, "od_free_mny": 0}
        if all_inactive
        else _tax_amounts(
            order,
            active,
            coupon_by_line,
            send_cost=send_cost,
            send_cost2=send_cost2,
            od_coupon=od_coupon,
            send_coupon=send_coupon,
            payable=max(0, total - point),
        )
    )
    returned = any(status_of(item) == STATUS_RETURNED for item in items)
    return (
        LineChangePlan(
            target=target,
            lines=tuple(selected),
            all_inactive=all_inactive,
            order_status=STATUS_RETURNED if returned else STATUS_CANCELLED,
            cart_price=cart_price,
            cancel_price=cancel_price,
            cart_coupon=cart_coupon,
            od_coupon=od_coupon,
            send_coupon=send_coupon,
            send_cost=send_cost,
            send_cost2=send_cost2,
            total=total,
            paid=paid,
            refunded=refunded,
            refund=refund,
            point_excess=point_excess,
            misu=misu,
            method=method,
            note=note,
            pg_refund=pg_refund,
            full_pg_cancel=full_pg_cancel,
            tax=tax,
            coupon_log_prices={
                log.pk: price
                for log in logs
                if (price := coupon_log_prices.get(log.pk, int(log.cp_price or 0))) != stored_prices[log.pk]
            },
            splits=tuple(splits),
            return_fee=return_fee,
        ),
        "",
    )


def change_order_lines(
    order, line_ids, target, reason="", *, actor="", quantities=None, expected=None, return_fee=0
):
    """Change the lines ``line_ids`` of ``order`` to 취소, 반품 or 품절 from the admin.

    ``quantities`` ({line pk: units}) changes only that many units of a line (the line is split);
    ``expected`` ({line pk: the quantity the admin saw}) refuses a stale or resubmitted form, so a
    double submit cannot split a line twice.

    Like admin_cancel_order the order row stays locked from the checks through the PG refund to the
    local change, in a durable transaction: once Toss has refunded, the change commits on its own.
    A second submit of the same change waits for the lock, then finds the lines changed already and
    refunds nothing."""
    with transaction.atomic(durable=True):
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            return StatusChange(False, "주문을 찾을 수 없습니다.")
        result = change_locked_order_lines(
            locked, line_ids, target, reason, actor=actor, quantities=quantities, expected=expected, return_fee=return_fee
        )
        _close_settled_return_requests(locked, result, actor)
        return result


def preview_line_change(order, line_ids, target, *, quantities=None, expected=None, return_fee=0):
    """plan_line_change for the admin preview, partial quantities included. Nothing is kept: a
    split is made in a transaction that is rolled back."""
    if not quantities and not expected:
        return plan_line_change(order, line_ids, target, return_fee=return_fee)
    with transaction.atomic():
        try:
            return _split_and_plan(order, line_ids, target, quantities, expected, return_fee), ""
        except _ChangeRefused as exc:
            return None, str(exc)
        finally:
            transaction.set_rollback(True)


def admin_return_order(order, reason="", *, actor=""):
    """Return (반품) a whole 배송 or 완료 order: every active line becomes 반품 and the rest of
    the payment goes back."""
    with transaction.atomic(durable=True):
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            return StatusChange(False, "주문을 찾을 수 없습니다.")
        error = transition_error(locked, STATUS_RETURNED)
        if error:
            return StatusChange(False, error)
        result = change_locked_order_lines(locked, active_line_ids(locked), STATUS_RETURNED, reason, actor=actor)
        _close_settled_return_requests(locked, result, actor)
        return result


def _close_settled_return_requests(order, result, actor):
    """A customer's return / exchange request whose lines the admin just settled on the order is
    closed as well (shop/returns.py). Completing a request calls change_locked_order_lines itself
    and closes its own request, so only these two admin entry points do this."""
    if not result:
        return
    from gnu_jango.shop.returns import close_settled_requests

    try:
        with transaction.atomic():
            close_settled_requests(order, actor=actor)
    except Exception:  # noqa: BLE001 - the line change (and any refund) stands; the request can be closed by hand
        logger.exception("order %s: could not close the return requests of the settled lines", order.od_id)


def active_line_ids(order):
    return list(order.items.exclude(ct_status__in=INACTIVE_LINE_STATUSES).values_list("pk", flat=True))


class _ChangeRefused(Exception):
    """The change cannot go ahead; the savepoint around the split and the refund is rolled back."""


def _split_and_plan(order, line_ids, target, quantities, expected, return_fee=0):
    splits = ()
    if quantities or expected:
        line_ids, splits, error = split_order_lines(order, line_ids, quantities or {}, expected)
        if error:
            raise _ChangeRefused(error)
    plan, error = plan_line_change(order, line_ids, target, splits=splits, return_fee=return_fee)
    if error:
        raise _ChangeRefused(error)
    return plan


def refund_tax_free(order, plan):
    """The tax-free part of ``plan``'s refund: what the order's 면세 amount (od_free_mny) drops
    by, held to the PG refund (youngcart orderpartcancel.inc.php free_mny). 0 for an order not
    placed under 복합과세 결제."""
    if not int(order.od_tax_flag or 0):
        return 0
    dropped = max(0, int(order.od_free_mny or 0) - int(plan.tax.get("od_free_mny", 0) or 0))
    return min(dropped, max(0, int(plan.pg_refund or 0)))


def _refund_at_pg(order, plan, reason):
    """Refund the Toss/NICEPAY part of ``plan`` before anything is applied."""
    from gnu_jango.api.shop_nicepay import (
        nicepay_api_cancel_payment,
        nicepay_api_partial_cancel_payment,
    )
    from gnu_jango.api.shop_payments import (
        PaymentCancelError,
        toss_api_cancel_payment,
        toss_api_partial_cancel_payment,
    )

    cancel_reason = reason or f"쇼핑몰 운영자 {plan.target} 처리"
    provider = "nicepay" if plan.method == REFUND_NICEPAY else "toss"
    try:
        if provider == "nicepay":
            if plan.full_pg_cancel:
                answer = nicepay_api_cancel_payment(order, cancel_reason)
            else:
                answer = nicepay_api_partial_cancel_payment(
                    order,
                    plan.pg_refund,
                    cancel_reason,
                    idempotency_key=plan.idempotency_key,
                    tax_free_amount=refund_tax_free(order, plan),
                )
        elif plan.full_pg_cancel:
            answer = toss_api_cancel_payment(order, cancel_reason)
        else:
            answer = toss_api_partial_cancel_payment(
                order,
                plan.pg_refund,
                cancel_reason,
                idempotency_key=plan.idempotency_key,
                tax_free_amount=refund_tax_free(order, plan),
            )
    except PaymentCancelError as exc:
        raise _ChangeRefused(f"결제 환불에 실패해 아무것도 바꾸지 않았습니다. {exc}") from exc
    if answer.get("already_canceled"):
        label = "NICEPAY" if provider == "nicepay" else "토스페이먼츠"
        plan = replace(plan, note=f"{plan.note} ({label}에서 이미 취소된 결제 - 환불 기록만 반영, 확인 필요)")
    _record_pg_answer(order, plan, answer, provider=provider)
    return plan


def change_locked_order_lines(
    order, line_ids, target, reason="", *, actor="", quantities=None, expected=None, return_fee=0
):
    """change_order_lines for an order the caller has locked (select_for_update) already."""
    pg_refunded = False
    try:
        # a savepoint: a split line is put back when the change is refused or Toss refuses the refund
        with transaction.atomic():
            plan = _split_and_plan(order, line_ids, target, quantities, expected, return_fee)
            if plan.method in {REFUND_TOSS, REFUND_NICEPAY}:
                plan = _refund_at_pg(order, plan, reason)
                pg_refunded = True
    except _ChangeRefused as exc:
        return StatusChange(False, str(exc))
    try:
        # a savepoint: should the local change fail after Toss refunded, the refund is still recorded
        with transaction.atomic():
            _apply_plan(order, plan, reason, actor)
    except Exception:
        if not pg_refunded:
            raise
        logger.exception("order %s: Toss refunded %s but the line change failed", order.od_id, plan.refund)
        _record_refund_only(order, plan, actor)
        return StatusChange(
            False,
            f"PG에서 {plan.pg_refund:,}원을 환불했지만 상품 상태를 바꾸지 못했습니다. 환불은 주문에 기록했으니 주문을 확인해 주세요.",
        )
    return StatusChange(
        True,
        _success_message(order, plan),
        manual_refund=plan.manual_refund > 0,
        refund=plan.refund,
        return_fee=plan.return_fee,
    )


def _record_pg_answer(order, plan, answer, *, provider="toss"):
    from gnu_jango.api.shop_payments import record_payment_raw_log

    try:
        with transaction.atomic():
            record_payment_raw_log(
                order,
                order.od_id,
                provider,
                plan.idempotency_key.rsplit("-", 1)[-1][:12],
                {f"{provider}_partial_cancel": answer, "cancelAmount": plan.pg_refund},
                prefix="npc" if provider == "nicepay" else "tpc",
            )
    except Exception:  # noqa: BLE001 - the PG refunded already; the change must still be applied
        logger.exception("order %s: could not record the %s partial cancel response", order.od_id, provider)


def _record_refund_only(order, plan, actor):
    from gnu_jango.shop.inventory import append_order_history, order_history_line

    locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
    locked.od_refund_price = plan.refunded + plan.pg_refund
    locked.od_mod_history = append_order_history(
        locked.od_mod_history,
        order_history_line(f"PG 부분취소 {plan.pg_refund:,}원 완료 - 상품 {plan.target} 처리 실패, 확인 필요", actor),
    )
    locked.save(update_fields=["od_refund_price", "od_mod_history"])


def _history_lines(plan, reason, actor):
    from gnu_jango.shop.inventory import order_history_line

    lines = [
        order_history_line(
            f"{split.label} 수량 {split.before}→{split.kept} ({split.moved}개 분리)"
            + (f" 구매포인트 {split.point_taken:,}점 회수" if split.point_taken else ""),
            actor,
        )
        for split in plan.splits
    ]
    moved = {split.new_pk: split.moved for split in plan.splits}
    lines += [
        order_history_line(
            f"{line_label(item)}{f' {moved[item.pk]}개' if item.pk in moved else ''} {item.ct_status}→{plan.target}",
            actor,
        )
        for item in plan.lines
    ]
    note = plan.note
    if plan.point_excess:
        note += f" 포인트 {plan.point_excess:,}점 수동 조정 필요"
    suffix = f" - {reason}" if reason else ""
    if plan.all_inactive:
        lines.append(order_history_line(f"주문{plan.order_status} 처리{note}{suffix}", actor))
    else:
        lines.append(order_history_line(f"상품 {len(plan.lines)}건 {plan.target} 처리{note}{suffix}", actor))
    return lines


def _apply_plan(order, plan, reason, actor):
    from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits
    from gnu_jango.shop.cash_receipts import partial_refund_note
    from gnu_jango.shop.inventory import append_order_history, order_history_line, restore_line_stock
    from gnu_jango.shop.order_points import take_back_order_points
    from gnu_jango.shop.product_counters import recount_product_sales

    history = _history_lines(plan, reason, actor)
    if not plan.all_inactive and (receipt_note := partial_refund_note(order, plan.refund)):
        history.append(order_history_line(receipt_note.strip(), actor))
    line_ids = [item.pk for item in plan.lines]
    for item in order.items.select_for_update().filter(pk__in=line_ids).order_by("pk"):
        restore_line_stock(item)
        item.stock_adjusted = False
        item.ct_status = plan.target
        item.save(update_fields=["stock_adjusted", "ct_status"])  # save() keeps ct_complete_time in step

    if plan.all_inactive:
        cancel_order_and_refund_benefits(
            order,
            "",
            refund_price=plan.refunded + plan.refund,
            history="\n".join(history),
            status=plan.order_status,
        )
    else:
        # youngcart orderformcartupdate.php: a paid purchase point of a line that leaves 완료 goes back
        take_back_order_points(order)
        for log_pk, price in plan.coupon_log_prices.items():
            coupon_log = ShopCouponLog.objects.filter(pk=log_pk, order_id=order.pk).first()
            if coupon_log is not None:
                coupon_log.cp_price = price
                coupon_log._change_reason = "order line change"[:100]
                coupon_log.save(update_fields=["cp_price"])
        locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
        locked.od_cart_price = plan.cart_price + plan.cancel_price
        locked.od_cancel_price = plan.cancel_price
        locked.od_send_cost = plan.send_cost
        locked.od_send_cost2 = plan.send_cost2  # a kept return shipping fee is added here
        locked.od_coupon = plan.od_coupon
        locked.od_send_coupon = plan.send_coupon
        locked.od_refund_price = plan.refunded + plan.refund
        locked.od_misu = plan.misu
        for key, value in plan.tax.items():
            setattr(locked, key, value)
        for line in history:
            locked.od_mod_history = append_order_history(locked.od_mod_history, line)
        locked.save(
            update_fields=[
                "od_cart_price",
                "od_cancel_price",
                "od_send_cost",
                "od_send_cost2",
                "od_coupon",
                "od_send_coupon",
                "od_refund_price",
                "od_misu",
                "od_mod_history",
                *plan.tax.keys(),
            ]
        )
    recount_product_sales(item.product_id for item in plan.lines)


def _success_message(order, plan):
    count = len(plan.lines)
    if plan.all_inactive:
        head = f"주문 {order.od_id}의 모든 상품이 {plan.target} 처리되어 주문이 '{plan.order_status}' 상태가 되었습니다."
    else:
        head = f"주문 {order.od_id}의 상품 {count}건을 {plan.target} 처리했습니다."
    if plan.method in {REFUND_TOSS, REFUND_NICEPAY}:
        label = "NICEPAY" if plan.method == REFUND_NICEPAY else "토스페이먼츠"
        tail = f" {plan.pg_refund:,}원을 PG에서 환불(승인취소)했습니다."
        if plan.manual_refund:
            tail += f" 개인결제로 받은 {plan.manual_refund:,}원은 직접 환불해야 합니다."
        if "이미 취소된 결제" in plan.note:
            tail += f" {label}에서 이미 취소된 결제여서 환불 기록만 반영했습니다. 상점관리자에서 확인하세요."
    elif plan.method == REFUND_MANUAL:
        tail = f" {plan.refund:,}원은 직접 환불해야 합니다.{plan.note}"
    elif plan.misu:
        tail = f" 남은 결제할 금액은 {plan.misu:,}원입니다."
    else:
        tail = ""
    if plan.point_excess:
        tail += f" 포인트로 결제된 {plan.point_excess:,}점은 회원 포인트에서 직접 조정하세요."
    return head + tail
