"""E-mail certification and open-profile rules of Gnuboard5, shared by the auth and member APIs.

lib/common.lib.php get_email_certify_token / is_valid_email_certify_token / is_use_email_certify,
register_form_update.php (the certify mail) and register_form.skin.php (cf_open_modify).
"""

import logging
import re
import secrets
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.config.models import Config
from gnu_jango.users import point_ledger
from gnu_jango.users.models import Profile

logger = logging.getLogger(__name__)

DEFAULT_CERTIFY_MINUTES = 60  # install/gnuboard5.sql cf_email_certify_minutes default
TOKEN_ISSUED_AT_RE = re.compile(r"\.([0-9]{10})$")


def _config_text(name, default=""):
    value = Config.objects.filter(name=name).values_list("value", flat=True).first()
    return default if value is None else str(value).strip()


def _config_int(name, default):
    try:
        return int(_config_text(name, str(default)) or 0)
    except ValueError:
        return default


def email_certify_enabled():
    """cf_use_email_certify."""
    return _config_int("cf_use_email_certify", 0) > 0


def social_certify_mail():
    """G5_SOCIAL_CERTIFY_MAIL (extend/social_login.extend.php, off by default): social members are
    exempt from the e-mail certification unless the site turns this on."""
    return bool(getattr(settings, "SOCIAL_CERTIFY_MAIL", False))


def email_certify_required(*, social=False):
    """is_use_email_certify(): with certification on, a social login or signup skips it unless
    SOCIAL_CERTIFY_MAIL is set."""
    if not email_certify_enabled():
        return False
    return social_certify_mail() if social else True


def email_certify_minutes():
    """How long a certify link stays valid; 0 (or less) means it never expires."""
    return _config_int("cf_email_certify_minutes", DEFAULT_CERTIFY_MINUTES)


def new_email_certify_token():
    """get_email_certify_token(): a one-time random value with its issue time."""
    return f"{secrets.token_hex(16)}.{int(timezone.now().timestamp())}"


def _token_issued_at(stored_token, date_joined):
    """get_email_certify_issued_at(): tokens without an issue time count from the join date."""
    match = TOKEN_ISSUED_AT_RE.search(stored_token or "")
    if match:
        return int(match.group(1))
    return int(date_joined.timestamp()) if date_joined else 0


def email_certify_expired(user, profile, valid_minutes=None, now=None):
    """Mirror is_expired_email_certify_member(): a resent token expires from its own issue time."""
    minutes = email_certify_minutes() if valid_minutes is None else int(valid_minutes)
    if minutes < 1 or profile.email_certify is not None or profile.leave_date:
        return False
    issued_at = _token_issued_at(profile.email_certify_token, user.date_joined)
    now_timestamp = int((now or timezone.now()).timestamp())
    return issued_at > 0 and issued_at + minutes * 60 < now_timestamp


def check_email_certify_token(token, profile):
    """'ok', 'expired' or 'invalid' (is_valid_email_certify_token). The token is compared first, so
    someone without it cannot learn whether a member's link expired."""
    stored = profile.email_certify_token or ""
    # Bytes, because compare_digest refuses non-ASCII text (a pasted Korean token would be a 500).
    if not token or not stored or not secrets.compare_digest(stored.encode("utf-8"), str(token).encode("utf-8")):
        return "invalid"
    minutes = email_certify_minutes()
    if minutes < 1:
        return "ok"
    issued_at = _token_issued_at(stored, profile.user.date_joined)
    if not issued_at:
        return "invalid"
    return "ok" if issued_at + minutes * 60 >= int(timezone.now().timestamp()) else "expired"


def is_email_certified(profile):
    return profile.email_certify is not None


def certification_pending(user):
    """True while cf_use_email_certify is on and the member's address awaits its certify link. Such a
    member is treated as signed out everywhere, so tokens issued before an e-mail change stop working
    (login_check.php refuses them a session). A member without a profile row counts as certified,
    like a newly created profile."""
    rows = list(Profile.objects.filter(user_id=user.pk).values_list("email_certify", flat=True)[:1])
    if not rows or rows[0] is not None:
        return False
    return email_certify_enabled()


