"""The customer's return (반품) and exchange (교환) requests of an order (shop/returns.py).

* ``GET  /api/v1/shop/orders/<od_id>/returns`` - the lines that may be asked for and the requests
* ``POST /api/v1/shop/orders/<od_id>/returns`` - ask: ``{kind, reason, detail, lines: [{line_id, qty}]}``
* ``POST /api/v1/shop/orders/<od_id>/returns/<request_id>/withdraw`` - take back a waiting request

Only the order's owner may use them: the member who placed it, or for a guest order whoever holds
the order's uid (shop_cash_receipts.owned_order); anyone else gets the same 404 as for a missing
order. The writes are throttled per member or address."""

from drf_spectacular.utils import extend_schema
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
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

from gnu_jango.shop.returns import ReturnRequestError, create_request, customer_payload, withdraw_request

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .contracts import envelope
from .contracts.returns import ShopOrderReturnsSerializer, ShopReturnCreateSerializer
from .response import api_error, api_response
from .shop_cash_receipts import owned_order
from .shop_common import current_user, request_data

THROTTLE_SCOPE = "shop-return-request"
RETURNS_ENVELOPE = envelope("ShopOrderReturns", ShopOrderReturnsSerializer())


class ReturnRequestThrottle(ScopedRateThrottle):
    """Throttles the writes only; reading the order page's return state is not limited."""

    def allow_request(self, request, view):
        if request.method == "GET":
            return True
        return super().allow_request(request, view)


def _caller_order(request, od_id):
    return owned_order(request, od_id, request.query_params.get("uid") or request_data(request).get("uid"))


def _not_found():
    return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")


@extend_schema(methods=["GET"], responses=RETURNS_ENVELOPE)
@extend_schema(methods=["POST"], request=ShopReturnCreateSerializer, responses={201: RETURNS_ENVELOPE})
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser])
@throttle_classes([ReturnRequestThrottle])
def order_returns_view(request, od_id):
    order = _caller_order(request, od_id)
    if order is None:
        return _not_found()
    if request.method == "GET":
        return api_response(data=customer_payload(order))
    data = request_data(request)
    try:
        create_request(
            order,
            kind=data.get("kind"),
            reason=data.get("reason"),
            detail=data.get("detail"),
            lines=data.get("lines"),
            user=current_user(request),
        )
    except ReturnRequestError as exc:
        return api_error(exc.message, status=exc.status, code=exc.code)
    return api_response(data=customer_payload(order), status=drf_status.HTTP_201_CREATED)


@extend_schema(request=None, responses=RETURNS_ENVELOPE)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser])
@throttle_classes([ReturnRequestThrottle])
def order_return_withdraw_view(request, od_id, request_id):
    order = _caller_order(request, od_id)
    if order is None:
        return _not_found()
    try:
        withdraw_request(order, request_id)
    except ReturnRequestError as exc:
        return api_error(exc.message, status=exc.status, code=exc.code)
    return api_response(data=customer_payload(order))


order_returns_view.cls.throttle_scope = THROTTLE_SCOPE
order_return_withdraw_view.cls.throttle_scope = THROTTLE_SCOPE
