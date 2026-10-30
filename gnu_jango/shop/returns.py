"""Customer return (반품) and exchange (교환) requests of delivered order lines.

The customer - the member who placed the order, or for a guest order whoever holds its uid - asks
for lines in 배송 or 완료, with a reason (단순변심, 상품불량, 오배송, 기타) and the units of each
line. A line is in at most one open request (ShopReturnRequestLine.is_open, a partial unique
constraint). The request then moves requested → approved → completed, or ends rejected (by the
shop, with a reason the customer sees) or withdrawn (by the customer while it still waits).

The request window (de_return_request_days, 7 by default) counts from ``ct_complete_time``: the
moment the line was marked 완료 (배송완료) is the closest record of the customer receiving the
goods, which is when the 청약철회 period of 전자상거래법 제17조 starts. A line still in 배송 has
no such stamp - it is in transit or has only just arrived - so its clock has not started and it can
always be asked for. A 완료 line written before ct_complete_time existed falls back to the
shipment (od_invoice_time) and then the order time: the earliest it can have arrived, so the
window is never longer than it should be.

Completing a return goes through the admin's own line change (order_lines.change_locked_order_lines):
the lines become 반품, their stock goes back, the order is priced again (shipping, coupons) and what
was overpaid is refunded at Toss / NICEPAY or recorded as a manual refund, purchase points and
coupons following the same rules. A 단순변심 return keeps back the return shipping fee
(de_return_shipping_fee). Completing an exchange records the re-shipment (courier and invoice); the
lines keep their status.

Every status change mails the customer and, for a member, lands in the notification inbox
(shop/notifications.py, notifications/outbox.py).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from gnu_jango.shop.delivery import delivery_inquiry
from gnu_jango.shop.delivery_import import MAX_INVOICE_LENGTH, normalize_company
from gnu_jango.shop.inventory import append_order_history, order_history_line
from gnu_jango.shop.models import ShopOrder, ShopReturnRequest, ShopReturnRequestLine
from gnu_jango.shop.order_flow import StatusChange, canonical_status
from gnu_jango.shop.order_lines import change_locked_order_lines, line_amount, line_label, preview_line_change
from gnu_jango.shop.order_statuses import (
    INACTIVE_LINE_STATUSES,
    STATUS_COMPLETED,
    STATUS_RETURNED,
    STATUS_SHIPPING,
)
from gnu_jango.shop.shop_options import shop_options

logger = logging.getLogger(__name__)

ELIGIBLE_LINE_STATUSES = frozenset({STATUS_SHIPPING, STATUS_COMPLETED})
DETAIL_MAX_LENGTH = 1000
REJECT_REASON_MAX_LENGTH = ShopReturnRequest._meta.get_field("reject_reason").max_length
MAX_REQUEST_LINES = 100

KIND_LABELS = dict(ShopReturnRequest.KINDS)
STATUS_LABELS = dict(ShopReturnRequest.STATUSES)
REASON_LABELS = dict(ShopReturnRequest.REASONS)
LEGACY_EMPTY_TIME = "0000-00-00 00:00:00"


class ReturnRequestError(Exception):
    """A customer request the shop cannot take; ``message`` is the English API message
    (nextjs/src/lib/api-messages.ts turns it into Korean)."""

    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ReturnSettings:
    enabled: bool
    days: int
    fee: int


def return_settings():
    values = shop_options("de_return_request_use", "de_return_request_days", "de_return_shipping_fee")
    return ReturnSettings(
        enabled=bool(values["de_return_request_use"]),
        days=int(values["de_return_request_days"]),
        fee=int(values["de_return_shipping_fee"]),
    )


def _stored_time(value):
    """od_invoice_time is stored text ("2026-10-30 14:00:00"); None when empty or unreadable."""
    text = str(value or "").strip()
    if not text or text == LEGACY_EMPTY_TIME:
        return None
    try:
        parsed = parse_datetime(text.replace(" ", "T", 1))
    except ValueError:
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def window_start(item, order):
    """When the request window of ``item`` starts; None while it has not (a 배송 line)."""
    if canonical_status(item.ct_status) != STATUS_COMPLETED:
        return None
    return item.ct_complete_time or _stored_time(order.od_invoice_time) or order.od_datetime


def request_deadline(item, order, days):
    start = window_start(item, order)
    return start + timedelta(days=days) if start else None


def order_block_reason(order, settings):
    """Why no line of ``order`` can be asked for (Korean, shown to the customer); "" when some can."""
    if not settings.enabled:
        return "반품·교환 신청을 받지 않습니다. 고객센터로 문의해 주세요."
    status = canonical_status(order.od_status)
    if status in INACTIVE_LINE_STATUSES:
        return f"{status}된 주문은 반품·교환을 신청할 수 없습니다."
    return ""


def line_block_reason(item, order, settings, *, now, open_line_ids):
    """Why ``item`` cannot be asked for (Korean, shown to the customer); "" when it can."""
    status = canonical_status(item.ct_status)
    if item.pk in open_line_ids:
        return "반품·교환을 신청해 처리 중인 상품입니다."
    if status in INACTIVE_LINE_STATUSES:
        return f"{status}된 상품입니다."
    if status not in ELIGIBLE_LINE_STATUSES:
        return "배송이 시작된 상품만 반품·교환을 신청할 수 있습니다."
    deadline = request_deadline(item, order, settings.days)
    if deadline is not None and now > deadline:
        return f"배송완료 후 {settings.days}일이 지나 신청 기간이 끝났습니다."
    return ""


def open_requests_by_line(order):
    """{order line pk: the open request holding it} of ``order``."""
    return dict(
        ShopReturnRequestLine.objects.filter(item__order_id=order.pk, is_open=True).values_list("item_id", "request_id")
    )


def default_return_fee(request):
    """The return shipping fee a request keeps back: de_return_shipping_fee on a 단순변심 return,
    nothing for a defect, a wrong item or an exchange (the shop pays those)."""
    if request.kind != ShopReturnRequest.KIND_RETURN or request.reason != ShopReturnRequest.REASON_CHANGE_OF_MIND:
        return 0
    return return_settings().fee


def latest_request(order):
    """The newest request of ``order`` the customer did not withdraw, or None (the order list badge).
    Uses the order's prefetched ``return_requests`` when the list view loaded them."""
    prefetched = getattr(order, "_prefetched_objects_cache", {}).get("return_requests")
    if prefetched is not None:
        # ShopReturnRequest.Meta.ordering is newest first
        return next((request for request in prefetched if request.status != ShopReturnRequest.STATUS_WITHDRAWN), None)
    return (
        ShopReturnRequest.objects.filter(order_id=order.pk)
        .exclude(status=ShopReturnRequest.STATUS_WITHDRAWN)
        .order_by("-created_at", "-pk")
        .only("kind", "status")
        .first()
    )


