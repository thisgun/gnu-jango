"""POST /api/v1/shop/orders/<od_id>/cash-receipt: the customer asks for a cash receipt after the
order (youngcart shop/taxsave.php, opened from orderinquiryview.php).

Only the order's owner may ask: the member who placed it, or for a guest order whoever holds the
order's uid (given out by the order lookup with order number and password, or at checkout). The
endpoint is throttled per address or member, as each try may reach Toss."""

import hmac

from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.shop.cash_receipts import CashReceiptError, request_cash_receipt
from gnu_jango.shop.models import ShopOrder

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from .shop_common import current_user, request_data

THROTTLE_SCOPE = "shop-cash-receipt"


def owned_order(request, od_id, uid):
    """The order when the caller owns it, else None (the same answer for a missing order)."""
    order = ShopOrder.objects.filter(pk=str(od_id or "").strip()).first()
    if order is None:
        return None
    user = current_user(request)
    if order.user_id is not None:
        return order if user and user.is_authenticated and user.pk == order.user_id else None
    uid = str(uid or "")
    return order if uid and hmac.compare_digest(uid.encode("utf-8"), str(order.uid).encode("utf-8")) else None


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser, FormParser])
@throttle_classes([ScopedRateThrottle])
def order_cash_receipt_view(request, od_id):
    from .v1_shop import order_payload

    data = request_data(request)
    order = owned_order(request, od_id, request.query_params.get("uid") or data.get("uid"))
    if order is None:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    user = current_user(request)
    try:
        result = request_cash_receipt(
            order,
            data.get("od_cash_type") or data.get("cash_type"),
            data.get("cash_receipt_registration_number") or data.get("identity"),
            actor=user.get_username() if user and user.is_authenticated else "guest",
        )
    except CashReceiptError as exc:
        return api_error(str(exc), status=exc.status, code=exc.code)
    order.refresh_from_db()
    return api_response(data={"issued": result.issued, "message": result.message, "order": order_payload(order, detail=True)})


order_cash_receipt_view.cls.throttle_scope = THROTTLE_SCOPE
