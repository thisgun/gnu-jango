"""Shipment tracking through Delivery Tracker: which orders to look up, what the answer means
for the order, and what the customer and the admin are shown.

An order is tracked while it is 배송 with an invoice and a courier that has a Delivery Tracker
carrier id (delivery.DELIVERY_TRACKER_CARRIERS). Each lookup stores the result on the order's
ShopShipmentTracking row and sets when to look again: every few hours while the shipment moves
(less often while a webhook is registered, as Delivery Tracker then calls back on a change),
later when the carrier does not know the invoice yet, and with a growing backoff on errors.
Tracking stops once the shipment is delivered or MAX_TRACKING_DAYS after it started.

When the shipment is delivered the time is recorded. With 배송완료 시 주문 완료 처리 on, an
order still in 배송 then moves to 완료 through order_flow.move_order_status - the same path as
the admin's status change, so lines, purchase points, sales counts and the order history follow
- and the customer gets the 배송완료 mail."""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import delivery_tracker_client as client
from .delivery import DELIVERY_TRACKER_CARRIERS, find_delivery_company, tracker_carrier_id
from .delivery_tracking_settings import tracking_config, webhook_callback_url
from .models import ShopOrder, ShopShipmentTracking
from .order_statuses import STATUS_COMPLETED, STATUS_SHIPPING

logger = logging.getLogger(__name__)

TRACKING_ACTOR = "배송조회"
POLL_INTERVAL = timedelta(hours=3)
WEBHOOK_POLL_INTERVAL = timedelta(hours=12)
NOT_FOUND_INTERVAL = timedelta(hours=6)
ERROR_BACKOFF = timedelta(minutes=30)
MAX_ERROR_BACKOFF = timedelta(hours=24)
MAX_TRACKING_DAYS = 30
# a lookup of the same shipment is not repeated sooner (admin button, overlapping runs)
REFRESH_COOLDOWN = timedelta(seconds=30)
# the docs: register for 48 hours and renew about every 24 hours
WEBHOOK_TTL = timedelta(hours=48)
WEBHOOK_RENEW_BEFORE = timedelta(hours=24)

STATUS_LABELS = {
    "UNKNOWN": "확인 중",
    "INFORMATION_RECEIVED": "접수",
    "AT_PICKUP": "집화",
    "IN_TRANSIT": "이동 중",
    "OUT_FOR_DELIVERY": "배송 출발",
    "ATTEMPT_FAIL": "배달 실패",
    "DELIVERED": "배송 완료",
    "AVAILABLE_FOR_PICKUP": "수령 대기",
    "EXCEPTION": "배송 이상",
}
ERROR_MESSAGES = {
    "NOT_FOUND": "조회 결과 없음 - 택배사에 운송장이 아직 등록되지 않았을 수 있습니다.",
    "BAD_REQUEST": "Delivery Tracker가 요청을 거부했습니다. 운송장번호를 확인하세요.",
    "UNAUTHENTICATED": "Delivery Tracker 키를 인증하지 못했습니다. Client ID와 Client Secret을 확인하세요.",
    "FORBIDDEN": "Delivery Tracker가 이 키의 조회를 허용하지 않습니다. 콘솔의 프로젝트 설정을 확인하세요.",
    "RATE_LIMITED": "Delivery Tracker 호출 한도를 넘었습니다. 잠시 후 다시 조회합니다.",
    "NETWORK": "Delivery Tracker에 연결하지 못했습니다. 잠시 후 다시 조회합니다.",
}


@dataclass(frozen=True)
class RefreshResult:
    # skipped | updated | not_found | delivered | error
    status: str
    message: str = ""
    completed: bool = False

    def __bool__(self):
        return self.status in {"updated", "delivered", "not_found"}


def tracking_number(invoice):
    """The invoice as Delivery Tracker takes it: no spaces or hyphens."""
    return re.sub(r"[\s-]", "", str(invoice or ""))[:100]


def tracked_company_names():
    return tuple(DELIVERY_TRACKER_CARRIERS)


def status_label(code):
    return STATUS_LABELS.get(code, STATUS_LABELS["UNKNOWN"])