# --- customer payloads -------------------------------------------------------------------------


def _iso(value):
    return timezone.localtime(value).isoformat() if value else ""


def request_payload(request):
    lines = list(request.lines.select_related("item").order_by("pk"))
    company, invoice = request.exchange_delivery_company, request.exchange_invoice
    return {
        "id": request.pk,
        "kind": request.kind,
        "kind_label": KIND_LABELS.get(request.kind, request.kind),
        "status": request.status,
        "status_label": STATUS_LABELS.get(request.status, request.status),
        "reason": request.reason,
        "reason_label": REASON_LABELS.get(request.reason, request.reason),
        "detail": request.detail,
        "reject_reason": request.reject_reason,
        "return_fee": request.return_fee,
        "refund_amount": request.refund_amount,
        "exchange_delivery_company": company,
        "exchange_invoice": invoice,
        "exchange_inquiry_url": delivery_inquiry(company, invoice)["url"] if company and invoice else "",
        "can_withdraw": request.status == ShopReturnRequest.STATUS_REQUESTED,
        "created_at": _iso(request.created_at),
        "approved_at": _iso(request.approved_at),
        "closed_at": _iso(request.closed_at),
        "lines": [
            {
                "line_id": line.item_id,
                "ct_id": line.item.ct_id if line.item else "",
                "it_name": line.it_name,
                "ct_option": line.ct_option,
                "qty": line.qty,
                "amount": line.amount,
            }
            for line in lines
        ],
    }