def flush_auth_session(request):
    """The Django session of the member is ended as well (the PHP unset of ss_mb_id)."""
    django_request = getattr(request, "_request", request)
    session = getattr(django_request, "session", None)
    if session is not None and session.get("_auth_user_id"):
        auth_logout(django_request)


PASSWORD_FIELDS = ("mb_password", "mb_password_current", "current_password", "password")


class PasswordCheckThrottle(ScopedRateThrottle):
    """A scoped throttle (scope "member-password") for the endpoints that check the member's
    password, so a stolen access token cannot be used to guess it. Requests that carry no password
    (a plain profile edit) are not counted."""

    def allow_request(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        data = request.data if isinstance(request.data, dict) else {}
        if not any(data.get(field) for field in PASSWORD_FIELDS):
            return True
        return super().allow_request(request, view)


def site_url(request, path):
    """An absolute link to a page of the site (the Next.js site may live on its own origin, the
    same setting the social login and the password reset mail use)."""
    site = str(getattr(settings, "SOCIAL_APP_BASE_URL", "") or "").rstrip("/")
    return f"{site}{path}" if site else request.build_absolute_uri(path)


def email_certify_url(request, user, token):
    query = urllib.parse.urlencode({"mb_id": user.get_username(), "token": token})
    return site_url(request, f"/email-certify?{query}")


def send_email_certify_mail(request, user, token, *, changed=False):
    """register_form_update_mail3.php: the certify link, mailed to the member's address.
    Returns whether the mail went out."""
    title = _config_text("cf_title") or "GNU Jango"
    name = getattr(getattr(user, "profile", None), "realname", "") or user.first_name or user.get_username()
    lines = ["회원 인증 메일입니다.", ""]
    if changed:
        lines += [f"{name} 님의 E-mail 주소가 변경되었습니다.", ""]
    lines.append("아래의 주소를 클릭하시면 인증이 완료됩니다.")
    minutes = email_certify_minutes()
    if minutes > 0:
        lines.append(f"인증 링크는 발송 후 {minutes}분 동안 유효합니다.")
    lines += [email_certify_url(request, user, token), "", "회원님의 성원에 보답하고자 더욱 더 열심히 하겠습니다.", "감사합니다."]
    try:
        send_mail(f"[{title}] 인증확인 메일입니다.", "\n".join(lines), None, [user.email])
    except Exception:  # noqa: BLE001 - a mail server failure must not break the request
        logger.exception("E-mail certify mail could not be sent to user %s", user.pk)
        return False
    return True


def issue_email_certify(request, user, profile, *, changed=False):
    """Mark the address as not certified, store a new token and mail the link."""
    profile.email_certify = None
    profile.email_certify_token = new_email_certify_token()
    profile.save(update_fields=["email_certify", "email_certify_token"])
    return send_email_certify_mail(request, user, profile.email_certify_token, changed=changed)


def open_profile_change_error(profile, wanted):
    """register_form.skin.php: once changed, mb_open keeps for cf_open_modify days from mb_open_date.
    Returns the message refusing the change, or ''."""
    if bool(wanted) == bool(profile.open_profile):
        return ""
    days = point_ledger.config_points("cf_open_modify")
    changed = profile.open_profile_date
    if days <= 0 or not changed:
        return ""
    changed_day = timezone.localdate(changed)
    if changed_day > timezone.localdate() - timedelta(days=days):
        until = changed_day + timedelta(days=days)
        return f"정보공개는 수정후 {days}일 이내, {until:%Y}년 {until:%m}월 {until.day}일 까지는 변경이 안됩니다."
    return ""


def truthy_flag(value):
    """A checkbox sent as 1/0, true/false or "1"/"0"."""
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}