def current_tracking(order):
    """The order's tracking row while it still belongs to the order's courier and invoice."""
    row = ShopShipmentTracking.objects.filter(order_id=order.pk).first()
    if row is None:
        return None
    if row.delivery_company != order.od_delivery_company or row.invoice != order.od_invoice:
        return None
    return row


def due_orders(*, now=None, limit=30, complete_on_delivered=False):
    """Orders to look up now, those never looked up (or whose invoice changed) first. With
    ``complete_on_delivered``, an order still 배송 whose shipment was found delivered is due too
    (it is completed without another lookup)."""
    now = now or timezone.now()
    started_after = now - timedelta(days=MAX_TRACKING_DAYS)
    tracking = "shipment_tracking"
    changed = ~Q(**{f"{tracking}__invoice": F("od_invoice")}) | ~Q(
        **{f"{tracking}__delivery_company": F("od_delivery_company")}
    )
    due = (
        Q(**{f"{tracking}__delivered_at__isnull": True, f"{tracking}__started_at__gte": started_after})
        & (Q(**{f"{tracking}__next_check_at__isnull": True}) | Q(**{f"{tracking}__next_check_at__lte": now}))
    )
    if complete_on_delivered:
        due |= Q(**{f"{tracking}__delivered_at__isnull": False})
    return list(
        ShopOrder.objects.filter(od_status=STATUS_SHIPPING, od_delivery_company__in=tracked_company_names())
        .exclude(od_invoice="")
        .filter(Q(**{f"{tracking}__isnull": True}) | changed | due)
        .order_by(F(f"{tracking}__next_check_at").asc(nulls_first=True), "od_invoice_time", "od_id")[:limit]
    )


def _row_for(order, carrier_id, number, now):
    """(The order's row, whether it is new or was started over because it had been fetched
    for another courier or invoice)."""
    row, created = ShopShipmentTracking.objects.get_or_create(
        order=order,
        defaults={
            "delivery_company": order.od_delivery_company,
            "invoice": order.od_invoice,
            "carrier_id": carrier_id,
            "tracking_number": number,
            "started_at": now,
        },
    )
    if (row.delivery_company, row.invoice, row.carrier_id, row.tracking_number) != (
        order.od_delivery_company, order.od_invoice, carrier_id, number
    ):
        row.delivery_company = order.od_delivery_company
        row.invoice = order.od_invoice
        row.carrier_id = carrier_id
        row.tracking_number = number
        row.status_code = row.status_label = row.last_error = ""
        row.events = []
        row.last_event_at = row.delivered_at = row.webhook_expires_at = row.next_check_at = None
        row.failures = 0
        row.started_at = now
        return row, True
    return row, created


def _error_backoff(failures):
    return min(MAX_ERROR_BACKOFF, ERROR_BACKOFF * 2 ** max(0, min(failures, 10) - 1))


def _apply_track_info(row, info, now):
    row.events = [event.as_dict() for event in info.events]
    last = info.last_event
    row.status_code = last.status if last else ""
    row.status_label = status_label(last.status) if last else ""
    row.last_event_at = last.time if last else None
    row.failures = 0
    row.last_error = ""
    if info.delivered:
        row.delivered_at = row.delivered_at or (last.time if last and last.time else now)
        row.next_check_at = None
        return
    webhook_active = bool(row.webhook_expires_at and row.webhook_expires_at > now)
    row.next_check_at = now + (WEBHOOK_POLL_INTERVAL if webhook_active else POLL_INTERVAL)


def _renew_webhook(row, config, now):
    """Register (or extend) the webhook when it is missing or expires within a day. A failure
    only means the order is polled more often."""
    if row.delivered_at or (row.webhook_expires_at and row.webhook_expires_at - now > WEBHOOK_RENEW_BEFORE):
        return
    callback_url = webhook_callback_url()
    if not callback_url:
        return
    expires_at = now + WEBHOOK_TTL
    try:
        accepted = client.register_webhook(
            row.carrier_id,
            row.tracking_number,
            callback_url=callback_url,
            expires_at=expires_at,
            credentials=config.credentials,
        )
    except client.DeliveryTrackerError as exc:
        logger.warning("Delivery Tracker webhook for order %s not registered: %s", row.order_id, exc.code)
        return
    if accepted:
        row.webhook_expires_at = expires_at
        # a change now calls back, so the regular lookup can wait longer
        row.next_check_at = now + WEBHOOK_POLL_INTERVAL