def customer_payload(order):
    """What the order page needs to offer and show returns and exchanges."""
    settings = return_settings()
    now = timezone.now()
    held = open_requests_by_line(order)
    order_reason = order_block_reason(order, settings)
    lines = []
    for item in order.items.order_by("pk"):
        deadline = request_deadline(item, order, settings.days)
        reason = order_reason or line_block_reason(item, order, settings, now=now, open_line_ids=held)
        lines.append(
            {
                "line_id": item.pk,
                "ct_id": item.ct_id,
                "it_id": item.it_id,
                "it_name": item.it_name,
                "ct_option": item.ct_option,
                "ct_qty": item.ct_qty,
                "ct_status": item.ct_status,
                "line_total": line_amount(item),
                "eligible": not reason,
                "block_reason": reason,
                # "" while the window has not started (a 배송 line)
                "deadline": _iso(deadline),
                "open_request_id": held.get(item.pk),
            }
        )
    requests = [request_payload(request) for request in order.return_requests.order_by("-created_at", "-pk")]
    return {
        "enabled": settings.enabled,
        "request_days": settings.days,
        "return_shipping_fee": settings.fee,
        "can_request": any(line["eligible"] for line in lines),
        "block_reason": order_reason,
        "kinds": [{"value": value, "label": label} for value, label in ShopReturnRequest.KINDS],
        "reasons": [{"value": value, "label": label} for value, label in ShopReturnRequest.REASONS],
        "lines": lines,
        "requests": requests,
    }


# --- customer actions --------------------------------------------------------------------------


def _wanted_lines(lines):
    """[(line pk, units)] from the posted ``lines`` ([{"line_id", "qty"}])."""
    if not isinstance(lines, (list, tuple)) or len(lines) > MAX_REQUEST_LINES:
        raise ReturnRequestError("Choose the items to return or exchange again.", "invalid_return_lines")
    if not lines:
        raise ReturnRequestError("Choose at least one item.", "return_lines_required")
    wanted = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise ReturnRequestError("Choose the items to return or exchange again.", "invalid_return_lines")
        try:
            pk = int(entry.get("line_id"))
            qty = int(entry.get("qty", 0))
        except (TypeError, ValueError):
            raise ReturnRequestError("Choose the items to return or exchange again.", "invalid_return_lines") from None
        wanted.append((pk, qty))
    if len({pk for pk, _qty in wanted}) != len(wanted):
        raise ReturnRequestError("Choose the items to return or exchange again.", "invalid_return_lines")
    return wanted


def _clean_request(kind, reason, detail):
    kind = str(kind or "").strip()
    reason = str(reason or "").strip()
    detail = str(detail or "").strip()
    if kind not in KIND_LABELS:
        raise ReturnRequestError("Choose a return or an exchange.", "invalid_return_kind")
    if reason not in REASON_LABELS:
        raise ReturnRequestError("Choose a reason for the request.", "invalid_return_reason")
    if len(detail) > DETAIL_MAX_LENGTH:
        raise ReturnRequestError("The detail is too long.", "return_detail_too_long")
    if reason == ShopReturnRequest.REASON_OTHER and not detail:
        raise ReturnRequestError("Describe the reason for the request.", "return_detail_required")
    return kind, reason, detail


