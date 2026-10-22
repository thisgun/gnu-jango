"""Product recommendation mail (youngcart shop/itemrecommend.php + itemrecommendmail.php).

Members only, one recipient per mail, and rate limits: an open "send this text to any address"
endpoint would be a spam relay. youngcart allows one mail per 120 seconds and three per session;
here the "shop-recommend" scope (5/hour per member) and the "shop-recommend-ip" scope (10/hour per
address, so a batch of fresh accounts cannot multiply the allowance) do that job.

The sender must be a member for at least a day (a throwaway account cannot send at once) and, when
the site uses e-mail certification (cf_use_email_certify), have a certified address. The message is
capped at 1,000 characters. youngcart sends the mail From the member's own address
(itemrecommendmail.php mailer($from_name, $from_email, ...)); here it leaves from the shop's
address and the member is the Reply-To, so replies still reach them without failing SPF/DMARC.
The mail goes out once the request's transaction commits (on_commit).
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from gnu_jango.shop import notifications

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from .shop_common import on_sale_products, request_data, require_user

RECOMMEND_SCOPE = "shop-recommend"
RECOMMEND_IP_SCOPE = "shop-recommend-ip"
DEFAULT_RECOMMEND_RATE = "5/hour"
DEFAULT_RECOMMEND_IP_RATE = "10/hour"
SUBJECT_MAX = 200
CONTENT_MAX = 1000
MIN_ACCOUNT_AGE = timedelta(days=1)


def _configured_rate(scope, default):
    rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
    return rates.get(scope) or default


class RecommendMailThrottle(UserRateThrottle):
    """Per member. Checked only when a valid mail is about to go out, so a typo in the form does
    not use up the member's allowance."""

    scope = RECOMMEND_SCOPE

    def get_rate(self):
        return _configured_rate(self.scope, DEFAULT_RECOMMEND_RATE)


class RecommendMailIpThrottle(SimpleRateThrottle):
    """Per address, whichever account sends."""

    scope = RECOMMEND_IP_SCOPE

    def get_rate(self):
        return _configured_rate(self.scope, DEFAULT_RECOMMEND_IP_RATE)

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def sender_error(user):
    """Why ``user`` may not send recommendation mails yet (None when they may)."""
    from gnu_jango.users.models import Profile

    from .member_certify import email_certify_enabled

    if user.is_staff or user.is_superuser:
        return None
    joined = getattr(user, "date_joined", None)
    if joined and timezone.now() - joined < MIN_ACCOUNT_AGE:
        return api_error(
            "가입 후 하루가 지나야 상품을 추천하는 메일을 보낼 수 있습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="recommend_account_too_new",
        )
    if email_certify_enabled() and not Profile.objects.filter(user_id=user.pk, email_certify__isnull=False).exists():
        return api_error(
            "메일 인증을 마친 회원만 상품을 추천하는 메일을 보낼 수 있습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="recommend_email_not_certified",
        )
    return None


def throttled(throttle):
    wait = throttle.wait()
    return api_error(
        "Too many recommendation mails. Try again later.",
        status=drf_status.HTTP_429_TOO_MANY_REQUESTS,
        code="throttled",
        details={"retry_after": int(wait) if wait else None},
    )


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
    error = sender_error(user)
    if error:
        return error
    for throttle in (RecommendMailIpThrottle(), RecommendMailThrottle()):
        if not throttle.allow_request(request, None):
            return throttled(throttle)
    results = []
    transaction.on_commit(
        lambda: results.append(notifications.send_product_recommend_mail(request, product, user, to_email, subject, content))
    )
    if results and not results[0]:
        return api_error(
            "The mail could not be sent. Try again later.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="mail_send_failed",
        )
    # outside a transaction the mail went out just now; inside one it leaves on commit
    return api_response(data={"sent": bool(results), "queued": not results, "it_id": product.it_id})
