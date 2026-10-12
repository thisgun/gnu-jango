"""Refresh-token-backed login sessions and revocation helpers."""

from datetime import datetime, timezone as datetime_timezone

from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from gnu_jango.users.models import Profile

from .response import api_error, api_response


def token_version_for_user(user):
    return Profile.objects.filter(user_id=user.pk).values_list("token_version", flat=True).first() or 0


def bump_token_version(user):
    """Move the member to a new token version: every access and refresh token stamped with an older
    one is refused from now on. The increment runs in the database, so two bumps never collapse."""
    Profile.objects.get_or_create(user=user)
    Profile.objects.filter(user=user).update(token_version=F("token_version") + 1)
    return token_version_for_user(user)


def revoke_member_tokens(user):
    """Sign the member out on every device: blacklist the refresh tokens (so their sessions and the
    access tokens bound to them end) and bump the token version (so tokens without a session claim end
    too). Used for a password change or reset, an e-mail change, a leave and a block."""
    revoke_refresh_tokens(user)
    return bump_token_version(user)


def _login_time(value):
    try:
        login_at = int(value)
    except (TypeError, ValueError):
        return None
    return login_at if login_at > 0 else None


def issue_refresh_token(user, request=None, login_at=None):
    """A refresh token that is its own login session: sid names the session (the token's jti, which
    every access token minted from it carries), tv the member's token version, lat the time the member
    signed in (kept across rotations), ua/ip the client that received it."""
    refresh = RefreshToken.for_user(user)
    refresh["tv"] = token_version_for_user(user)
    refresh["sid"] = refresh["jti"]
    refresh["lat"] = _login_time(login_at) or int(refresh["iat"])
    user_agent = request.headers.get("User-Agent") if request else ""
    remote_addr = request.META.get("REMOTE_ADDR") if request else ""
    refresh["ua"] = user_agent[:512] if isinstance(user_agent, str) else ""
    refresh["ip"] = remote_addr[:64] if isinstance(remote_addr, str) else ""
    OutstandingToken.objects.filter(user_id=user.pk, jti=refresh["jti"]).update(token=str(refresh))
    return refresh


def tokens_for_user(user, request=None):
    refresh = issue_refresh_token(user, request)
    access = refresh.access_token
    return str(access), str(refresh), int(access.lifetime.total_seconds())


def revoke_refresh_tokens(user):
    """Invalidate every outstanding refresh token issued to the member."""
    for token in OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True):
        BlacklistedToken.objects.get_or_create(token=token)


def _current_access_token(request):
    authorization = request.headers.get("Authorization") or ""
    raw_token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
    raw_token = raw_token or request.COOKIES.get("g5_token") or ""
    if not raw_token:
        return None
    try:
        return AccessToken(raw_token)
    except TokenError:
        return None


def current_session_id(request):
    access = _current_access_token(request)
    value = access.payload.get("sid") if access else None
    return value if isinstance(value, str) and value else ""


def _active_refresh_session(row, user):
    try:
        token = RefreshToken(row.token)
    except TokenError:
        return None
    payload = token.payload
    if (
        str(payload.get("user_id")) != str(user.pk)
        or payload.get("token_type") != "refresh"
        or payload.get("sid") != row.jti
        or payload.get("tv", 0) != token_version_for_user(user)
    ):
        return None
    return payload


