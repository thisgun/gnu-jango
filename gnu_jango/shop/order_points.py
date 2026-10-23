"""Youngcart purchase points (구매 포인트) for shop order lines.

An order line records the point it earns (``ct_point``, per unit) when the order is placed. The
point is paid once the line has been 완료 for ``de_point_days`` days (``save_order_point`` in
youngcart's lib/shop.lib.php); ``ct_point_use`` marks a line as handled and ``ct_complete_time``
is the clock. A line that leaves 완료 after it was paid gives the point back.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, F, Value, When
from django.utils import timezone

from gnu_jango.shop.models import ORDER_ITEM_STATUS_COMPLETED, ShopOrderItem
from gnu_jango.shop.shop_options import shop_options
from gnu_jango.users import point_ledger
from gnu_jango.users.models import User_Point

logger = logging.getLogger(__name__)

DELIVERY_POINT_TABLE = "@delivery"
POINT_TRUNC = 10  # youngcart get_item_point rounds a percentage point down to 10 won
DEFAULT_BATCH_LIMIT = 500
REQUEST_BATCH_LIMIT = 100  # admin pages pay a smaller batch; the scheduled job takes the rest


def item_purchase_point(product, *, io_type=0, io_price=0, has_option=False):
    """The point one unit of a line earns (youngcart get_item_point, cartupdate.php).

    A supplement line (io_type 1) earns nothing: youngcart reads it_supply_point, which the
    Django product model does not have."""
    if product is None or int(io_type or 0) != 0:
        return 0
    point_type = int(product.it_point_type or 0)
    rate = int(product.it_point or 0)
    if point_type > 0:
        base = int(product.it_price or 0)
        if point_type == 2 and has_option:
            base += int(io_price or 0)
        point = (base * rate // 100) // POINT_TRUNC * POINT_TRUNC
    else:
        point = rate
    return max(0, int(point))


def settle_case_keeps_purchase_points(settle_case, payable_amount):
    """True when an order paid this way earns purchase points even with de_card_point off.

    youngcart keeps them for orders without an online payment: bank deposit and (Django) the
    virtual account, which is also a deposit; an order with nothing to pay keeps them too."""
    from gnu_jango.api.shop_payments import settle_case_is_bank, settle_case_is_vbank

    if int(payable_amount or 0) <= 0:
        return True
    return settle_case_is_bank(settle_case) or settle_case_is_vbank(settle_case)


def order_line_points_enabled(settle_case, payable_amount):
    """Whether the lines of a new order record a purchase point at all."""
    if not point_ledger.points_enabled():
        return False
    if shop_options("de_card_point")["de_card_point"]:
        return True
    return settle_case_keeps_purchase_points(settle_case, payable_amount)


def purchase_point_notice():
    """Checkout notice data: points on, and whether PG-paid orders earn them."""
    return {
        "enabled": point_ledger.points_enabled(),
        "pg_orders": bool(shop_options("de_card_point")["de_card_point"]),
    }


def item_status_update(status, now=None):
    """``.update()`` kwargs that move lines to ``status`` and keep ct_complete_time in step
    (youngcart get_cart_complete_time_sql): stamped when a line first becomes 완료, kept while it
    stays 완료, cleared when it leaves.

    ct_complete_time comes first: MySQL evaluates SET assignments left to right, so the CASE must
    read the old ct_status (youngcart orderformcartupdate.php orders them the same way)."""
    if status != ORDER_ITEM_STATUS_COMPLETED:
        return {"ct_complete_time": None, "ct_status": status}
    now = now or timezone.now()
    return {
        "ct_complete_time": Case(
            When(
                ct_status=ORDER_ITEM_STATUS_COMPLETED,
                ct_complete_time__isnull=False,
                then=F("ct_complete_time"),
            ),
            default=Value(now),
        ),
        "ct_status": status,
    }


def save_order_item_status(queryset, status, *, reason=""):
    """Move each line to ``status`` through save() so django-simple-history records it.

    The order cancel/paid/shipping paths used a bulk ``.update()`` here, which bypassed the
    ShopOrderItem history. Order lines are few, so saving each one is acceptable and keeps the
    audit trail complete.
    """

    changed = []
    for item in queryset.select_for_update():
        item.ct_status = status
        item.sync_complete_time()
        item._change_reason = (reason or f"order line {status}")[:100]
        item.save(update_fields=["ct_status", "ct_complete_time"])
        changed.append(item)
    return changed


def _award_content(item, order):
    return f"주문번호 {order.od_id} ({item.ct_id}) 배송완료"


def _award_line(pk):
    """Pay one due line once; returns the points paid (0 when nothing was earned)."""
    with transaction.atomic():
        item = (
            ShopOrderItem.objects.select_for_update()
            .filter(pk=pk, ct_point_use=False, ct_status=ORDER_ITEM_STATUS_COMPLETED)
            .first()
        )
        if item is None:
            return None  # another run handled it
        order = item.order
        paid = 0
        point = int(item.ct_point or 0) * int(item.ct_qty or 0)
        if order.user_id and point > 0:
            result = point_ledger.insert_point(
                order.user,
                point,
                _award_content(item, order),
                DELIVERY_POINT_TABLE,
                item.pk,
                str(order.od_id),
            )
            if result == point_ledger.APPLIED:
                paid = point
            elif result != point_ledger.DUPLICATE:
                # Not paid and not paid before (points switched off meanwhile): leave it for later.
                return None
        # youngcart marks the line handled also when it earned nothing (guest, zero point)
        item.ct_point_use = True
        item.save(update_fields=["ct_point_use"])
        return paid


def save_order_points(now=None, *, limit=DEFAULT_BATCH_LIMIT, dry_run=False):
    """Pay the purchase points of lines that have been 완료 for de_point_days days.

    While cf_use_point is off nothing is paid or marked, so lines that already carry a point (ordered
    while points were on) are paid once points are switched back on; youngcart instead marks them
    handled and the member never gets them. Lines ordered while points were off carry ct_point 0
    (as in youngcart's cartupdate.php) and never earn anything. A 완료 line without
    ct_complete_time (completed by a path that did not stamp it) starts its clock now instead of
    being paid at once.
    """
    now = now or timezone.now()
    summary = {"applied": not dry_run, "due": 0, "awarded": 0, "points": 0, "marked": 0, "stamped": 0}
    if not point_ledger.points_enabled():
        summary["skipped"] = "points_disabled"
        return summary
    days = max(0, int(shop_options("de_point_days")["de_point_days"] or 0))
    unhandled = ShopOrderItem.objects.filter(ct_status=ORDER_ITEM_STATUS_COMPLETED, ct_point_use=False)
    if not dry_run:
        summary["stamped"] = unhandled.filter(ct_complete_time__isnull=True).update(ct_complete_time=now)
    due_ids = list(
        unhandled.filter(ct_complete_time__isnull=False, ct_complete_time__lte=now - timedelta(days=days))
        .order_by("ct_complete_time", "pk")
        .values_list("pk", flat=True)[: max(1, int(limit or DEFAULT_BATCH_LIMIT))]
    )
    summary["due"] = len(due_ids)
    if dry_run:
        return summary
    for pk in due_ids:
        paid = _award_line(pk)
        if paid is None:
            continue
        summary["marked"] += 1
        if paid:
            summary["awarded"] += 1
            summary["points"] += paid
    return summary


def run_save_order_points_safely():
    """save_order_points for request paths (admin pages): a failure is logged, never raised."""
    try:
        # a savepoint, so a failure inside the admin's own transaction does not break it
        with transaction.atomic():
            return save_order_points(limit=REQUEST_BATCH_LIMIT)
    except Exception:  # noqa: BLE001 - paying points must not break the admin page
        logger.exception("save_order_points failed")
        return None


def _legacy_rel_id(user):
    # Gnuboard5 rows imported from PHP keep po_rel_id = mb_id (an integer column here, 0 unless
    # the member id is numeric) and po_rel_action "od_id,ct_id".
    username = str(user.get_username() or "")
    return int(username) if username.isdigit() else 0


def _take_back_line(pk):
    with transaction.atomic():
        item = (
            ShopOrderItem.objects.select_for_update()
            .filter(pk=pk, ct_point_use=True)
            .exclude(ct_status=ORDER_ITEM_STATUS_COMPLETED)
            .first()
        )
        if item is None:
            return False
        order = item.order
        taken = False
        if order.user_id:
            user = order.user
            taken = point_ledger.delete_point(user, DELIVERY_POINT_TABLE, item.pk, str(order.od_id))
            if not taken:
                taken = point_ledger.delete_point(
                    user, DELIVERY_POINT_TABLE, _legacy_rel_id(user), f"{order.od_id},{item.ct_id}"
                )
        item.ct_point_use = False
        item.ct_complete_time = None
        item.save(update_fields=["ct_point_use", "ct_complete_time"])
        return taken


def _delivery_point_total(user, rel_id, rel_action):
    rows = User_Point.objects.filter(
        user=user, po_rel_table=DELIVERY_POINT_TABLE, po_rel_id=rel_id, po_rel_action=rel_action
    ).values_list("po_point", flat=True)
    return sum(rows)


def resettle_split_line_points(item, order):
    """A paid line (``ct_point_use``) was split by a partial quantity cancel and now holds fewer
    units: its @delivery point is paid again for the units it kept, so the units that left take
    their share back (ct_point per unit × the cancelled quantity) and a later take-back of the
    line removes exactly what it still earns. The caller has saved the reduced ``ct_qty``.
    Returns the points taken back."""
    if not item.ct_point_use or not order.user_id:
        return 0
    user = order.user
    keys = (item.pk, str(order.od_id))
    paid = _delivery_point_total(user, *keys)
    if not paid:
        keys = (_legacy_rel_id(user), f"{order.od_id},{item.ct_id}")
        paid = _delivery_point_total(user, *keys)
    if not paid:
        return 0  # nothing on record to adjust
    point_ledger.delete_point(user, DELIVERY_POINT_TABLE, *keys)
    kept = int(item.ct_point or 0) * int(item.ct_qty or 0)
    if kept > 0:
        point_ledger.insert_point(
            user, kept, _award_content(item, order), DELIVERY_POINT_TABLE, item.pk, str(order.od_id), force=True
        )
    return max(0, paid - kept)


def take_back_order_points(order):
    """Give back the purchase points of the order's lines that were paid and are no longer 완료
    (youngcart orderformcartupdate.php deletes the @delivery point on a status change).
    Returns the number of lines whose point was taken back."""
    pks = list(
        ShopOrderItem.objects.filter(order_id=order.pk, ct_point_use=True)
        .exclude(ct_status=ORDER_ITEM_STATUS_COMPLETED)
        .values_list("pk", flat=True)
    )
    return sum(1 for pk in pks if _take_back_line(pk))