def create_request(order, *, kind, reason, detail="", lines=(), user=None):
    """Take the customer's request for ``lines`` of ``order``; returns the new ShopReturnRequest or
    raises ReturnRequestError. The order row is locked, so two submits cannot both take a line."""
    kind, reason, detail = _clean_request(kind, reason, detail)
    wanted = _wanted_lines(lines)
    settings = return_settings()
    if not settings.enabled:
        raise ReturnRequestError("Return and exchange requests are not available.", "return_requests_disabled")
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            raise ReturnRequestError("Order not found.", "order_not_found", status=404)
        if order_block_reason(locked, settings):
            raise ReturnRequestError("This order cannot be returned or exchanged.", "order_not_returnable")
        items = {item.pk: item for item in locked.items.filter(pk__in=[pk for pk, _qty in wanted])}
        if len(items) != len(wanted):
            raise ReturnRequestError("An item is not part of this order.", "return_line_not_found")
        held = open_requests_by_line(locked)
        now = timezone.now()
        for pk, qty in wanted:
            item = items[pk]
            if pk in held:
                raise ReturnRequestError(
                    "This item already has an open return or exchange request.", "return_line_already_requested"
                )
            if canonical_status(item.ct_status) not in ELIGIBLE_LINE_STATUSES:
                raise ReturnRequestError("This item cannot be returned or exchanged.", "return_line_not_eligible")
            if line_block_reason(item, locked, settings, now=now, open_line_ids=held):
                raise ReturnRequestError("The request period for this item has ended.", "return_period_ended")
            if not 1 <= qty <= int(item.ct_qty or 0):
                raise ReturnRequestError(
                    "Enter a quantity between 1 and the ordered quantity.", "invalid_return_quantity"
                )
        try:
            with transaction.atomic():
                request = ShopReturnRequest.objects.create(
                    order=locked,
                    user=user if getattr(user, "is_authenticated", False) else None,
                    kind=kind,
                    reason=reason,
                    detail=detail,
                )
                ShopReturnRequestLine.objects.bulk_create(
                    ShopReturnRequestLine(
                        request=request,
                        item=items[pk],
                        qty=qty,
                        it_name=items[pk].it_name,
                        ct_option=items[pk].ct_option,
                        amount=line_amount(items[pk]) * qty // max(1, int(items[pk].ct_qty or 1)),
                    )
                    for pk, qty in wanted
                )
        except IntegrityError:
            # the partial unique constraint: another request took the line in the meantime
            raise ReturnRequestError(
                "This item already has an open return or exchange request.", "return_line_already_requested"
            ) from None
        _append_order_history(locked, f"{_label(request)} 접수 ({REASON_LABELS[reason]})", "고객")
        _queue_notifications(request)
    return request


def withdraw_request(order, request_id):
    """The customer takes back a request that still waits for the shop."""
    with transaction.atomic():
        request = _locked_request(request_id, order_id=order.pk)
        if request is None:
            raise ReturnRequestError("Return request not found.", "return_request_not_found", status=404)
        if request.status != ShopReturnRequest.STATUS_REQUESTED:
            raise ReturnRequestError(
                "Only a request that is still waiting can be withdrawn.", "return_request_not_withdrawable"
            )
        _close(request, ShopReturnRequest.STATUS_WITHDRAWN, actor="고객")
        _append_order_history(request.order, f"{_label(request)} 철회", "고객")
        _queue_notifications(request)
    return request


# --- shop actions (admin) ----------------------------------------------------------------------


def _locked_request(request_id, *, order_id=None):
    """The request, locked after its order row (always in that order, so a customer and an admin
    acting at once cannot deadlock); None when it is missing or belongs to another order."""
    queryset = ShopReturnRequest.objects.filter(pk=request_id)
    if order_id is not None:
        queryset = queryset.filter(order_id=order_id)
    found = queryset.values_list("order_id", flat=True).first()
    if found is None:
        return None
    if ShopOrder.objects.select_for_update().filter(pk=found).values_list("pk", flat=True).first() is None:
        return None
    return (
        ShopReturnRequest.objects.select_for_update()
        .filter(pk=request_id, order_id=found)
        .select_related("order")
        .first()
    )


def _close(request, status, *, actor, fields=()):
    request.status = status
    request.closed_at = timezone.now()
    request.processed_by = str(actor or "")[:150]
    request.save(update_fields=["status", "closed_at", "processed_by", "updated_at", *fields])
    request.lines.update(is_open=False)


