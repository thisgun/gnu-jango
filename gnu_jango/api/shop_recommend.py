"""Product recommendation mail (youngcart shop/itemrecommend.php + itemrecommendmail.php).

Members only, one recipient per mail, and a per-member rate limit: an open "send this text to any
address" endpoint would be a spam relay. youngcart allows one mail per 120 seconds and three per
session; here the "shop-recommend" throttle scope (5/hour by default) does that job.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import UserRateThrottle

from gnu_jango.shop import notifications

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from .shop_common import on_sale_products, request_data, require_user

RECOMMEND_SCOPE = "shop-recommend"
DEFAULT_RECOMMEND_RATE = "5/hour"
SUBJECT_MAX = 200
CONTENT_MAX = 3000


class RecommendMailThrottle(UserRateThrottle):
    """Per member. Checked only when a valid mail is about to go out, so a typo in the form does
    not use up the member's allowance."""

    scope = RECOMMEND_SCOPE

    def get_rate(self):
        rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
        return rates.get(self.scope) or DEFAULT_RECOMMEND_RATE


def invalid(field, message):
    return api_error(message, status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error", details={field: message})


def recipient_error(to_email):
    if not to_email or to_email.count("@") != 1 or any(char in to_email for char in ",; \r\n"):
        return invalid("to_email", "Enter one valid recipient email address.")
    try:
        validate_email(to_email)
    except ValidationError:
        return invalid("to_email", "Enter one valid recipient email address.")
    return None


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def product_recommend_view(request, it_id):
    user, error = require_user(request)
    if error:
        return error
    product = on_sale_products().filter(pk=it_id).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    if not notifications.mail_enabled():
        return api_error(
            "Sending mail is disabled on this site.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="mail_disabled",
        )
    data = request_data(request)
    to_email = str(data.get("to_email") or "").strip()
    error = recipient_error(to_email)
    if error:
        return error
    subject = notifications.single_line(data.get("subject"), SUBJECT_MAX + 1)
    if not subject:
        return invalid("subject", "Subject is required.")
    if len(subject) > SUBJECT_MAX:
        return invalid("subject", "Subject is too long.")
    content = str(data.get("content") or "").strip()
    if not content:
        return invalid("content", "Content is required.")
    if len(content) > CONTENT_MAX:
        return invalid("content", "Content is too long.")
    throttle = RecommendMailThrottle()
    if not throttle.allow_request(request, None):
        wait = throttle.wait()
        return api_error(
            "Too many recommendation mails. Try again later.",
            status=drf_status.HTTP_429_TOO_MANY_REQUESTS,
            code="throttled",
            details={"retry_after": int(wait) if wait else None},
        )
    if not notifications.send_product_recommend_mail(request, product, user, to_email, subject, content):
        return api_error(
            "The mail could not be sent. Try again later.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="mail_send_failed",
        )
    return api_response(data={"sent": True, "it_id": product.it_id})
