"""정기구독 API for members (the service is gnu_jango/shop/subscriptions.py).

- POST shop/subscriptions/start: product line, cycle and delivery address -> a pending card
  registration (registration_token, customerKey, client key) for the Toss billing window.
- POST shop/subscriptions/billing-auth: the success page sends the token back with the authKey and
  customerKey Toss added to successUrl; the server issues and seals the billing key and charges
  the first cycle. The billing key never leaves the server.
- POST shop/subscriptions/billing-auth/cancel: the fail page forgets the registration.
- GET shop/subscriptions[/<id>], POST shop/subscriptions/<id>/action (pause, resume, skip, cycle,
  cancel) and POST shop/subscriptions/<id>/card (re-register the card).

Every endpoint needs the signed-in member (cookie JWT, which runs Django's CSRF check, or Basic),
answers 404 while subscriptions are switched off, and only ever finds the member's own rows.
Card registrations are throttled (scope "shop-subscription").
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.shop import subscriptions as service
from gnu_jango.shop.models import ShopProduct, ShopSubscription

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .contracts import envelope
from .contracts.subscriptions import (
    ShopSubscriptionBillingResultSerializer,
    ShopSubscriptionDetailSerializer,
    ShopSubscriptionRegistrationSerializer,
    ShopSubscriptionSerializer,
)
from .response import api_error, api_response
from .shop_common import PRODUCT_LINE_IMAGE_WIDTH, first_value, product_thumbnail_url, request_data, require_user

THROTTLE_SCOPE = "shop-subscription"
LIST_LIMIT = 50
CHARGE_HISTORY_LIMIT = 24
STATUS_LABELS = dict(ShopSubscription.STATUS_CHOICES)
PAUSE_LABELS = dict(ShopSubscription.PAUSE_CHOICES)
CHARGE_LABELS = dict(service.Charge.STATUS_CHOICES)


def service_error(exc):
    return api_error(str(exc), status=exc.status, code=exc.code, details=exc.details or None)


def member_or_error(request):
    """(user, None) for a signed-in member while the feature is on, else (None, error response)."""
    user, error = require_user(request)
    if error:
        return None, error
    if not service.feature_enabled():
        return None, api_error(
            "Subscriptions are not available.", status=drf_status.HTTP_404_NOT_FOUND, code="subscription_unavailable"
        )
    return user, None


def charge_payload(charge):
    return {
        "id": charge.pk,
        "cycle_no": charge.cycle_no,
        "attempt": charge.attempt,
        "scheduled_date": charge.scheduled_date.isoformat(),
        "status": charge.status,
        "status_label": CHARGE_LABELS.get(charge.status, charge.status),
        "amount": charge.amount,
        "order_id": charge.od_id if charge.order_id else "",
        "failure_message": charge.failure_message,
        "created_at": charge.created_at.isoformat(),
    }


def subscription_payload(sub, *, detail=False, product=None):
    product = product if product is not None else (
        ShopProduct.objects.filter(pk=sub.it_id).first() if sub.it_id else None
    )
    active = sub.status != ShopSubscription.STATUS_CANCELLED
    cycles = service.product_cycles(product) if product is not None else ()
    has_card = bool(sub.card_number or sub.card_company)
    data = {
        "id": sub.pk,
        "status": sub.status,
        "status_label": STATUS_LABELS.get(sub.status, sub.status),
        "pause_reason": sub.pause_reason,
        "pause_reason_label": PAUSE_LABELS.get(sub.pause_reason, "") if sub.pause_reason else "",
        "it_id": sub.it_id,
        "it_name": sub.it_name,
        "io_id": sub.io_id,
        "option_label": " / ".join(part for part in sub.io_id.split("\x1e") if part),
        "qty": sub.qty,
        "cycle": sub.cycle,
        "cycle_label": service.CYCLE_LABELS.get(sub.cycle, sub.cycle),
        "cycle_choices": [{"value": cycle, "label": service.CYCLE_LABELS[cycle]} for cycle in cycles],
        "discount_rate": service.discount_rate(product) if product is not None else 0,
        "next_charge_date": service.due_date(sub).isoformat() if active and service.due_date(sub) else None,
        "retry_date": sub.retry_date.isoformat() if active and sub.retry_date else None,
        "cycle_no": sub.cycle_no,
        "failure_count": sub.failure_count,
        "estimated_amount": service.estimated_amount(sub, product) if active else None,
        "card": {"company": sub.card_company, "number": sub.card_number, "type": sub.card_type} if has_card else None,
        "delivery": {
            "name": sub.od_b_name, "tel": sub.od_b_tel, "hp": sub.od_b_hp, "zip": sub.od_b_zip,
            "addr1": sub.od_b_addr1, "addr2": sub.od_b_addr2, "addr3": sub.od_b_addr3,
        },
        "image_url": product_thumbnail_url(product, PRODUCT_LINE_IMAGE_WIDTH) if product is not None else "",
        "last_error": sub.last_error,
        "charge_in_progress": sub.charges.filter(status=service.Charge.STATUS_PENDING).exists(),
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
        "created_at": sub.created_at.isoformat(),
    }
    if detail:
        data["charges"] = [charge_payload(charge) for charge in sub.charges.all()[:CHARGE_HISTORY_LIMIT]]
    return data


@extend_schema(responses=envelope("ShopSubscriptions", ShopSubscriptionSerializer(many=True)))
@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def subscriptions_view(request):
    user, error = member_or_error(request)
    if error:
        return error
    rows = (
        ShopSubscription.objects.filter(user=user)
        .exclude(status=ShopSubscription.STATUS_PENDING)
        .order_by("-created_at", "-pk")[:LIST_LIMIT]
    )
    products = ShopProduct.objects.in_bulk({sub.it_id for sub in rows})
    return api_response(data=[subscription_payload(sub, product=products.get(sub.it_id)) for sub in rows])


def owned_subscription(user, pk):
    return ShopSubscription.objects.filter(user=user, pk=pk).exclude(status=ShopSubscription.STATUS_PENDING).first()


def not_found():
    return api_error("Subscription not found.", status=drf_status.HTTP_404_NOT_FOUND, code="subscription_not_found")


@extend_schema(responses=envelope("ShopSubscriptionDetail", ShopSubscriptionDetailSerializer()))
@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def subscription_detail_view(request, pk):
    user, error = member_or_error(request)
    if error:
        return error
    sub = owned_subscription(user, pk)
    if sub is None:
        return not_found()
    return api_response(data=subscription_payload(sub, detail=True))


@extend_schema(responses={201: envelope("ShopSubscriptionRegistration", ShopSubscriptionRegistrationSerializer())})
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def subscription_start_view(request):
    user, error = member_or_error(request)
    if error:
        return error
    try:
        registration = service.start_subscription(user, request_data(request))
    except service.SubscriptionError as exc:
        return service_error(exc)
    return api_response(data=registration, status=drf_status.HTTP_201_CREATED)


@extend_schema(responses={200: envelope("ShopSubscriptionCardRegistration", ShopSubscriptionRegistrationSerializer())})
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def subscription_card_view(request, pk):
    user, error = member_or_error(request)
    if error:
        return error
    try:
        registration = service.start_card_change(user, pk)
    except service.SubscriptionError as exc:
        return service_error(exc)
    return api_response(data=registration)


@extend_schema(responses={200: envelope("ShopSubscriptionBillingResult", ShopSubscriptionBillingResultSerializer())})
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def subscription_billing_auth_view(request):
    user, error = member_or_error(request)
    if error:
        return error
    data = request_data(request)
    try:
        sub, result = service.complete_registration(
            user,
            first_value(data, "registration_token", "token"),
            first_value(data, "authKey", "auth_key"),
            first_value(data, "customerKey", "customer_key"),
        )
    except service.SubscriptionError as exc:
        return service_error(exc)
    return api_response(data={
        "subscription": subscription_payload(sub, detail=True),
        "order_id": result.order_id if result else "",
        "charge_status": result.status if result else "",
    })


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def subscription_billing_cancel_view(request):
    user, error = member_or_error(request)
    if error:
        return error
    data = request_data(request)
    discarded = service.discard_registration(user, str(first_value(data, "registration_token", "token") or ""))
    return api_response(data={"discarded": discarded})


@extend_schema(responses={200: envelope("ShopSubscriptionAction", ShopSubscriptionDetailSerializer())})
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def subscription_action_view(request, pk):
    user, error = member_or_error(request)
    if error:
        return error
    data = request_data(request)
    try:
        sub = service.member_action(
            user, pk, str(data.get("action") or "").strip(), cycle=str(data.get("cycle") or "").strip()
        )
    except service.SubscriptionError as exc:
        return service_error(exc)
    return api_response(data=subscription_payload(sub, detail=True))


for _view in (
    subscription_start_view,
    subscription_card_view,
    subscription_billing_auth_view,
    subscription_billing_cancel_view,
):
    # each card registration may reach the Toss billing API
    _view.cls.throttle_scope = THROTTLE_SCOPE