def _append_order_history(order, text, actor):
    locked = ShopOrder.objects.select_for_update().get(pk=order.pk)
    locked.od_mod_history = append_order_history(locked.od_mod_history, order_history_line(text, actor))
    locked.save(update_fields=["od_mod_history"])


def _label(request):
    return f"{KIND_LABELS.get(request.kind, request.kind)} 신청 #{request.pk}"


def approve_request(request_id, *, actor=""):
    with transaction.atomic():
        request = _locked_request(request_id)
        if request is None:
            return StatusChange(False, "신청을 찾을 수 없습니다.")
        if request.status != ShopReturnRequest.STATUS_REQUESTED:
            return StatusChange(False, f"'{request.get_status_display()}' 상태의 신청은 승인할 수 없습니다.")
        request.status = ShopReturnRequest.STATUS_APPROVED
        request.approved_at = timezone.now()
        request.processed_by = str(actor or "")[:150]
        request.save(update_fields=["status", "approved_at", "processed_by", "updated_at"])
        _append_order_history(request.order, f"{_label(request)} 승인", actor)
        _queue_notifications(request)
    return StatusChange(True, f"{_label(request)}을 승인했습니다. 상품을 회수한 뒤 완료 처리하세요.")


def reject_request(request_id, reason, *, actor=""):
    reason = " ".join(str(reason or "").split())
    if not reason:
        return StatusChange(False, "고객에게 보일 거절 사유를 입력하세요.")
    if len(reason) > REJECT_REASON_MAX_LENGTH:
        return StatusChange(False, f"거절 사유는 {REJECT_REASON_MAX_LENGTH}자 이내로 입력하세요.")
    with transaction.atomic():
        request = _locked_request(request_id)
        if request is None:
            return StatusChange(False, "신청을 찾을 수 없습니다.")
        if not request.is_open:
            return StatusChange(False, f"'{request.get_status_display()}' 상태의 신청은 거절할 수 없습니다.")
        request.reject_reason = reason
        _close(request, ShopReturnRequest.STATUS_REJECTED, actor=actor, fields=["reject_reason"])
        _append_order_history(request.order, f"{_label(request)} 거절 - {reason}", actor)
        _queue_notifications(request)
    return StatusChange(True, f"{_label(request)}을 거절했습니다.")


SETTLED_ON_ORDER_REASON = "주문에서 직접 처리되어 신청을 닫았습니다. 주문 내역을 확인해 주세요."


def close_settled_requests(order, *, actor=""):
    """Close the open requests of ``order`` (locked by the caller) whose every line the shop has
    already settled on the order itself - 취소, 반품 or 품절 through the admin's line change or
    주문 반품 - so nothing is left to decide. A return whose lines all became 반품 counts as completed;
    anything else is closed as rejected, the reason telling the customer it was handled on the
    order. A request with a line still active (a part of its units, say) stays open."""
    closed = 0
    requests = (
        ShopReturnRequest.objects.select_for_update()
        .filter(order_id=order.pk, status__in=ShopReturnRequest.OPEN_STATUSES)
        .prefetch_related("lines__item")
    )
    for request in requests:
        statuses = {str(line.item.ct_status or "") for line in request.lines.all()}
        if not statuses or not statuses <= INACTIVE_LINE_STATUSES:
            continue
        if request.kind == ShopReturnRequest.KIND_RETURN and statuses == {STATUS_RETURNED}:
            _close(request, ShopReturnRequest.STATUS_COMPLETED, actor=actor)
            history = f"{_label(request)} 완료 (주문에서 직접 반품 처리)"
        else:
            request.reject_reason = SETTLED_ON_ORDER_REASON
            _close(request, ShopReturnRequest.STATUS_REJECTED, actor=actor, fields=["reject_reason"])
            history = f"{_label(request)} 종료 (주문에서 직접 처리)"
        _append_order_history(order, history, actor)
        _queue_notifications(request)
        closed += 1
    return closed


