"""Member leave and the e-mail certify endpoints of the v1 API.

bbs/member_leave.php + lib/common.lib.php g5_leave_member, bbs/email_certify.php and
bbs/register_email_update.php of Gnuboard5.
"""

import json

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile

from .community_common import User, _request_data, _require_user, _text
from .member_certify import (
    PasswordCheckThrottle,
    check_email_certify_token,
    flush_auth_session,
    email_certify_enabled,
    is_email_certified,
    new_email_certify_token,
    send_email_certify_mail,
)
from .auth_common import email_rule_error
from .response import api_error, api_response
from .v1_auth import SOCIAL_IDENTITY_PREFIX, _clear_auth_cookies, revoke_member_tokens

RESEND_COOLDOWN_SECONDS = 60
RESEND_COOLDOWN_KEY = "email_certify_resend_{}"


def _korean_date(day):
    return f"{day:%Y}년 {day:%m}월 {day:%d}일"


def _delete_social_links(user):
    """social_member_link_delete(): the member's social accounts are no longer linked."""
    for row in Config.objects.filter(name__startswith=SOCIAL_IDENTITY_PREFIX, value__contains=str(user.pk)):
        try:
            linked_id = json.loads(row.value).get("user_id")
        except (TypeError, ValueError, AttributeError):
            continue
        if linked_id == user.pk:
            row.delete()


def _site_admin_id():
    return (Config.objects.filter(name="cf_admin").values_list("value", flat=True).first() or "").strip()


def leave_member(user):
    """g5_leave_member(): record the leave date and clear the certification data. Returns the leave
    date, or None when the member already left (the update runs only on a member still present)."""
    today = timezone.localdate()
    with transaction.atomic():
        updated = Profile.objects.filter(user=user, leave_date__isnull=True).update(
            leave_date=today, email_certify_token=""
        )
        if not updated:
            return None
        User.objects.filter(pk=user.pk).update(is_active=False)
        _delete_social_links(user)
    revoke_member_tokens(user)
    return today


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([PasswordCheckThrottle])
def member_leave_view(request):
    user, error = _require_user(request)
    if error:
        return error
    if user.is_superuser or (_site_admin_id() and user.get_username() == _site_admin_id()):
        return api_error("최고 관리자는 탈퇴할 수 없습니다", status=status.HTTP_403_FORBIDDEN, code="super_admin_cannot_leave")

    data = _request_data(request)
    password = (_text(data.get("mb_password")) or _text(data.get("password"))).strip()
    if not password or not user.check_password(password):
        message = "비밀번호가 틀립니다."
        return api_error(
            message, status=status.HTTP_422_UNPROCESSABLE_ENTITY, code="invalid_password", details={"mb_password": message}
        )

    nickname = getattr(Profile.objects.filter(user=user).first(), "nickname", "") or user.get_username()
    left = leave_member(user)
    if not left:
        return api_error(
            "회원탈퇴를 처리하지 못했습니다. 회원 상태를 확인해 주십시오.",
            status=status.HTTP_409_CONFLICT,
            code="leave_failed",
        )

    response = api_response(
        data={
            "left": True,
            "mb_leave_date": left.strftime("%Y%m%d"),
            "message": f"{nickname}님께서는 {_korean_date(left)}에 회원에서 탈퇴 하셨습니다.",
        }
    )
    # The same sign-out as logout_view (and the PHP unset of ss_mb_id).
    _clear_auth_cookies(response)
    flush_auth_session(request)
    return response


