"""POST /api/v1/shop/delivery-tracker/webhook/<token>: Delivery Tracker calls this when a
registered shipment changes (registerTrackWebhook, shop/delivery_tracking.py).

The callback carries no signature (the docs: anyone who knows the URL can call it), so the URL
holds a per-site token derived from SECRET_KEY and anything else gets a 404. Even then the body
- {"carrierId", "trackingNumber"} - is only used to pick the shipment: the call marks it for a
lookup by the next track_shipments run and never sets a status. It answers at once (the docs
ask for a reply within a second, 202 recommended) and is throttled per address."""

from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status as drf_status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.shop.delivery_tracking import mark_webhook_ping
from gnu_jango.shop.delivery_tracking_settings import tracking_config, webhook_token_valid

from .response import api_error, api_response
from .shop_common import request_data

THROTTLE_SCOPE = "delivery-tracker-webhook"


@never_cache
@extend_schema(exclude=True)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@throttle_classes([ScopedRateThrottle])
def delivery_tracker_webhook_view(request, token):
    if not webhook_token_valid(token):
        return api_error("Not found.", status=drf_status.HTTP_404_NOT_FOUND, code="not_found")
    data = request_data(request)
    carrier_id = str(data.get("carrierId") or "").strip()
    tracking_number = str(data.get("trackingNumber") or "").strip()
    if not carrier_id or not tracking_number or len(carrier_id) > 64 or len(tracking_number) > 100:
        return api_error(
            "Invalid Delivery Tracker callback.",
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="delivery_tracker_callback_invalid",
        )
    # a 2xx stops Delivery Tracker's retries; with tracking off there is nothing to look up
    marked = mark_webhook_ping(carrier_id, tracking_number) if tracking_config().enabled else 0
    return api_response({"accepted": bool(marked)}, status=drf_status.HTTP_202_ACCEPTED)


delivery_tracker_webhook_view.cls.throttle_scope = THROTTLE_SCOPE