def _return_lines(request):
    """(line ids, {pk: units} for lines returned in part, {pk: the quantity now}) of an approved
    return, or raises ValueError with the reason (Korean, for the admin)."""
    ids, quantities, expected = [], {}, {}
    for line in request.lines.select_related("item").order_by("pk"):
        item = line.item
        status = canonical_status(item.ct_status)
        if status not in ELIGIBLE_LINE_STATUSES:
            raise ValueError(
                f"{line_label(item)}은(는) 이미 '{status}' 상태라 반품할 수 없습니다. 주문을 확인한 뒤 신청을 거절하세요."
            )
        if line.qty > int(item.ct_qty or 0):
            raise ValueError(
                f"{line_label(item)}의 남은 수량({item.ct_qty}개)이 신청 수량({line.qty}개)보다 적습니다. 주문을 확인하세요."
            )
        ids.append(item.pk)
        expected[item.pk] = item.ct_qty
        if line.qty < item.ct_qty:
            quantities[item.pk] = line.qty
    return ids, quantities, expected


def _cancel_reason(request):
    return f"고객 반품 신청 #{request.pk} ({REASON_LABELS.get(request.reason, request.reason)})"


def preview_return(request, return_fee=None):
    """What completing an approved return would refund: (LineChangePlan, "") or (None, reason).
    Nothing is kept (a partial line is split in a rolled-back transaction)."""
    if request.kind != ShopReturnRequest.KIND_RETURN:
        return None, "교환 신청은 환불하지 않습니다."
    try:
        ids, quantities, expected = _return_lines(request)
    except ValueError as exc:
        return None, str(exc)
    fee = default_return_fee(request) if return_fee is None else max(0, int(return_fee))
    return preview_line_change(request.order, ids, STATUS_RETURNED, quantities=quantities, expected=expected, return_fee=fee)


def complete_request(request_id, *, actor="", return_fee=None, delivery_company="", invoice=""):
    """Complete an approved request: a return goes through the admin line change (refund first,
    then the lines, stock, coupons and points), an exchange records the re-shipment.

    Like admin_return_order the order row stays locked from the checks through the PG refund to
    the local change, in one durable transaction; a second submit waits for the lock, then finds
    the request completed and refunds nothing."""
    with transaction.atomic(durable=True):
        request = _locked_request(request_id)
        if request is None:
            return StatusChange(False, "신청을 찾을 수 없습니다.")
        order = request.order
        if request.status != ShopReturnRequest.STATUS_APPROVED:
            return StatusChange(False, f"'{request.get_status_display()}' 상태의 신청은 완료할 수 없습니다. 승인한 신청만 완료합니다.")
        if request.kind == ShopReturnRequest.KIND_EXCHANGE:
            return _complete_exchange(request, actor, delivery_company, invoice)
        return _complete_return(order, request, actor, return_fee)


def _complete_return(order, request, actor, return_fee):
    try:
        ids, quantities, expected = _return_lines(request)
    except ValueError as exc:
        return StatusChange(False, str(exc))
    fee = default_return_fee(request) if return_fee is None else max(0, int(return_fee))
    refunded_before = int(order.od_refund_price or 0)
    result = change_locked_order_lines(
        order,
        ids,
        STATUS_RETURNED,
        _cancel_reason(request),
        actor=actor,
        quantities=quantities,
        expected=expected,
        return_fee=fee,
    )
    if not result:
        # the PG may have refunded before the line change failed (the refund is recorded on the
        # order): count it on the request, so a retry that refunds only the rest reports the whole
        paid_out = int(ShopOrder.objects.filter(pk=order.pk).values_list("od_refund_price", flat=True).first() or 0)
        if paid_out > refunded_before:
            request.refund_amount = int(request.refund_amount or 0) + paid_out - refunded_before
            request.save(update_fields=["refund_amount", "updated_at"])
        return result
    try:
        # a savepoint: the refund and the line change stand even if the request cannot be updated
        with transaction.atomic():
            request.return_fee = result.return_fee
            request.refund_amount = int(request.refund_amount or 0) + result.refund
            _close(request, ShopReturnRequest.STATUS_COMPLETED, actor=actor, fields=["return_fee", "refund_amount"])
            _queue_notifications(request)
    except Exception:
        logger.exception("return request %s: the order lines were returned but the request was not updated", request.pk)
        return StatusChange(
            True,
            f"{result.message} 신청 상태를 저장하지 못했습니다. 신청을 확인해 주세요.",
            manual_refund=result.manual_refund,
            warning=True,
            refund=result.refund,
            return_fee=result.return_fee,
        )
    return result


