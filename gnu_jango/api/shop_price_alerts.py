"""가격 인하 알림 of the shop API: a signed-in member asks on a product page to hear when it gets cheaper
(gnu_jango/shop/price_alerts.py sends the notice)."""

from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.shop.models import ShopPriceAlert, ShopProduct
from gnu_jango.shop.price_alerts import price_alerts_enabled, register

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from .shop_common import require_user

MAX_LISTED_ALERTS = 200


def alert_payload(alert, it_id=None):
    if alert is None:
        return {"it_id": it_id, "alerted": False, "waiting": False, "pa_price": None, "created_at": None}
    return {
        "it_id": alert.product_id,
        "alerted": True,
        # waiting: not told yet; a told alert stays listed until the member asks again or removes it
        "waiting": alert.notified_at is None,
        "pa_price": alert.pa_price,
        "created_at": alert.created_at.isoformat(),
    }


def _disabled():
    return api_error(
        "Price drop alerts are not enabled.",
        status=drf_status.HTTP_409_CONFLICT,
        code="price_alert_disabled",
    )


@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def product_price_alert_view(request, it_id):
    user, error = require_user(request)
    if error:
        return error
    alerts = ShopPriceAlert.objects.filter(user=user, product_id=it_id)
    if request.method == "GET":
        return api_response(data=alert_payload(alerts.first(), it_id))
    if request.method == "DELETE":
        deleted, _ = alerts.delete()
        return api_response(data={"it_id": it_id, "deleted": bool(deleted)})
    if not price_alerts_enabled():
        return _disabled()
    product = ShopProduct.objects.filter(pk=it_id, it_use="1").first()
    if product is None:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    alert = register(user, product)
    return api_response(data=alert_payload(alert), status=drf_status.HTTP_201_CREATED)


product_price_alert_view.cls.throttle_scope = "price-alert"


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def price_alert_list_view(request):
    user, error = require_user(request)
    if error:
        return error
    alerts = ShopPriceAlert.objects.filter(user=user).select_related("product")[:MAX_LISTED_ALERTS]
    return api_response(
        data=[
            {
                **alert_payload(alert),
                "it_name": alert.product.it_name,
                "it_price": int(alert.product.it_price or 0),
                "notified_at": alert.notified_at.isoformat() if alert.notified_at else None,
                "notified_price": alert.notified_price,
            }
            for alert in alerts
        ]
    )
