"""재입고 SMS (adm/shop_admin/itemstocksms.php): one message to a subscriber of a product that is back
in stock. The admin action sends the rows an administrator picks; with de_stock_sms_auto the scheduled
shop alerts send the rows nobody has tried yet."""

from django.db import transaction
from django.utils import timezone

from gnu_jango.shop.models import ShopStockNotification, ShopStockNotificationSendLog

SKIPPED = "skipped"
# The admin action and one scheduled run send at most this many messages.
SEND_LIMIT = 25


def in_stock(product):
    return bool(product) and str(product.it_soldout or "0") != "1" and int(product.it_stock_qty or 0) > 0


def send_restock_sms(notification_id, *, sms, sender_name, requested_by=None):
    """Send the restock SMS of one subscription; returns accepted, rejected, unknown or skipped.

    Skipped: already sent, a previous attempt may still be on its way (sending/unknown), or the
    product is gone or not in stock. The send log is written before the gateway call, so a crash in
    between leaves a "sending" row that keeps the subscriber from getting the message twice."""
    from gnu_jango.shop.sms.service import send_message

    with transaction.atomic():
        notification = (
            # PostgreSQL refuses FOR UPDATE on the nullable side of the product join
            ShopStockNotification.objects.select_for_update(of=("self",))
            .select_related("product")
            .filter(pk=notification_id)
            .first()
        )
        if not notification or notification.ss_send:
            return SKIPPED
        previous = notification.send_logs.order_by("-created_at", "-pk").first()
        if previous and previous.status in {"sending", "unknown"}:
            return SKIPPED
        product = notification.product
        if not in_stock(product):
            return SKIPPED
        message_text = f"[{sender_name}] {product.it_name} 상품이 재입고되었습니다."
        digits = "".join(character for character in str(notification.ss_hp or "") if character.isdigit())
        send_log = ShopStockNotificationSendLog.objects.create(
            notification=notification,
            product_it_id=notification.it_id,
            recipient_last4=digits[-4:],
            message=message_text,
            requested_by=requested_by,
        )

    # never raises: configuration, gateway and network failures come back as a result
    result = send_message(notification.ss_hp, message_text, current=sms, purpose=f"재입고 {notification.it_id}")

    with transaction.atomic():
        send_log.status = result.status
        send_log.error_text = result.error_text[:2000]
        send_log.provider_code = result.provider_code[:40]
        send_log.completed_at = timezone.now()
        send_log.save(update_fields=("status", "error_text", "provider_code", "completed_at"))
        if result.status == "accepted":
            ShopStockNotification.objects.filter(pk=notification_id, ss_send=False).update(
                ss_send=True,
                ss_send_time=timezone.now(),
            )
    return result.status


def untried_in_stock_ids(limit=SEND_LIMIT):
    """Subscriptions of products back in stock that were never tried, oldest first (the automatic send)."""
    return list(
        ShopStockNotification.objects.filter(
            ss_send=False,
            send_logs__isnull=True,
            product__it_stock_sms="1",
            product__it_stock_qty__gt=0,
        )
        .exclude(product__it_soldout="1")
        .order_by("ss_datetime", "pk")
        .values_list("pk", flat=True)[:limit]
    )


def send_due_restock_sms(*, dry_run=False, limit=SEND_LIMIT):
    """de_stock_sms_auto: send the untried subscriptions; returns the counts by outcome."""
    from gnu_jango.shop.sms.service import sms_settings

    ids = untried_in_stock_ids(limit)
    counts = {"due": len(ids), "accepted": 0, "rejected": 0, "unknown": 0, "skipped": 0}
    if dry_run or not ids:
        return counts
    sms = sms_settings()
    if not sms.enabled or not sms.company_name or not sms.callback:
        # the admin action reports this; the job just waits for the SMS settings
        return {**counts, "skipped": len(ids), "reason": "sms_not_configured"}
    for notification_id in ids:
        status = send_restock_sms(notification_id, sms=sms, sender_name=sms.company_name)
        counts[status] = counts.get(status, 0) + 1
    return counts