def _complete_exchange(request, actor, delivery_company, invoice):
    company, _listed = normalize_company(delivery_company)
    invoice = " ".join(str(invoice or "").split())
    if not company or not invoice:
        return StatusChange(False, "교환 상품을 보낸 배송회사와 운송장번호를 입력하세요.")
    if len(company) > 100 or len(invoice) > MAX_INVOICE_LENGTH:
        return StatusChange(False, "배송회사 또는 운송장번호가 너무 깁니다.")
    try:
        _return_lines(request)
    except ValueError as exc:
        return StatusChange(False, str(exc).replace("반품할 수 없습니다", "교환할 수 없습니다"))
    request.exchange_delivery_company = company
    request.exchange_invoice = invoice
    _close(
        request,
        ShopReturnRequest.STATUS_COMPLETED,
        actor=actor,
        fields=["exchange_delivery_company", "exchange_invoice"],
    )
    _append_order_history(request.order, f"{_label(request)} 완료 - 교환 상품 발송 {company} {invoice}", actor)
    _queue_notifications(request)
    return StatusChange(True, f"{_label(request)}을 완료했습니다. 교환 상품 발송({company} {invoice})을 고객에게 알렸습니다.")


# --- notifications -----------------------------------------------------------------------------


def notification_title(request):
    kind = KIND_LABELS.get(request.kind, request.kind)
    if request.status == ShopReturnRequest.STATUS_COMPLETED:
        return "반품이 완료되었습니다." if request.kind == ShopReturnRequest.KIND_RETURN else "교환 상품을 보내 드렸습니다."
    return {
        ShopReturnRequest.STATUS_REQUESTED: f"{kind} 신청이 접수되었습니다.",
        ShopReturnRequest.STATUS_APPROVED: f"{kind} 신청이 승인되었습니다.",
        ShopReturnRequest.STATUS_REJECTED: f"{kind} 신청이 거절되었습니다.",
        ShopReturnRequest.STATUS_WITHDRAWN: f"{kind} 신청을 철회했습니다.",
    }.get(request.status, f"{kind} 신청 상태가 바뀌었습니다.")


def notification_body(request):
    body = f"주문번호 {request.order_id} · {_label(request)} {request.get_status_display()}"
    if request.status == ShopReturnRequest.STATUS_REJECTED and request.reject_reason:
        body += f" - {request.reject_reason}"
    elif request.status == ShopReturnRequest.STATUS_COMPLETED and request.kind == ShopReturnRequest.KIND_RETURN:
        body += f" - 환불 {request.refund_amount:,}원"
    elif request.status == ShopReturnRequest.STATUS_COMPLETED and request.exchange_invoice:
        body += f" - {request.exchange_delivery_company} {request.exchange_invoice}"
    return body


def _queue_notifications(request):
    """Mail the customer (and on a new request the shop) and fill a member's inbox, once the
    surrounding transaction commits."""
    from gnu_jango.notifications.outbox import event_on_commit
    from gnu_jango.notifications.signals import events_enabled
    from gnu_jango.shop.notifications import queue_return_request_mails

    queue_return_request_mails(request)
    user_id = request.order.user_id
    if not user_id or not events_enabled(False):
        return
    event_on_commit(
        user_id,
        f"return:{request.pk}:{request.status}",
        {
            "nt_type": "order",
            "nt_title": notification_title(request),
            "nt_body": notification_body(request),
            "nt_data": {
                "href": f"/shop/orders/{request.order_id}",
                "order_id": request.order_id,
                "return_request_id": request.pk,
                "status": request.status,
            },
        },
    )