def _certify_error(message, http_status, code):
    return api_error(message, status=http_status, code=code)


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([ScopedRateThrottle])
def email_certify_view(request):
    """email_certify.php: the mailed link certifies the address once, within cf_email_certify_minutes.
    POST only: the link opens the /email-certify page, which posts once it is on screen, so a mail
    scanner prefetching the link certifies nothing."""
    source = _request_data(request)
    mb_id = str(source.get("mb_id") or "").strip()
    token = str(source.get("token") or source.get("mb_md5") or "").strip()
    if not mb_id or not token:
        return _certify_error("제대로 된 값이 넘어오지 않았습니다.", status.HTTP_400_BAD_REQUEST, "invalid_request")

    user = User.objects.filter(username=mb_id).first()
    profile = Profile.objects.filter(user=user).select_related("user").first() if user else None
    # An unknown id gets the same answer as a wrong token, so the endpoint cannot list member ids.
    result = check_email_certify_token(token, profile) if profile else "invalid"
    if result == "invalid":
        return _certify_error("메일인증 요청 정보가 올바르지 않습니다.", status.HTTP_400_BAD_REQUEST, "email_certify_invalid")
    # Only told after the token matched, so nobody can probe which ids left or were blocked.
    if not user.is_active or profile.leave_date:
        return _certify_error("탈퇴 또는 차단된 회원입니다.", status.HTTP_403_FORBIDDEN, "inactive_member")

    stored = profile.email_certify_token
    if result == "expired":
        Profile.objects.filter(pk=profile.pk, email_certify_token=stored).update(email_certify_token="")
        return _certify_error(
            "메일인증 유효시간이 만료되었습니다. 인증메일을 다시 요청해 주십시오.",
            status.HTTP_410_GONE,
            "email_certify_expired",
        )

    # The link works once: the token is burnt in the same update that certifies.
    updated = Profile.objects.filter(pk=profile.pk, email_certify_token=stored).update(
        email_certify=timezone.now(), email_certify_token=""
    )
    if not updated:
        return _certify_error(
            "이미 처리되었거나 올바르지 않은 메일인증 요청입니다.", status.HTTP_409_CONFLICT, "email_certify_used"
        )
    return api_response(
        data={
            "certified": True,
            "mb_id": user.get_username(),
            "message": f"메일인증 처리를 완료 하였습니다.\n\n지금부터 {user.get_username()} 아이디로 로그인 가능합니다.",
        }
    )


def _resend_target_email(user, data):
    """register_email_update.php lets the member switch to another address before the resend.
    Returns (email, error response)."""
    wanted = (_text(data.get("mb_email")) or _text(data.get("email"))).strip()
    if not wanted or wanted == user.email:
        return user.email, None
    # The new address meets the signup rules (valid_mb_email, prohibit_mb_email), so a barred domain
    # cannot be reached by registering with another one and switching here.
    message = email_rule_error(wanted)
    if message:
        return None, api_error(
            message, status=status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error", details={"mb_email": message}
        )
    if User.objects.filter(email__iexact=wanted).exclude(pk=user.pk).exists():
        return None, api_error(
            f"{wanted} 메일은 이미 존재하는 메일주소 입니다.\n\n다른 메일주소를 입력해 주십시오.",
            status=status.HTTP_409_CONFLICT,
            code="email_exists",
        )
    return wanted, None


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([ScopedRateThrottle])
def email_certify_resend_view(request):
    """register_email_update.php: a member who cannot log in yet asks for a new certify link. The login
    is refused to them, so they prove who they are with the id and password the login screen took."""
    if not email_certify_enabled():
        return api_error("메일인증을 사용하지 않습니다.", status=status.HTTP_400_BAD_REQUEST, code="email_certify_disabled")
    data = _request_data(request)
    mb_id = (_text(data.get("mb_id")) or _text(data.get("username"))).strip()
    password = _text(data.get("mb_password")) or _text(data.get("password"))
    user = authenticate(request, username=mb_id, password=password) if mb_id and password else None
    if not user:
        return api_error("Invalid member ID or password.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_login")

    profile, _ = Profile.objects.get_or_create(user=user)
    if is_email_certified(profile):
        return api_error("이미 메일인증 하신 회원입니다.", status=status.HTTP_409_CONFLICT, code="email_already_certified")

    email, error = _resend_target_email(user, data)
    if error:
        return error
    cooldown_key = RESEND_COOLDOWN_KEY.format(user.pk)
    if not cache.add(cooldown_key, 1, RESEND_COOLDOWN_SECONDS):
        return api_error(
            "인증메일은 잠시 후 다시 요청해 주십시오.", status=status.HTTP_429_TOO_MANY_REQUESTS, code="too_many_requests"
        )

    previous_email, previous_token = user.email, profile.email_certify_token
    user.email = email
    profile.email_certify_token = new_email_certify_token()
    if not send_email_certify_mail(request, user, profile.email_certify_token):
        # The link mailed before keeps working when the new one could not be sent.
        user.email = previous_email
        cache.delete(cooldown_key)
        return api_error(
            "지금은 인증 메일을 보낼 수 없습니다. 관리자에게 문의해주세요.",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="mail_failed",
        )
    if email != previous_email:
        user.save(update_fields=["email"])
    Profile.objects.filter(pk=profile.pk, email_certify_token=previous_token).update(
        email_certify_token=profile.email_certify_token
    )
    return api_response(
        data={
            "sent": True,
            "mb_email": email,
            "message": f"인증메일을 {email} 메일로 다시 보내 드렸습니다.\n\n잠시후 {email} 메일을 확인하여 주십시오.",
        }
    )


email_certify_resend_view.cls.throttle_scope = "auth-login"
email_certify_view.cls.throttle_scope = "auth-token"
member_leave_view.cls.throttle_scope = "member-password"