def _complete_order(order, actor):
    """배송→완료 through the admin's status change path; the 배송완료 mail once it commits."""
    from .notifications import queue_order_delivered_mail
    from .order_flow import move_order_status

    with transaction.atomic():
        result = move_order_status(order, STATUS_COMPLETED, actor=actor)
        if result:
            queue_order_delivered_mail(order)
    return bool(result)


def refresh_order_tracking(order, *, config=None, now=None, actor=TRACKING_ACTOR, pay_due_points=True):
    """Look the order's shipment up once and record the answer (see the module docstring).
    ``pay_due_points=False`` leaves the purchase point run to the caller (a batch runs it once)."""
    config = config or tracking_config()
    if not config.enabled:
        return RefreshResult("skipped", "배송조회가 꺼져 있거나 Delivery Tracker 키가 등록되지 않았습니다.")
    carrier_id = tracker_carrier_id(order.od_delivery_company)
    number = tracking_number(order.od_invoice)
    if not carrier_id or not number:
        return RefreshResult("skipped", "배송회사가 배송조회를 지원하지 않거나 운송장번호가 없습니다.")
    if order.od_status != STATUS_SHIPPING:
        return RefreshResult("skipped", "배송 상태의 주문만 조회합니다.")
    now = now or timezone.now()
    row, restarted = _row_for(order, carrier_id, number, now)
    message = "이미 배송완료가 확인된 주문입니다."
    if not row.delivered_at:
        message = "배송완료를 확인했습니다."
        if not restarted and row.last_checked_at and now - row.last_checked_at < REFRESH_COOLDOWN:
            return RefreshResult("skipped", "방금 조회했습니다. 잠시 후 다시 조회하세요.")
        if not _claim(row, now):
            return RefreshResult("skipped", "다른 작업이 이 주문을 조회하고 있습니다.")
        result = _look_up(row, config, now)
        if result is not None:
            return result
        if not row.delivered_at:
            return RefreshResult("updated", row.status_label)
    # Decided from the order, not from whether this lookup found the delivery: a completion that
    # failed (or the switch turned on later) is retried, and move_order_status refuses a repeat.
    completed = False
    if config.complete_on_delivered:
        completed = _complete_order(order, actor)
        if completed and pay_due_points:
            from .order_points import run_save_order_points_safely

            run_save_order_points_safely()
    return RefreshResult("delivered", message, completed=completed)


def _claim(row, now):
    """Stamp last_checked_at unless another lookup did so first (two runs, or the admin button
    during a run): only one of them calls the API."""
    if row.pk is None or row._state.adding:
        row.last_checked_at = now
        return True
    claimed = ShopShipmentTracking.objects.filter(pk=row.pk, last_checked_at=row.last_checked_at).update(
        last_checked_at=now
    )
    row.last_checked_at = now
    return bool(claimed)


def _save(row, loaded_next_check):
    """Save the lookup; a webhook ping that arrived meanwhile (next_check_at moved earlier) wins."""
    with transaction.atomic():
        current = (
            ShopShipmentTracking.objects.select_for_update().filter(pk=row.pk).values_list("next_check_at", flat=True).first()
            if row.pk
            else None
        )
        if current is not None and current != loaded_next_check and not row.delivered_at:
            row.next_check_at = min(current, row.next_check_at or current)
        row.save()


def _look_up(row, config, now):
    """One track call recorded on ``row``; a RefreshResult when it failed, else None."""
    loaded_next_check = row.next_check_at
    try:
        info = client.track(row.carrier_id, row.tracking_number, credentials=config.credentials)
    except client.DeliveryTrackerError as exc:
        if exc.code == "NOT_FOUND":
            row.last_error = ERROR_MESSAGES["NOT_FOUND"]
            row.next_check_at = now + NOT_FOUND_INTERVAL
            _save(row, loaded_next_check)
            return RefreshResult("not_found", row.last_error)
        row.failures = min(row.failures + 1, 1000)
        row.last_error = (ERROR_MESSAGES.get(exc.code) or f"Delivery Tracker 조회 실패 ({exc.code})")[:255]
        row.next_check_at = now + _error_backoff(row.failures)
        _save(row, loaded_next_check)
        return RefreshResult("error", row.last_error)
    _apply_track_info(row, info, now)
    _renew_webhook(row, config, now)
    _save(row, loaded_next_check)
    return None


