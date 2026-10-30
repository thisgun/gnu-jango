"""가격 인하 알림: a member asks on a product page to hear when the product gets cheaper than it is now.
The scheduled shop alerts tell them once, by mail and a site notification, when the product is on sale
again below that price; the alert then rests until the member asks again."""

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from gnu_jango.shop.models import ShopPriceAlert
from gnu_jango.shop.shop_options import shop_options

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT = 200


def price_alerts_enabled():
    return bool(shop_options("de_price_alert_use")["de_price_alert_use"])


def register(user, product):
    """Ask for (or re-arm) the alert at the product's current price; returns the alert."""
    alert, _ = ShopPriceAlert.objects.update_or_create(
        user=user,
        product=product,
        defaults={
            "pa_price": int(product.it_price or 0),
            "created_at": timezone.now(),
            "notified_at": None,
            "notified_price": None,
        },
    )
    return alert


def due_alerts():
    """Waiting alerts of products that can be bought for less than when they were asked for."""
    return (
        ShopPriceAlert.objects.filter(
            notified_at__isnull=True,
            # a withdrawn or blocked member is not told
            user__is_active=True,
            user__profile__leave_date__isnull=True,
            product__it_price__lt=F("pa_price"),
            product__it_use="1",
            product__it_stock_qty__gt=0,
        )
        .exclude(product__it_soldout="1")
        .order_by("created_at", "pk")
    )


def _notify(alert_id):
    """Mark one alert as told and queue its site notification; returns the alert, or None when it was
    already told or the price went back up meanwhile."""
    from gnu_jango.notifications.outbox import event_on_commit

    with transaction.atomic():
        alert = (
            ShopPriceAlert.objects.select_for_update(of=("self",))
            .select_related("product", "user")
            .filter(pk=alert_id, notified_at__isnull=True)
            .first()
        )
        price = int(alert.product.it_price or 0) if alert else 0
        if alert is None or price >= alert.pa_price:
            return None
        alert.notified_at = timezone.now()
        alert.notified_price = price
        alert.save(update_fields=["notified_at", "notified_price"])
        product = alert.product
        event_on_commit(alert.user_id, f"price-alert:{alert.pk}:{int(alert.created_at.timestamp())}", {
            "nt_type": "price_alert",
            "nt_title": "관심 상품의 가격이 내려갔습니다.",
            "nt_body": f"{product.it_name}: {alert.pa_price:,}원 → {price:,}원",
            "nt_data": {"href": f"/shop/products/{product.it_id}", "it_id": product.it_id, "price": price},
        })
    return alert


def _send_mail(alert):
    from gnu_jango.api.shop_common import product_image_url
    from gnu_jango.shop.notifications import absolute_asset_url, mail_enabled, send_shop_mail, site_link, site_title

    if not mail_enabled() or not alert.user.email:
        return False
    product = alert.product
    context = {
        "product": product,
        "old_price": alert.pa_price,
        "new_price": alert.notified_price,
        "product_url": site_link(f"/shop/products/{product.it_id}"),
        "image_url": absolute_asset_url(product_image_url(product)),
    }
    return send_shop_mail(
        f"[{site_title()}] 관심 상품의 가격이 내려갔습니다: {product.it_name}",
        "price_alert",
        context,
        [alert.user.email],
    )


def send_due_price_alerts(*, dry_run=False, limit=DEFAULT_BATCH_LIMIT):
    ids = list(due_alerts().values_list("pk", flat=True)[:limit])
    summary = {"due": len(ids), "notified": 0, "mailed": 0}
    if dry_run:
        return summary
    for alert_id in ids:
        alert = _notify(alert_id)
        if alert is None:
            continue
        summary["notified"] += 1
        if _send_mail(alert):
            summary["mailed"] += 1
    return summary