def _session_payload(row, payload, current_jti):
    issued_at = row.created_at.isoformat() if row.created_at else ""
    login_at = _login_time(payload.get("lat"))
    current = bool(current_jti) and row.jti == current_jti
    user_agent = payload.get("ua")
    ip = payload.get("ip")
    return {
        "id": row.pk,
        "token_id": row.pk,
        "current": current,
        "device_label": "현재 사용 중인 브라우저" if current else "",
        "user_agent": user_agent[:512] if isinstance(user_agent, str) else "",
        "ip": ip[:64] if isinstance(ip, str) else "",
        # created_at: when the member signed in on this device; last_used_at: the latest refresh.
        "created_at": (
            datetime.fromtimestamp(login_at, tz=datetime_timezone.utc).isoformat() if login_at else issued_at
        ),
        "last_used_at": issued_at,
        "expires_at": row.expires_at.isoformat() if row.expires_at else "",
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def sessions_view(request):
    from .v1_auth import _auth_user_from_request

    user = _auth_user_from_request(request)
    if not user:
        return _not_authenticated()
    now = timezone.now()
    current_jti = current_session_id(request)
    sessions = []
    rows = OutstandingToken.objects.filter(
        user=user,
        expires_at__gt=now,
        blacklistedtoken__isnull=True,
    ).order_by("-created_at", "-pk")
    for row in rows:
        payload = _active_refresh_session(row, user)
        if payload is not None:
            sessions.append(_session_payload(row, payload, current_jti))
    return api_response(data={"sessions": sessions})


def _parse_session_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= 9_223_372_036_854_775_807 else None
    if isinstance(value, str) and value.isdecimal():
        if len(value) > 19:
            return None
        parsed = int(value)
        return parsed if 0 < parsed <= 9_223_372_036_854_775_807 else None
    return None


def _not_authenticated():
    return api_error(
        "Authentication credentials were not provided.",
        status=status.HTTP_401_UNAUTHORIZED,
        code="not_authenticated",
    )


def _revoke_session(request, user, token_id):
    """Blacklist one of the member's live refresh sessions; the access tokens minted from it stop at
    once because SessionJWTAuthentication checks their sid against it."""
    from .v1_auth import _clear_auth_cookies

    if token_id is None:
        return api_error(
            "로그인 세션 번호가 올바르지 않습니다.",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
        )
    row = OutstandingToken.objects.filter(
        pk=token_id,
        user=user,
        expires_at__gt=timezone.now(),
        blacklistedtoken__isnull=True,
    ).first()
    payload = _active_refresh_session(row, user) if row else None
    if not row or payload is None:
        return api_error(
            "로그인 세션을 찾을 수 없습니다.",
            status=status.HTTP_404_NOT_FOUND,
            code="session_not_found",
        )

    BlacklistedToken.objects.get_or_create(token=row)
    current = row.jti == current_session_id(request)
    response = api_response(data={"revoked": True, "current": current})
    if current:
        _clear_auth_cookies(response)
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def session_revoke_view(request):
    """POST /auth/sessions/revoke {token_id}: kept for older clients; DELETE /auth/sessions/<id> is the
    resource form of the same action."""
    from .v1_auth import _auth_user_from_request, _request_data

    user = _auth_user_from_request(request)
    if not user:
        return _not_authenticated()
    return _revoke_session(request, user, _parse_session_id(_request_data(request).get("token_id")))


@api_view(["DELETE"])
@permission_classes([AllowAny])
def session_detail_view(request, token_id):
    from .v1_auth import _auth_user_from_request

    user = _auth_user_from_request(request)
    if not user:
        return _not_authenticated()
    return _revoke_session(request, user, _parse_session_id(token_id))


def revoke_refresh_token(raw_token, user=None):
    try:
        refresh = RefreshToken(str(raw_token))
    except TokenError:
        return False
    if user and str(refresh.payload.get("user_id")) != str(user.pk):
        return False
    refresh.blacklist()
    return True


def revoke_current_session(request, user=None, refresh_token=""):
    current_jti = current_session_id(request)
    if current_jti and user:
        row = OutstandingToken.objects.filter(
            jti=current_jti,
            user=user,
            expires_at__gt=timezone.now(),
            blacklistedtoken__isnull=True,
        ).first()
        if row:
            BlacklistedToken.objects.get_or_create(token=row)
            return True
    if refresh_token:
        return revoke_refresh_token(refresh_token, user)

    access = _current_access_token(request)
    if not access or not user or str(access.payload.get("user_id")) != str(user.pk):
        return False
    jti = access.payload.get("jti")
    if not jti:
        return False
    expires_at = datetime.fromtimestamp(int(access.payload["exp"]), tz=datetime_timezone.utc)
    row, _ = OutstandingToken.objects.get_or_create(
        jti=jti,
        defaults={"user": user, "token": str(access), "expires_at": expires_at},
    )
    BlacklistedToken.objects.get_or_create(token=row)
    return True