def mark_webhook_ping(carrier_id, number, *, now=None):
    """A webhook call: look the matching undelivered shipments up on the next run. The posted
    body only says which shipment changed; its status always comes from a fresh lookup."""
    now = now or timezone.now()
    return ShopShipmentTracking.objects.filter(
        carrier_id=str(carrier_id or "")[:64],
        tracking_number=tracking_number(number),
        delivered_at__isnull=True,
        order__od_status=STATUS_SHIPPING,
    ).update(next_check_at=now)


def _iso(value):
    return timezone.localtime(value).isoformat() if value else ""


def _event_payload(event):
    code = str(event.get("status") or "UNKNOWN")
    return {
        "time": str(event.get("time") or ""),
        "status": code,
        "status_label": str(event.get("name") or "") or status_label(code),
        "location": str(event.get("location") or ""),
        "description": str(event.get("description") or ""),
    }


def _local(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else "-"


def admin_summary(order, *, config=None):
    """The order change page's 배송조회 card: whether a lookup is possible and the last answer."""
    config = config or tracking_config()
    carrier_id = tracker_carrier_id(order.od_delivery_company)
    can_refresh = (
        config.enabled and bool(carrier_id) and bool(tracking_number(order.od_invoice))
        and order.od_status == STATUS_SHIPPING
    )
    if not config.enabled:
        note = "배송조회가 꺼져 있거나 Delivery Tracker 키가 등록되지 않았습니다 (쇼핑몰 설정 > 배송설정)."
    elif not order.od_invoice:
        note = "운송장번호를 입력하면 조회할 수 있습니다."
    elif not carrier_id:
        note = f"'{order.od_delivery_company or '-'}'은(는) 배송조회를 지원하지 않는 배송회사입니다. 배송 조회 링크만 표시합니다."
    elif order.od_status != STATUS_SHIPPING:
        note = "배송 상태의 주문만 조회합니다."
    else:
        note = ""
    row = current_tracking(order)
    events = [_event_payload(event) for event in reversed(row.events or []) if isinstance(event, dict)][:5] if row else []
    for event in events:
        parsed = client.parse_time(event["time"])
        event["time"] = _local(parsed) if parsed else "-"
    return {
        "can_refresh": can_refresh,
        "note": note,
        "carrier_id": carrier_id or "-",
        "has_row": row is not None,
        "status_label": (row.status_label or status_label(row.status_code)) if row and row.status_code else "조회 전",
        "delivered": bool(row and row.delivered_at),
        "delivered_at": _local(row.delivered_at) if row else "-",
        "last_event_at": _local(row.last_event_at) if row else "-",
        "last_checked_at": _local(row.last_checked_at) if row else "-",
        "next_check_at": _local(row.next_check_at) if row and not row.delivered_at else "-",
        "webhook_expires_at": _local(row.webhook_expires_at) if row else "-",
        "last_error": row.last_error if row else "",
        "events": events,
    }


def tracking_payload(order, *, config=None):
    """The customer's view of the tracking, newest event first; None while tracking is off,
    the courier is not tracked or nothing was found yet (the page then shows only the link)."""
    if not order.od_invoice or not find_delivery_company(order.od_delivery_company):
        return None
    config = config or tracking_config()
    if not config.enabled:
        return None
    row = current_tracking(order)
    if row is None or not (row.status_code or row.events):
        return None
    return {
        "carrier_id": row.carrier_id,
        "status": row.status_code,
        "status_label": row.status_label or status_label(row.status_code),
        "delivered": bool(row.delivered_at),
        "delivered_at": _iso(row.delivered_at),
        "last_event_at": _iso(row.last_event_at),
        "last_checked_at": _iso(row.last_checked_at),
        "events": [_event_payload(event) for event in reversed(row.events or []) if isinstance(event, dict)],
    }
