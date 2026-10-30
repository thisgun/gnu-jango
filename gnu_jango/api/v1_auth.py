import base64
import hashlib
import hmac
import json
import re
import secrets
import socket
import urllib.error as urllib_error
import urllib.parse
import urllib.request as urllib_request

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.config.models import Config
from gnu_jango.shop.signup_coupon import issue_signup_coupon
from gnu_jango.shop.sms.notifications import queue_member_join_sms
from gnu_jango.users import point_ledger
from gnu_jango.users.models import Profile

from .response import api_error, api_response
from .authentication import SessionJWTAuthentication as JWTAuthentication
from .contracts import envelope
from .contracts.auth import AuthMeSerializer
from .auth_sessions import (  # noqa: F401 - urls and other api modules import these from v1_auth
    bump_token_version,
    issue_refresh_token,
    revoke_current_session,
    revoke_member_tokens,
    revoke_refresh_tokens,
    session_detail_view,
    session_revoke_view,
    sessions_view,
    token_version_for_user,
    tokens_for_user as _tokens_for_user,
)
from .member_certify import (
    certification_pending,
    email_certify_required,
    is_email_certified,
    new_email_certify_token,
    send_email_certify_mail,
    truthy_flag,
)
from .auth_common import (  # noqa: F401 - urls, tests and commands import these from v1_auth
    _config_value,
    _current_origin,
    _form_text,
    _has_control_character,
    _is_loopback_host,
    _iter_configured_origins,
    NICKNAME_MARKUP_CHARACTERS,
    _normalize_origin,
    _setting_value,
    _strip_markup,
    _truthy,
    email_rule_error,
    nickname_rule_error,
    reserved_member_id_error,
)
from .auth_captcha import (  # noqa: F401 - urls, tests and commands import these from v1_auth
    CAPTCHA_ALPHABET,
    CAPTCHA_ATTEMPT_SESSION_KEY,
    CAPTCHA_MAX_FAILURES,
    CAPTCHA_SESSION_KEY,
    _captcha_audio,
    _captcha_audio_roots,
    _captcha_font,
    _captcha_image,
    _captcha_matches,
    _captcha_mp3_audio,
    _captcha_tone_audio,
    _consume_captcha,
    _new_captcha_code,
    _no_cache_audio_response,
    _store_captcha,
    captcha_audio_view,
    captcha_view,
)
from .auth_cert import (  # noqa: F401 - urls, tests and commands import these from v1_auth
    CERT_RETURN_ORIGIN_SESSION_KEY,
    _cert_adapter_url,
    _cert_allowed_post_message_origins,
    _cert_bridge_html,
    _cert_config_payload,
    _cert_error_and_close,
    _cert_int_value,
    _cert_method_enabled,
    _cert_origin_allowed,
    _cert_page_type,
    _cert_post_message_origin,
    _cert_provider_value,
    _cert_result_view,
    _cert_start_view,
    _cert_value,
    cert_config_view,
    cert_inicis_result_view,
    cert_inicis_start_view,
    cert_kcp_result_view,
    cert_kcp_start_view,
    cert_kcp_v2_result_view,
    cert_kcp_v2_start_view,
)

User = get_user_model()
MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
SOCIAL_STATE_SESSION_PREFIX = "g5_social_oauth_"
SOCIAL_TICKET_PREFIX = "social_ticket_"
SOCIAL_IDENTITY_PREFIX = "social_id_"
SOCIAL_TICKET_TTL_SECONDS = 10 * 60
# A random value kept in the session of the browser that starts a social login; tickets carry only its
# hash, and are redeemed only where the session still holds it (no login CSRF with a leaked ticket).
SOCIAL_BINDING_SESSION_KEY = "g5_social_binding"
# A native app cannot share the system browser's cookies, so it starts the flow with an RFC 7636 style
# S256 client_challenge and redeems the ticket with the matching client_verifier.
SOCIAL_CLIENT_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")
SOCIAL_CLIENT_VERIFIER_RE = re.compile(r"[A-Za-z0-9._~-]{43,128}")
SOCIAL_TOKEN_TIMEOUT_SECONDS = 10

SOCIAL_PROVIDER_SPECS = {
    "naver": {
        "label": "Naver",
        "config_client_id": "cf_naver_clientid",
        "config_secret": "cf_naver_secret",
        "setting_client_id": "SOCIAL_NAVER_CLIENT_ID",
        "setting_secret": "SOCIAL_NAVER_CLIENT_SECRET",
        "authorize_url": "https://nid.naver.com/oauth2.0/authorize",
        "token_url": "https://nid.naver.com/oauth2.0/token",
        "userinfo_url": "https://openapi.naver.com/v1/nid/me",
        "requires_secret": True,
    },
    "kakao": {
        "label": "Kakao",
        "config_client_id": "cf_kakao_rest_key",
        "config_secret": "cf_kakao_client_secret",
        "setting_client_id": "SOCIAL_KAKAO_REST_KEY",
        "setting_secret": "SOCIAL_KAKAO_CLIENT_SECRET",
        "authorize_url": "https://kauth.kakao.com/oauth/authorize",
        "token_url": "https://kauth.kakao.com/oauth/token",
        "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        "requires_secret": False,
    },
    "google": {
        "label": "Google",
        "config_client_id": "cf_google_clientid",
        "config_secret": "cf_google_secret",
        "setting_client_id": "SOCIAL_GOOGLE_CLIENT_ID",
        "setting_secret": "SOCIAL_GOOGLE_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "requires_secret": True,
    },
    "facebook": {
        "label": "Facebook",
        "config_client_id": "cf_facebook_appid",
        "config_secret": "cf_facebook_secret",
        "setting_client_id": "SOCIAL_FACEBOOK_APP_ID",
        "setting_secret": "SOCIAL_FACEBOOK_APP_SECRET",
        "authorize_url": "https://www.facebook.com/dialog/oauth",
        "token_url": "https://graph.facebook.com/oauth/access_token",
        "userinfo_url": "https://graph.facebook.com/me",
        "userinfo_params": {"fields": "id,name,email,picture.type(large)"},
        "scope": "email,public_profile",
        "requires_secret": True,
    },
    "twitter": {
        "label": "Twitter/X",
        "config_client_id": "cf_twitter_key",
        "config_secret": "cf_twitter_secret",
        "setting_client_id": "SOCIAL_TWITTER_CLIENT_ID",
        "setting_secret": "SOCIAL_TWITTER_CLIENT_SECRET",
        "authorize_url": "https://x.com/i/oauth2/authorize",
        "token_url": "https://api.x.com/2/oauth2/token",
        "userinfo_url": "https://api.x.com/2/users/me",
        "userinfo_params": {"user.fields": "id,name,username,confirmed_email,profile_image_url"},
        "scope": "tweet.read users.read users.email",
        "requires_secret": False,
        "requires_pkce": True,
    },
    "payco": {
        "label": "Payco",
        "config_client_id": "cf_payco_clientid",
        "config_secret": "cf_payco_secret",
        "setting_client_id": "SOCIAL_PAYCO_CLIENT_ID",
        "setting_secret": "SOCIAL_PAYCO_CLIENT_SECRET",
        "setting_service_provider_code": "SOCIAL_PAYCO_SERVICE_PROVIDER_CODE",
        "authorize_url": "https://id.payco.com/oauth2.0/authorize",
        "token_url": "https://id.payco.com/oauth2.0/token",
        "userinfo_url": "https://apis-payco.krp.toastoven.net/payco/friends/find_member_v2.json",
        "requires_secret": True,
        "requires_service_provider_code": True,
    },
}


class SocialOAuthError(Exception):
    def __init__(self, message, *, code="social_oauth_failed", status_code=400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _request_data(request):
    return request.data if isinstance(request.data, dict) else {}


def _split_provider_list(value):
    return {item.strip().lower() for item in str(value or "").replace("|", ",").split(",") if item.strip()}


SOCIAL_GLOBAL_CONFIG_NAMES = ("cf_social_login_use", "cf_social_servicelist")


def _social_config_values():
    """Every Config value the provider list needs, in one query (it is fetched on every page)."""
    names = set(SOCIAL_GLOBAL_CONFIG_NAMES)
    for spec in SOCIAL_PROVIDER_SPECS.values():
        names.update(name for name in (spec.get("config_client_id"), spec.get("config_secret")) if name)
    try:
        return {name: str(value) for name, value in Config.objects.filter(name__in=names).values_list("name", "value") if value is not None}
    except Exception:
        return None


def _provider_config(provider_name, config_values=None):
    """config_values: Config values read in advance (_social_config_values); None reads each one."""
    provider = str(provider_name or "").strip().lower()
    spec = SOCIAL_PROVIDER_SPECS.get(provider)
    if not spec:
        return None

    def config_value(name, default=""):
        if config_values is None:
            return _config_value(name, default)
        return config_values.get(name, default) if name else default

    client_id = _setting_value(spec.get("setting_client_id", "")) or config_value(spec.get("config_client_id", ""))
    client_secret = _setting_value(spec.get("setting_secret", "")) or config_value(spec.get("config_secret", ""))
    service_provider_code = _setting_value(spec.get("setting_service_provider_code", ""))
    configured_from_env = bool(_setting_value(spec.get("setting_client_id", "")))
    has_required_secret = bool(client_secret) or not spec.get("requires_secret", False)
    has_required_service_code = bool(service_provider_code) or not spec.get("requires_service_provider_code", False)
    has_api_key = bool(client_id and has_required_secret and has_required_service_code)

    global_enabled = _truthy(config_value("cf_social_login_use", "0"))
    service_list = _split_provider_list(config_value("cf_social_servicelist", ""))
    provider_allowed = not service_list or provider in service_list
    enabled = has_api_key and (configured_from_env or (global_enabled and provider_allowed))

    return {
        "name": provider,
        "label": spec.get("label", provider.title()),
        "client_id": str(client_id or "").strip(),
        "client_secret": str(client_secret or "").strip(),
        "authorize_url": spec.get("authorize_url", ""),
        "token_url": spec.get("token_url", ""),
        "userinfo_url": spec.get("userinfo_url", ""),
        "userinfo_params": spec.get("userinfo_params", {}),
        "scope": spec.get("scope", ""),
        "service_provider_code": service_provider_code,
        "has_api_key": has_api_key,
        "enabled": enabled,
    }


def _configured_social_providers():
    providers = []
    config_values = _social_config_values()
    for name in SOCIAL_PROVIDER_SPECS:
        config = _provider_config(name, config_values)
        providers.append(
            {
                "name": name,
                "label": config["label"] if config else SOCIAL_PROVIDER_SPECS[name].get("label", name.title()),
                "has_api_key": bool(config and config["has_api_key"]),
                "enabled": bool(config and config["enabled"]),
            }
        )
    return providers


def _allowed_social_redirect_origins(request):
    origins = {_normalize_origin(_current_origin(request))}
    configured = _setting_value("SOCIAL_APP_BASE_URL")
    if configured:
        origin = _normalize_origin(configured)
        if origin:
            origins.add(origin)

    origins.update(_iter_configured_origins(getattr(settings, "SOCIAL_ALLOWED_REDIRECT_ORIGINS", [])))
    return {origin for origin in origins if origin}


def _safe_social_redirect_url(request, value, fallback_path):
    """Where the browser goes back to: a path on this site, or an address on this site or on a configured
    front-end origin. Anything else, including a protocol-relative "//host" address and a value with a
    control character (the legacy redirect check refuses those too), falls back to fallback_path."""
    fallback = request.build_absolute_uri(fallback_path)
    raw = value.strip() if isinstance(value, str) else ""
    if not raw or _has_control_character(raw):
        return fallback

    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return fallback

    if not parsed.scheme and not parsed.netloc:
        if raw.startswith("/") and url_has_allowed_host_and_scheme(raw, allowed_hosts={request.get_host()}):
            return request.build_absolute_uri(raw)
        return fallback

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return fallback
    # Django reads a backslash as a slash the way browsers do; an address whose host changes under that
    # reading ("http://evil.example\@site/") is refused.
    if not url_has_allowed_host_and_scheme(raw, allowed_hosts={parsed.netloc}):
        return fallback

    origin = _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
    if origin in _allowed_social_redirect_origins(request):
        return raw
    if settings.DEBUG and _is_loopback_host(parsed.hostname):
        return raw
    return fallback


def _append_query(url, values):
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in values.items():
        if value is not None and value != "":
            query[key] = str(value)
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def _social_pkce_verifier():
    return secrets.token_urlsafe(64)


def _social_pkce_challenge(verifier):
    digest = hashlib.sha256(str(verifier).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _social_basic_authorization(client_id, client_secret):
    credential = f"{client_id}:{client_secret}".encode("utf-8")
    return f"Basic {base64.b64encode(credential).decode('ascii')}"


def _social_callback_url(request):
    return request.build_absolute_uri("/api/social/callback.php")


def _social_ticket_config_name(ticket):
    return f"{SOCIAL_TICKET_PREFIX}{str(ticket or '')}"[:50]


def _social_identity_config_name(provider, provider_user_id):
    digest = hashlib.sha256(f"{provider}:{provider_user_id}".encode("utf-8")).hexdigest()[:40]
    return f"{SOCIAL_IDENTITY_PREFIX}{digest}"


def _load_json_config(name):
    raw = Config.objects.filter(name=name).values_list("value", flat=True).first()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _store_json_config(name, payload):
    Config.objects.update_or_create(
        name=name,
        defaults={"value": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    )


def _social_session_binding(session, *, create=False):
    """The session's social-login binding value, made (and stored in the session) when create is set."""
    if session is None:
        return ""
    value = session.get(SOCIAL_BINDING_SESSION_KEY)
    if isinstance(value, str) and value:
        return value
    if not create:
        return ""
    value = secrets.token_urlsafe(32)
    session[SOCIAL_BINDING_SESSION_KEY] = value
    session.modified = True
    return value


def _social_binding_digest(value):
    return hashlib.sha256(f"g5-social-ticket-binding:{value}".encode("utf-8")).hexdigest()


def _social_s256(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _social_client_challenge(request):
    """The start request's client_challenge when it is a well-formed S256 challenge, else ""."""
    challenge = request.GET.get("client_challenge") or ""
    method = request.GET.get("client_challenge_method") or "S256"
    if method != "S256" or not SOCIAL_CLIENT_CHALLENGE_RE.fullmatch(challenge):
        return ""
    return challenge


def _setting_list(name):
    value = getattr(settings, name, None) or []
    if isinstance(value, str):
        value = value.replace("|", ",").split(",")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _social_app_redirect_url(value, client_challenge):
    """A native app's deep link (a custom scheme listed in SOCIAL_ALLOWED_REDIRECT_SCHEMES), accepted
    only for a flow that carries a client_challenge, so a ticket sent to the app is useless without
    the app's verifier. Returns "" for anything else."""
    raw = value.strip() if isinstance(value, str) else ""
    if not raw or not client_challenge or len(raw) > 1024 or _has_control_character(raw):
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return ""
    scheme = (parsed.scheme or "").lower()
    allowed = {item.lower() for item in _setting_list("SOCIAL_ALLOWED_REDIRECT_SCHEMES")}
    if not scheme or scheme in {"http", "https", "javascript", "data", "file", "vbscript"} or scheme not in allowed:
        return ""
    return raw


class _SocialRedirect(HttpResponseRedirect):
    """A redirect that may also go to a configured app scheme (Django allows only http/https/ftp);
    _social_flow_redirect has already vetted the address."""

    def __init__(self, redirect_to, *args, **kwargs):
        self.allowed_schemes = ["http", "https", *(item.lower() for item in _setting_list("SOCIAL_ALLOWED_REDIRECT_SCHEMES"))]
        super().__init__(redirect_to, *args, **kwargs)


def _social_redirect(url):
    return _SocialRedirect(url)


def _social_flow_redirect(request, state_payload, fallback_path):
    """Where a started flow goes back to: the app deep link it was started with, or a checked web URL."""
    app_redirect = _social_app_redirect_url(state_payload.get("redirect"), state_payload.get("client_challenge"))
    return app_redirect or _safe_social_redirect_url(request, state_payload.get("redirect"), fallback_path)


def _social_client_verifier(request):
    source = request.query_params if request.method == "GET" else _request_data(request)
    value = source.get("client_verifier")
    return value if isinstance(value, str) else ""


def _social_ticket_is_bound_to(payload, request):
    """True when the request comes from the client that started the flow: the browser whose session
    holds the binding value, or the app that knows the verifier of the flow's client_challenge."""
    session_digest = payload.get("session_binding")
    if isinstance(session_digest, str) and session_digest:
        nonce = _social_session_binding(getattr(request, "session", None))
        if nonce and hmac.compare_digest(_social_binding_digest(nonce), session_digest):
            return True
    challenge = payload.get("client_challenge")
    verifier = _social_client_verifier(request)
    if isinstance(challenge, str) and challenge and SOCIAL_CLIENT_VERIFIER_RE.fullmatch(verifier):
        return hmac.compare_digest(_social_s256(verifier), challenge)
    return False


def _create_social_ticket(profile, *, kind, user=None, session=None, client_challenge=""):
    """A one-time ticket for the profile. It is bound to the starting browser's session and/or to the
    app's client_challenge; a ticket with neither binding can never be redeemed."""
    ticket = secrets.token_urlsafe(24)
    now = int(timezone.now().timestamp())
    payload = {
        "kind": kind,
        "provider": profile["provider"],
        "provider_label": profile["provider_label"],
        "provider_user_id": profile["provider_user_id"],
        "email": profile.get("email", ""),
        "name": profile.get("name", ""),
        "nickname": profile.get("nickname", ""),
        "phone": profile.get("phone", ""),
        "photo_url": profile.get("photo_url", ""),
        "suggested_mb_id": _suggest_social_member_id(profile),
        "suggested_nick": _suggest_social_nickname(profile),
        "created_at": now,
        "expires_at": now + SOCIAL_TICKET_TTL_SECONDS,
    }
    if user:
        payload["user_id"] = user.pk
    binding = _social_session_binding(session, create=True)
    if binding:
        payload["session_binding"] = _social_binding_digest(binding)
    if client_challenge:
        payload["client_challenge"] = client_challenge
    _store_json_config(_social_ticket_config_name(ticket), payload)
    return ticket, payload


def _read_social_ticket(ticket, *, request, expected_kind=None, consume=False):
    """The ticket's payload when it exists, is fresh, of the expected kind and is redeemed by the
    client that started the flow. A redemption from another client does not use the ticket up."""
    payload = _load_social_ticket(ticket, expected_kind=expected_kind)
    if not payload or not _social_ticket_is_bound_to(payload, request):
        return None
    if consume:
        # Whoever deletes the row redeems the ticket; a concurrent second redemption finds nothing.
        deleted, _ = Config.objects.filter(name=_social_ticket_config_name(str(ticket).strip())).delete()
        if not deleted:
            return None
    return payload


def _load_social_ticket(ticket, *, expected_kind=None):
    raw_ticket = str(ticket or "").strip()
    if not raw_ticket or len(raw_ticket) > 80 or not re.match(r"^[A-Za-z0-9_\-]+$", raw_ticket):
        return None

    name = _social_ticket_config_name(raw_ticket)
    payload = _load_json_config(name)
    if not payload:
        return None

    now = int(timezone.now().timestamp())
    if int(payload.get("expires_at") or 0) < now:
        Config.objects.filter(name=name).delete()
        return None

    if expected_kind and payload.get("kind") != expected_kind:
        return None
    return payload


def _social_identity_owner(provider, provider_user_id):
    """The member a provider identity is linked to, blocked or not (None when unlinked or the member row
    is gone). A member who leaves has their links removed (member_lifecycle), so an inactive owner here
    is a member the site blocked."""
    payload = _load_json_config(_social_identity_config_name(provider, provider_user_id))
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def _social_identity_user(provider, provider_user_id):
    """The active member who may log in with the identity."""
    owner = _social_identity_owner(provider, provider_user_id)
    return owner if owner and owner.is_active else None


def _link_social_identity(user, ticket_payload):
    provider = ticket_payload.get("provider")
    provider_user_id = ticket_payload.get("provider_user_id")
    if not provider or not provider_user_id:
        return

    _store_json_config(
        _social_identity_config_name(provider, provider_user_id),
        {
            "provider": provider,
            "provider_label": ticket_payload.get("provider_label", provider.title()),
            "provider_user_id": provider_user_id,
            "user_id": user.pk,
            "username": user.get_username(),
            "email": user.email,
            "linked_at": timezone.now().isoformat(),
        },
    )


def _clean_social_value(value, max_length=255):
    return str(value or "").strip()[:max_length]


def _unique_member_id(base):
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(base or "").lower()).strip("_")
    if not cleaned:
        cleaned = "social_user"
    if cleaned and cleaned[0].isdigit():
        cleaned = f"u_{cleaned}"
    cleaned = cleaned[:20]
    if len(cleaned) < 3:
        cleaned = f"{cleaned}_user"[:20]

    if not User.objects.filter(username__iexact=cleaned).exists() and MEMBER_ID_RE.match(cleaned):
        return cleaned

    stem = cleaned[:14].rstrip("_") or "social_user"
    for index in range(1, 1000):
        candidate = f"{stem}_{index}"[:20]
        if MEMBER_ID_RE.match(candidate) and not User.objects.filter(username__iexact=candidate).exists():
            return candidate
    return f"social_{secrets.token_hex(4)}"[:20]


def _unique_nickname(base):
    # The suggestion has to pass the nickname rules at signup, so tags and markup characters are dropped.
    cleaned = "".join(
        char
        for char in _strip_markup(str(base or ""))
        if char not in NICKNAME_MARKUP_CHARACTERS and not _has_control_character(char)
    )
    cleaned = _clean_social_value(cleaned or "social_user", 80)
    if not cleaned:
        cleaned = "social_user"
    if not Profile.objects.filter(nickname__iexact=cleaned).exists():
        return cleaned

    stem = cleaned[:70].rstrip()
    for index in range(1, 1000):
        candidate = f"{stem}{index}"[:100]
        if not Profile.objects.filter(nickname__iexact=candidate).exists():
            return candidate
    return f"{stem}{secrets.token_hex(3)}"[:100]


def _suggest_social_member_id(profile):
    email = str(profile.get("email") or "").strip()
    if "@" in email:
        return _unique_member_id(email.split("@", 1)[0])
    return _unique_member_id(f"{profile.get('provider')}_{profile.get('provider_user_id')}")


def _suggest_social_nickname(profile):
    return _unique_nickname(
        profile.get("nickname")
        or profile.get("name")
        or profile.get("email", "").split("@", 1)[0]
        or profile.get("provider_user_id")
    )


def _http_json_request(url, *, method="GET", data=None, headers=None):
    body = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")

    req = urllib_request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib_request.urlopen(req, timeout=SOCIAL_TOKEN_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SocialOAuthError(f"Social provider rejected the request. {detail}", status_code=exc.code)
    except (urllib_error.URLError, socket.timeout) as exc:
        raise SocialOAuthError(f"Social provider request failed. {exc}", status_code=502)

    try:
        return json.loads(raw)
    except ValueError:
        raise SocialOAuthError("Social provider returned an invalid response.", status_code=502)


def _social_token(provider_config, code, state, redirect_uri, code_verifier=None):
    provider = provider_config["name"]
    data = {
        "client_id": provider_config["client_id"],
        "code": code,
    }
    headers = {}

    if provider == "naver":
        data.update(
            {
                "grant_type": "authorization_code",
                "client_secret": provider_config["client_secret"],
                "state": state,
            }
        )
    elif provider == "kakao":
        data.update({"grant_type": "authorization_code", "redirect_uri": redirect_uri})
        if provider_config["client_secret"]:
            data["client_secret"] = provider_config["client_secret"]
    elif provider == "google":
        data.update(
            {
                "grant_type": "authorization_code",
                "client_secret": provider_config["client_secret"],
                "redirect_uri": redirect_uri,
            }
        )
    elif provider == "facebook":
        data.update(
            {
                "client_secret": provider_config["client_secret"],
                "redirect_uri": redirect_uri,
            }
        )
    elif provider == "payco":
        data.update(
            {
                "grant_type": "authorization_code",
                "client_secret": provider_config["client_secret"],
                "state": state,
            }
        )
    elif provider == "twitter":
        if not code_verifier:
            raise SocialOAuthError("Social provider PKCE verifier is missing.", code="invalid_state")
        data.update(
            {
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        if provider_config["client_secret"]:
            headers["Authorization"] = _social_basic_authorization(
                provider_config["client_id"], provider_config["client_secret"]
            )
            data.pop("client_id", None)
    else:
        raise SocialOAuthError("Unsupported social login provider.", code="unsupported_provider")

    token = _http_json_request(provider_config["token_url"], method="POST", data=data, headers=headers)
    access_token = token.get("access_token")
    if not access_token:
        raise SocialOAuthError("Social provider did not return an access token.", status_code=502)
    return str(access_token)


def _social_userinfo(provider_config, access_token):
    provider = provider_config["name"]
    if provider == "payco":
        data = _http_json_request(
            provider_config["userinfo_url"],
            method="POST",
            data={},
            headers={"client_id": provider_config["client_id"], "access_token": access_token},
        )
    else:
        url = provider_config["userinfo_url"]
        if provider_config.get("userinfo_params"):
            url = _append_query(url, provider_config["userinfo_params"])
        data = _http_json_request(url, headers={"Authorization": f"Bearer {access_token}"})

    if provider == "naver":
        response = data.get("response") or {}
        provider_user_id = response.get("id")
        profile = {
            "email": response.get("email", ""),
            "name": response.get("name", ""),
            "nickname": response.get("nickname", ""),
            "phone": response.get("mobile", ""),
            "photo_url": response.get("profile_image", ""),
        }
    elif provider == "kakao":
        account = data.get("kakao_account") or {}
        kakao_profile = account.get("profile") or {}
        provider_user_id = data.get("id")
        profile = {
            "email": account.get("email", ""),
            "name": account.get("name", ""),
            "nickname": kakao_profile.get("nickname") or (data.get("properties") or {}).get("nickname", ""),
            "phone": account.get("phone_number", ""),
            "photo_url": kakao_profile.get("profile_image_url") or kakao_profile.get("thumbnail_image_url", ""),
        }
    elif provider == "google":
        provider_user_id = data.get("sub")
        profile = {
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "nickname": data.get("name", ""),
            "phone": "",
            "photo_url": data.get("picture", ""),
        }
    elif provider == "twitter":
        account = data.get("data") if isinstance(data.get("data"), dict) else {}
        provider_user_id = account.get("id")
        profile = {
            "email": account.get("confirmed_email") or account.get("email", ""),
            "name": account.get("name", ""),
            "nickname": account.get("username") or account.get("name", ""),
            "phone": "",
            "photo_url": account.get("profile_image_url", ""),
        }
    elif provider == "facebook":
        picture = ((data.get("picture") or {}).get("data") or {}) if isinstance(data.get("picture"), dict) else {}
        provider_user_id = data.get("id")
        profile = {
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "nickname": data.get("name", ""),
            "phone": "",
            "photo_url": picture.get("url", ""),
        }
    elif provider == "payco":
        payco_data = data.get("data") if isinstance(data.get("data"), dict) else {}
        member = payco_data.get("member") if isinstance(payco_data.get("member"), dict) else {}
        provider_user_id = member.get("idNo")
        profile = {
            "email": member.get("email") or member.get("maskedEmail", ""),
            "name": member.get("name", ""),
            "nickname": member.get("name", ""),
            "phone": member.get("mobile") or member.get("maskedMobile", ""),
            "photo_url": "",
        }
    else:
        raise SocialOAuthError("Unsupported social login provider.", code="unsupported_provider")

    provider_user_id = _clean_social_value(provider_user_id, 255)
    if not provider_user_id:
        raise SocialOAuthError("Social provider did not return a user id.", status_code=502)

    return {
        "provider": provider,
        "provider_label": provider_config["label"],
        "provider_user_id": provider_user_id,
        "email": _clean_social_value(profile.get("email"), 255),
        "name": _clean_social_value(profile.get("name"), 100),
        "nickname": _clean_social_value(profile.get("nickname"), 100),
        "phone": _clean_social_value(profile.get("phone"), 100),
        "photo_url": _clean_social_value(profile.get("photo_url"), 500),
    }


def _social_start_redirect(request, *, mode):
    provider_name = (request.GET.get("provider") or "").strip().lower()
    provider_config = _provider_config(provider_name)
    if not provider_config or not provider_config["enabled"]:
        redirect = _safe_social_redirect_url(request, request.GET.get("redirect"), "/login/social-callback")
        return HttpResponseRedirect(_append_query(redirect, {"error": "social_disabled"}))

    fallback_path = "/register" if mode == "signup" else "/login/social-callback"
    client_challenge = _social_client_challenge(request)
    redirect = _social_app_redirect_url(request.GET.get("redirect"), client_challenge) or _safe_social_redirect_url(
        request, request.GET.get("redirect"), fallback_path
    )
    state = secrets.token_urlsafe(24)
    redirect_uri = _social_callback_url(request)
    code_verifier = _social_pkce_verifier() if provider_config.get("name") == "twitter" else ""
    state_payload = {
        "provider": provider_config["name"],
        "mode": mode,
        "redirect": redirect,
        "redirect_uri": redirect_uri,
        "created_at": int(timezone.now().timestamp()),
    }
    if code_verifier:
        state_payload["code_verifier"] = code_verifier
    if client_challenge:
        state_payload["client_challenge"] = client_challenge
    _social_session_binding(request.session, create=True)
    request.session[f"{SOCIAL_STATE_SESSION_PREFIX}{state}"] = state_payload
    request.session.modified = True

    params = {
        "response_type": "code",
        "client_id": provider_config["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if provider_config.get("scope"):
        params["scope"] = provider_config["scope"]
    if provider_config["name"] == "google":
        params["prompt"] = "select_account"
    if provider_config["name"] == "twitter":
        params["code_challenge"] = _social_pkce_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    if provider_config["name"] == "payco":
        params["serviceProviderCode"] = provider_config["service_provider_code"]
        params["userLocale"] = "ko_KR"

    return HttpResponseRedirect(f"{provider_config['authorize_url']}?{urllib.parse.urlencode(params)}")


def _social_bridge_html(provider, signup_url):
    safe_provider = json.dumps(provider)
    safe_signup_url = json.dumps(signup_url)
    return HttpResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Social signup</title></head>
<body>
<script>
(function () {{
  var provider = {safe_provider};
  var signupUrl = {safe_signup_url};
  try {{
    if (window.opener && !window.opener.closed && window.opener.social_link_fn) {{
      window.opener.social_link_fn(provider);
      window.close();
      return;
    }}
  }} catch (e) {{}}
  window.location.replace(signupUrl);
}}());
</script>
</body></html>""",
        content_type="text/html; charset=utf-8",
    )


def _field_errors(**errors):
    return {key: str(value) for key, value in errors.items() if value}


def _cookie_secure(request):
    return request.is_secure()


def _set_auth_cookies(response, request, token, refresh_token=None, auto_login=False):
    cookie_kwargs = {
        "path": "/",
        "secure": _cookie_secure(request),
        "samesite": "Lax",
    }
    refresh_max_age = 30 * 24 * 60 * 60 if auto_login else None

    response.set_cookie("g5_token", token, httponly=True, **cookie_kwargs)
    if refresh_token:
        response.set_cookie(
            "g5_refresh",
            refresh_token,
            max_age=refresh_max_age,
            httponly=True,
            **cookie_kwargs,
        )
    response.set_cookie(
        "g5_auth_hint",
        "1",
        max_age=refresh_max_age,
        httponly=False,
        **cookie_kwargs,
    )
    if auto_login:
        response.set_cookie(
            "g5_auto_login",
            "1",
            max_age=refresh_max_age,
            httponly=False,
            **cookie_kwargs,
        )
    else:
        response.delete_cookie("g5_auto_login", path="/", samesite="Lax")


def _clear_auth_cookies(response):
    for name in ("g5_token", "g5_refresh", "g5_auth_hint", "g5_auto_login"):
        response.delete_cookie(name, path="/", samesite="Lax")


def _profile_for_user(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _absolute_media_url(request, field_file):
    if not field_file:
        return ""
    try:
        url = field_file.url
    except ValueError:
        return ""
    return request.build_absolute_uri(url)


def member_payload(user, request=None):
    profile = _profile_for_user(user)
    full_name = profile.realname or user.get_full_name() or user.first_name or user.username
    icon_path = _absolute_media_url(request, profile.icon) if request else ""
    avatar_path = _absolute_media_url(request, profile.avatar) if request else ""

    return {
        "mb_no": user.pk,
        "mb_id": user.username,
        "mb_name": full_name,
        "mb_nick": profile.nickname or user.username,
        "mb_email": user.email,
        "mb_level": profile.user_level,
        "mb_point": profile.user_point,
        "mb_icon_path": icon_path or avatar_path or "",
        "mb_datetime": user.date_joined.isoformat() if user.date_joined else "",
        "mb_today_login": timezone.now().isoformat(),
        "mb_open": 1 if profile.open_profile else 0,
        "mb_open_date": profile.open_profile_date.isoformat() if profile.open_profile_date else "",
        "mb_mailling": 1 if profile.mailing else 0,
        "mb_mailling_date": profile.mailing_date.isoformat() if profile.mailing_date else "",
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def merge_guest_cart(request, user):
    """YoungCart keeps what a visitor put in the cart when they sign in: move the session cart into
    the member cart (the member cart is a JSON list in Config, the guest cart lives in the session)."""
    from .shop_cart_keep import cart_keep_options, prune_cart_rows, reset_guest_cart_session
    from .shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
    from gnu_jango.shop.shipping import with_server_send_cost_flags

    session = getattr(request, "session", None)
    # a member session keeps the default lifetime, not the long guest cart one (de_guest_cart_use)
    reset_guest_cart_session(request)
    guest_rows = list(session.get(SHOP_CART_SESSION_KEY, [])) if session is not None else []
    if not guest_rows:
        return
    name = auth_cart_config_name(user)
    stored = Config.objects.filter(name=name).values_list("value", flat=True).first()
    try:
        member_rows = json.loads(stored) if stored else []
    except (TypeError, ValueError):
        member_rows = []
    if not isinstance(member_rows, list):
        member_rows = []
    # lines older than the cart keep term (de_cart_keep_term) are not carried over
    _, keep_term = cart_keep_options(request)
    member_rows, _ = prune_cart_rows(member_rows, keep_term)
    guest_rows, _ = prune_cart_rows(guest_rows, keep_term)
    known = {str(row.get("ct_id")) for row in member_rows}
    member_rows.extend(row for row in guest_rows if str(row.get("ct_id")) not in known)
    # the guest rows came from the session: their ct_send_cost is recomputed, not carried over
    member_rows = with_server_send_cost_flags(member_rows)
    Config.objects.update_or_create(
        name=name, defaults={"value": json.dumps(member_rows, ensure_ascii=False, separators=(",", ":"))}
    )
    session.pop(SHOP_CART_SESSION_KEY, None)


def award_login_points(user):
    """Gnuboard5 grants cf_login_point on a member's first login of the day."""
    today = timezone.localdate().isoformat()
    point_ledger.insert_point(
        user, point_ledger.config_points("cf_login_point"), f"{today} 첫로그인", "@login", user.pk, today
    )


def reissue_auth(response, user, request):
    """Give the current client a fresh token pair (and cookies) after the old ones were revoked."""
    payload = _auth_payload(user, request)
    _set_auth_cookies(response, request, payload["token"], payload["refresh_token"], False)
    return payload


def _auth_user_from_request(request):
    """The signed-in member, or None. A member whose new e-mail address still awaits its certify link
    (cf_use_email_certify on) counts as signed out, so access tokens issued before the change stop
    working at once instead of at their expiry."""
    user = _token_user_from_request(request)
    if user is None or not user.is_active or certification_pending(user):
        return None
    return user


def _token_user_from_request(request):
    if request.user and request.user.is_authenticated:
        return request.user

    auth_header = request.headers.get("Authorization") or ""
    raw_token = ""
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
    raw_token = raw_token or request.COOKIES.get("g5_token")
    if not raw_token:
        return None

    authenticator = JWTAuthentication()
    try:
        validated = authenticator.get_validated_token(raw_token)
        return authenticator.get_user(validated)
    except (InvalidToken, TokenError, AuthenticationFailed):
        return None


def _auth_payload(user, request, *, refresh_token=None, auto_login=False):
    token, issued_refresh, expires_in = _tokens_for_user(user, request)
    return {
        "token": token,
        "refresh_token": refresh_token or issued_refresh,
        "expires_in": expires_in,
        "auto_login": 1 if auto_login else 0,
        "member": member_payload(user, request),
        "is_super_admin": bool(user.is_superuser),
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token_view(request):
    """Issue a CSRF cookie and a masked token for browser API mutations."""
    response = api_response(data={"csrf_token": get_token(request)})
    response["Cache-Control"] = "no-store, private"
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def check_id_view(request):
    mb_id = (request.query_params.get("mb_id") or "").strip()
    if not mb_id:
        return api_response(data={"available": False, "message": "아이디를 입력해주세요."})
    if not MEMBER_ID_RE.match(mb_id):
        return api_response(
            data={
                "available": False,
                "message": "아이디는 3~20자의 영문, 숫자, _만 사용할 수 있습니다.",
            }
        )

    reserved = reserved_member_id_error(mb_id)  # ajax.mb_id.php: reserve_mb_id
    if reserved:
        return api_response(data={"available": False, "message": reserved})

    exists = User.objects.filter(username__iexact=mb_id).exists()
    return api_response(
        data={
            "available": not exists,
            "message": "사용 가능한 아이디입니다." if not exists else "이미 사용 중인 아이디입니다.",
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def check_email_view(request):
    mb_email = (request.query_params.get("mb_email") or "").strip()
    # ajax.mb_email.php: valid_mb_email, then prohibit_mb_email.
    email_error = email_rule_error(mb_email) if mb_email else "올바른 이메일 주소를 입력해주세요."
    if email_error:
        return api_response(data={"available": False, "message": email_error})

    exists = User.objects.filter(email__iexact=mb_email).exists()
    return api_response(
        data={
            "available": not exists,
            "message": "사용 가능한 이메일입니다." if not exists else "이미 사용 중인 이메일입니다.",
        }
    )


def _left_member_error(mb_id, password):
    """login_check.php: a member who left is told so, with the leave date, once the password matched
    (the auth backend refuses inactive members, so the password is checked here again)."""
    candidate = (
        User.objects.filter(Q(username__iexact=mb_id) | Q(email__iexact=mb_id), is_active=False)
        .filter(profile__leave_date__isnull=False)
        .select_related("profile")
        .order_by("id")
        .first()
    )
    if not candidate or not candidate.check_password(password):
        return None
    left = candidate.profile.leave_date
    return api_error(
        f"탈퇴한 아이디이므로 접근하실 수 없습니다.\n탈퇴일 : {left:%Y}년 {left:%m}월 {left:%d}일",
        status=status.HTTP_403_FORBIDDEN,
        code="member_left",
    )


def _email_not_certified_error(user, *, social=False):
    """login_check.php: with cf_use_email_certify on, a member whose address is not certified cannot
    log in. The password matched, so the answer names the address and lets the screen offer a resend."""
    profile = _profile_for_user(user)
    if is_email_certified(profile) or not email_certify_required(social=social):
        return None
    message = f"{user.email} 메일로 메일인증을 받으셔야 로그인 가능합니다."
    return api_error(
        message,
        status=status.HTTP_403_FORBIDDEN,
        code="email_not_certified",
        details={"mb_id": user.get_username(), "mb_email": user.email},
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def login_view(request):
    data = _request_data(request)
    mb_id, bad_id = _form_text(data, "mb_id", "username", "email")
    mb_id = mb_id.strip()
    password, bad_password = _form_text(data, "mb_password", "password")
    # login_check.php keeps the login only when the auto_login checkbox is on: "0", "false" and "" are off.
    auto_login = any(truthy_flag(data.get(key)) for key in ("auto_login", "remember", "remember_me"))

    if bad_id or bad_password or not mb_id or not password:
        return api_error(
            "Validation failed.",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details=_field_errors(mb_id="아이디를 입력해주세요.", mb_password="비밀번호를 입력해주세요."),
        )

    if "\x00" in mb_id:
        return api_error("Invalid member ID or password.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_login")

    user = authenticate(request, username=mb_id, password=password)
    if not user:
        return _left_member_error(mb_id, password) or api_error(
            "Invalid member ID or password.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_login"
        )
    if not user.is_active:
        return api_error("This account is inactive.", status=status.HTTP_403_FORBIDDEN, code="inactive_member")
    certify_error = _email_not_certified_error(user)
    if certify_error:
        return certify_error

    award_login_points(user)
    merge_guest_cart(request, user)
    payload = _auth_payload(user, request, auto_login=auto_login)
    response = api_response(data=payload, status=status.HTTP_200_OK)
    _set_auth_cookies(response, request, payload["token"], payload["refresh_token"], auto_login)
    return response


REGISTER_CERTIFY_MESSAGE = (
    "회원 가입 시 입력하신 이메일 주소로 인증메일이 발송되었습니다. "
    "발송된 인증메일을 확인하신 후 인증처리를 하시면 사이트를 원활하게 이용하실 수 있습니다."
)


def _signup_needs_email_certify(social_signup, mb_email):
    """A social signup is certified at once (plugin/social/register_member_update.php) unless
    SOCIAL_CERTIFY_MAIL is on, or the member typed an address the provider did not vouch for."""
    if not social_signup:
        return email_certify_required()
    provider_email = str(social_signup.get("email") or "").strip().lower()
    if provider_email and provider_email == mb_email.strip().lower():
        return email_certify_required(social=True)
    return email_certify_required()


def _register_field_errors(mb_id, password, password_re, mb_email, mb_name, mb_nick):
    """register_form_update.php and plugin/social/register_member_update.php field checks: the id
    alphabet and reserve_mb_id, the nickname rules with reserve_mb_nick, valid_mb_email with
    prohibit_mb_email, then the ids, addresses and nicknames already taken."""
    errors = {"mb_id": "", "mb_email": "", "mb_nick": ""}
    if not MEMBER_ID_RE.match(mb_id):
        errors["mb_id"] = "아이디는 3~20자의 영문, 숫자, _만 사용할 수 있습니다."
    else:
        errors["mb_id"] = reserved_member_id_error(mb_id)
    if not password:
        errors["mb_password"] = "비밀번호를 입력해주세요."
    if password != password_re:
        errors["mb_password_re"] = "비밀번호가 일치하지 않습니다."
    errors["mb_email"] = email_rule_error(mb_email) if mb_email else "올바른 이메일 주소를 입력해주세요."
    if not mb_name:
        errors["mb_name"] = "이름을 입력해주세요."
    errors["mb_nick"] = nickname_rule_error(mb_nick) if mb_nick else "닉네임을 입력해주세요."
    if not errors["mb_id"] and User.objects.filter(username__iexact=mb_id).exists():
        errors["mb_id"] = "이미 사용 중인 아이디입니다."
    if not errors["mb_email"] and User.objects.filter(email__iexact=mb_email).exists():
        errors["mb_email"] = "이미 사용 중인 이메일입니다."
    if not errors["mb_nick"] and Profile.objects.filter(nickname__iexact=mb_nick).exists():
        errors["mb_nick"] = "이미 사용 중인 닉네임입니다."
    return {key: value for key, value in errors.items() if value}


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def register_view(request):
    data = _request_data(request)
    fields = {
        "mb_id": _form_text(data, "mb_id", "username"),
        "mb_password": _form_text(data, "mb_password", "password"),
        "mb_password_re": _form_text(data, "mb_password_re", "mb_password_confirm", "password_confirm"),
        "mb_email": _form_text(data, "mb_email", "email"),
        "mb_name": _form_text(data, "mb_name", "name"),
        "mb_nick": _form_text(data, "mb_nick", "nickname"),
        "social_signup_ticket": _form_text(data, "social_signup_ticket"),
    }
    # A number, list or object where text belongs is refused up front (it used to raise a 500).
    type_errors = {key: "올바른 값을 입력해주세요." for key, (_value, bad) in fields.items() if bad}
    if type_errors:
        return api_error(
            "Validation failed.", status=status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error", details=type_errors
        )
    mb_id = fields["mb_id"][0].strip()
    password = fields["mb_password"][0]
    password_re = fields["mb_password_re"][0]
    mb_email = fields["mb_email"][0].strip()
    # register_form_update.php: clean_xss_tags() on the name; markup is dropped, not stored.
    mb_name = _strip_markup(fields["mb_name"][0] or mb_id)
    mb_nick = (fields["mb_nick"][0] or mb_id).strip()
    social_signup_ticket = fields["social_signup_ticket"][0].strip()
    social_signup = (
        _read_social_ticket(social_signup_ticket, request=request, expected_kind="signup") if social_signup_ticket else None
    )
    # register_form.skin.php checks mb_open for a new member.
    open_profile = truthy_flag(data.get("mb_open")) if "mb_open" in data else True
    # register_form.skin.php mb_mailling: information mail only when the member ticks it.
    mailing = truthy_flag(data.get("mb_mailling"))

    if social_signup_ticket and not social_signup:
        return api_error(
            "Social signup profile was not found.",
            status=status.HTTP_404_NOT_FOUND,
            code="social_signup_not_found",
        )

    if social_signup:
        mb_id = mb_id or social_signup.get("suggested_mb_id") or _suggest_social_member_id(social_signup)
        mb_email = mb_email or social_signup.get("email", "")
        mb_name = mb_name or _strip_markup(social_signup.get("name") or social_signup.get("nickname") or "") or mb_id
        mb_nick = mb_nick or social_signup.get("suggested_nick") or _suggest_social_nickname(social_signup)
        if not password:
            password = secrets.token_urlsafe(24)
            password_re = password

    if social_signup and _social_identity_owner(social_signup.get("provider"), social_signup.get("provider_user_id")):
        # The identity was linked (perhaps to a member the site blocked) after the ticket was issued:
        # a second account must not take the link over.
        return api_error("This social account is already linked.", status=status.HTTP_409_CONFLICT, code="already_linked")

    errors = _register_field_errors(mb_id, password, password_re, mb_email, mb_name, mb_nick)

    if not social_signup and not _captcha_matches(request, data.get("captcha_key")):
        errors["captcha_key"] = "Invalid captcha."

    if not errors:
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            errors["mb_password"] = " ".join(exc.messages)

    needs_certify = not errors and _signup_needs_email_certify(social_signup, mb_email)
    if errors:
        message = "Invalid captcha." if set(errors) == {"captcha_key"} else "Validation failed."
        return api_error(
            message,
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details=errors,
        )

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=mb_id,
                email=mb_email,
                password=password,
                first_name=mb_name,
            )
            profile = _profile_for_user(user)
            profile.nickname = mb_nick
            profile.realname = mb_name
            if not profile.user_level:
                profile.user_level = 2
            profile.open_profile = open_profile
            profile.open_profile_date = timezone.now()  # register_form_update.php: mb_open_date = today
            profile.mailing = mailing
            profile.mailing_date = timezone.now()
            # register_form_update.php: without e-mail certification the address counts as certified now;
            # with it, the member is stored uncertified with the link's token in the same transaction.
            profile.email_certify = None if needs_certify else timezone.now()
            profile.email_certify_token = new_email_certify_token() if needs_certify else ""
            profile.save(
                update_fields=[
                    "nickname", "realname", "user_level", "open_profile", "open_profile_date",
                    "mailing", "mailing_date", "email_certify", "email_certify_token",
                ]
            )
            if social_signup:
                _link_social_identity(user, social_signup)
                Config.objects.filter(name=_social_ticket_config_name(social_signup_ticket)).delete()
            point_ledger.insert_point(
                user, point_ledger.config_points("cf_register_point"), "회원가입 축하", "@member", user.pk, "회원가입"
            )
            issue_signup_coupon(user)
            queue_member_join_sms(user)
        _consume_captcha(request)
    except IntegrityError:
        return api_error(
            "Failed to create member account.",
            status=status.HTTP_409_CONFLICT,
            code="member_conflict",
        )

    request.session["g5_last_register_id"] = user.pk
    if needs_certify:
        # register_form_update.php: the member is not signed in until the mailed link is clicked.
        send_email_certify_mail(request, user, profile.email_certify_token)
        return api_response(
            data={
                "requires_email_verification": True,
                "mb_id": user.get_username(),
                "mb_email": user.email,
                "message": REGISTER_CERTIFY_MESSAGE,
                "registration_result_url": "/register/result",
            },
            status=status.HTTP_201_CREATED,
        )
    payload = _auth_payload(user, request, auto_login=False)
    response = api_response(data=payload, status=status.HTTP_201_CREATED)
    _set_auth_cookies(response, request, payload["token"], payload["refresh_token"], False)
    return response


@extend_schema(responses=envelope("AuthMe", AuthMeSerializer()))
@api_view(["GET"])
@permission_classes([AllowAny])
def me_view(request):
    user = _auth_user_from_request(request)
    if not user:
        return api_error("Authentication credentials were not provided.", status=status.HTTP_401_UNAUTHORIZED, code="not_authenticated")
    if user.is_active:
        # Gnuboard5 grants the daily login points on the first visit of the day, also for members
        # who stay signed in; the site calls this on every page load and the ledger keeps it to once.
        award_login_points(user)
    member = {**member_payload(user, request), **_own_contact_payload(user)}
    return api_response(data={"member": member, "is_super_admin": bool(user.is_superuser)})


def _own_contact_payload(user):
    """The signed-in member's own phone and address, which the order form fills in as the orderer
    (YoungCart orderform.php prefills od_name/od_tel/od_hp/od_zip/od_addr* from $member).
    Only ``me_view`` adds this; payloads describing other members never carry it."""
    profile = _profile_for_user(user)
    zip_code = str(profile.user_zip or "").strip()
    return {
        "mb_hp": profile.user_hp or "",
        "mb_tel": "",  # Profile keeps a single phone number (mb_hp)
        "mb_zip": zip_code,
        "mb_zip1": zip_code[:3],
        "mb_zip2": zip_code[3:],
        "mb_addr1": profile.user_addr1 or "",
        "mb_addr2": profile.user_addr2 or "",
        "mb_addr3": "",
        "mb_addr_jibeon": profile.user_addr_jibeon or "",
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_view(request):
    data = _request_data(request)
    if request.COOKIES.get("g5_refresh"):
        # Refresh cookies are ambient browser credentials even when the access
        # token has expired and SessionJWTAuthentication therefore cannot run.
        SessionAuthentication().enforce_csrf(request)
    refresh_token = data.get("refresh_token") or data.get("refresh") or request.COOKIES.get("g5_refresh")
    if not refresh_token:
        return api_error("Refresh token is required.", status=status.HTTP_401_UNAUTHORIZED, code="refresh_required")

    try:
        refresh = RefreshToken(str(refresh_token))
        user = User.objects.get(pk=refresh["user_id"], is_active=True)
    except (TokenError, User.DoesNotExist, KeyError):
        response = api_error("Invalid or expired refresh token.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_refresh")
        _clear_auth_cookies(response)
        return response
    try:
        refresh_version = int(refresh.payload.get("tv", 0))
    except (TypeError, ValueError):
        refresh_version = -1
    if refresh_version != token_version_for_user(user):
        response = api_error("Invalid or expired refresh token.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_refresh")
        _clear_auth_cookies(response)
        return response
    certify_error = _email_not_certified_error(user)
    if certify_error:
        _clear_auth_cookies(certify_error)
        return certify_error

    simple_jwt = getattr(settings, "SIMPLE_JWT", {})
    rotate_refresh = bool(simple_jwt.get("ROTATE_REFRESH_TOKENS", False))
    blacklist_after_rotation = bool(simple_jwt.get("BLACKLIST_AFTER_ROTATION", False))
    issued_refresh = refresh
    needs_session_claims = refresh.payload.get("sid") != refresh.payload.get("jti")
    if rotate_refresh or needs_session_claims:
        if needs_session_claims and not rotate_refresh:
            try:
                refresh.blacklist()
            except AttributeError:
                pass
        elif blacklist_after_rotation:
            try:
                refresh.blacklist()
            except AttributeError:
                pass
        issued_refresh = issue_refresh_token(user, request, login_at=refresh.payload.get("lat"))

    access = issued_refresh.access_token
    payload = {
        "token": str(access),
        "refresh_token": str(issued_refresh),
        "expires_in": int(access.lifetime.total_seconds()),
        "member": member_payload(user, request),
        "is_super_admin": bool(user.is_superuser),
    }
    response = api_response(data=payload)
    _set_auth_cookies(response, request, payload["token"], payload["refresh_token"], bool(request.COOKIES.get("g5_auto_login")))
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    data = _request_data(request)
    if request.COOKIES.get("g5_refresh"):
        SessionAuthentication().enforce_csrf(request)
    refresh_token = data.get("refresh_token") or data.get("refresh") or request.COOKIES.get("g5_refresh")
    user = _token_user_from_request(request)
    revoke_current_session(request, user, str(refresh_token or ""))

    response = api_response(data={"logged_out": True}, status=status.HTTP_200_OK)
    _clear_auth_cookies(response)
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def register_result_view(request):
    user = None
    user_id = request.session.get("g5_last_register_id")
    if user_id:
        user = User.objects.filter(pk=user_id).first()
    if not user:
        user = _auth_user_from_request(request)
    if not user:
        return api_error("Registration result was not found.", status=status.HTTP_404_NOT_FOUND, code="register_result_not_found")

    member = member_payload(user, request)
    return api_response(
        data={
            "mb_id": member["mb_id"],
            "mb_name": member["mb_name"],
            "mb_nick": member["mb_nick"],
            "mb_email": member["mb_email"],
            "mb_datetime": member["mb_datetime"],
            "requires_email_verification": email_certify_required() and not is_email_certified(_profile_for_user(user)),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def social_providers_view(request):
    providers = _configured_social_providers()
    return api_response(
        data={
            "enabled": any(provider.get("enabled") for provider in providers),
            "providers": providers,
        }
    )


@never_cache
def social_start_view(request):
    return _social_start_redirect(request, mode="login")


@never_cache
def social_signup_start_view(request):
    return _social_start_redirect(request, mode="signup")


def _social_state_is_fresh(state_payload):
    """The OAuth state lives as long as a social ticket: a state older than SOCIAL_TICKET_TTL_SECONDS, or
    without a start time, is refused, so a stale authorize link cannot be completed much later."""
    if not isinstance(state_payload, dict):
        return False
    try:
        created_at = int(state_payload.get("created_at") or 0)
    except (TypeError, ValueError):
        return False
    age = int(timezone.now().timestamp()) - created_at
    return 0 <= age <= SOCIAL_TICKET_TTL_SECONDS


@never_cache
def social_callback_view(request):
    state = str(request.GET.get("state") or "")
    session_key = f"{SOCIAL_STATE_SESSION_PREFIX}{state}"
    state_payload = request.session.pop(session_key, None)
    request.session.modified = True

    fallback = request.build_absolute_uri("/login/social-callback")
    if not _social_state_is_fresh(state_payload):
        return HttpResponseRedirect(_append_query(fallback, {"error": "invalid_state"}))

    redirect = _social_flow_redirect(
        request,
        state_payload,
        "/register" if state_payload.get("mode") == "signup" else "/login/social-callback",
    )
    ticket_binding = {"session": request.session, "client_challenge": state_payload.get("client_challenge") or ""}

    provider_name = state_payload.get("provider")
    provider_config = _provider_config(provider_name)
    if not provider_config or not provider_config["enabled"]:
        return _social_redirect(_append_query(redirect, {"error": "social_disabled"}))

    provider_error = request.GET.get("error")
    if provider_error:
        return _social_redirect(_append_query(redirect, {"error": provider_error}))

    code = str(request.GET.get("code") or "").strip()
    if not code:
        return _social_redirect(_append_query(redirect, {"error": "missing_code"}))

    try:
        access_token = _social_token(
            provider_config,
            code,
            state,
            state_payload.get("redirect_uri") or _social_callback_url(request),
            code_verifier=state_payload.get("code_verifier"),
        )
        profile = _social_userinfo(provider_config, access_token)
    except SocialOAuthError as exc:
        return _social_redirect(_append_query(redirect, {"error": exc.code}))

    linked_user = _social_identity_owner(profile["provider"], profile["provider_user_id"])
    if linked_user and not linked_user.is_active:
        # login_check.php refuses a member with mb_intercept_date. The identity stays theirs, so no signup
        # is offered either: a second account would take the link over and walk around the block.
        return _social_redirect(_append_query(redirect, {"error": "member_blocked"}))
    if linked_user:
        ticket, _ = _create_social_ticket(profile, kind="login", user=linked_user, **ticket_binding)
        return _social_redirect(_append_query(redirect, {"ticket": ticket}))

    ticket, _ = _create_social_ticket(profile, kind="signup", **ticket_binding)
    signup_url = _append_query(
        _safe_social_redirect_url(request, redirect if state_payload.get("mode") == "signup" else "", "/register"),
        {"social_signup_ticket": ticket},
    )
    if state_payload.get("mode") == "login":
        return _social_bridge_html(profile["provider"], signup_url)
    return HttpResponseRedirect(signup_url)


@api_view(["POST"])
@permission_classes([AllowAny])
def social_exchange_view(request):
    data = _request_data(request)
    ticket = data.get("ticket") or data.get("social_ticket") or ""
    payload = _read_social_ticket(ticket, request=request, expected_kind="login", consume=True)
    if not payload:
        return api_error(
            "Social login ticket was not found.",
            status=status.HTTP_404_NOT_FOUND,
            code="social_ticket_not_found",
        )

    user = User.objects.filter(pk=payload.get("user_id"), is_active=True).first()
    if not user:
        return api_error("Linked member was not found.", status=status.HTTP_404_NOT_FOUND, code="member_not_found")
    certify_error = _email_not_certified_error(user, social=True)
    if certify_error:
        return certify_error

    award_login_points(user)
    auth_payload = _auth_payload(user, request, auto_login=False)
    response = api_response(data=auth_payload, status=status.HTTP_200_OK)
    _set_auth_cookies(response, request, auth_payload["token"], auth_payload["refresh_token"], False)
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def social_signup_profile_view(request):
    payload = _read_social_ticket(request.query_params.get("ticket"), request=request, expected_kind="signup")
    if not payload:
        return api_error(
            "Social signup profile was not found.",
            status=status.HTTP_404_NOT_FOUND,
            code="social_signup_not_found",
        )

    return api_response(
        data={
            "ticket": request.query_params.get("ticket"),
            "provider": payload.get("provider", ""),
            "provider_label": payload.get("provider_label", ""),
            "suggested_mb_id": payload.get("suggested_mb_id", ""),
            "suggested_nick": payload.get("suggested_nick", ""),
            "name": payload.get("name", ""),
            "email": payload.get("email", ""),
            "phone": payload.get("phone", ""),
            "photo_url": payload.get("photo_url", ""),
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def social_link_existing_view(request):
    data = _request_data(request)
    ticket = data.get("social_signup_ticket") or data.get("ticket") or ""
    payload = _read_social_ticket(ticket, request=request, expected_kind="signup")
    if not payload:
        return api_error(
            "Social signup profile was not found.",
            status=status.HTTP_404_NOT_FOUND,
            code="social_signup_not_found",
        )

    mb_id, _bad_id = _form_text(data, "mb_id", "username")
    password, _bad_password = _form_text(data, "mb_password", "password")
    user = authenticate(request, username=mb_id.strip(), password=password) if mb_id.strip() and password else None
    if not user:
        return api_error("Invalid member ID or password.", status=status.HTTP_401_UNAUTHORIZED, code="invalid_login")
    if not user.is_active:
        return api_error("This account is inactive.", status=status.HTTP_403_FORBIDDEN, code="inactive_member")
    # The member signs in with their password here, so the same certification rule as login_view.
    certify_error = _email_not_certified_error(user)
    if certify_error:
        return certify_error

    # An identity linked to a blocked member is still theirs and cannot be moved to another account.
    linked_user = _social_identity_owner(payload.get("provider"), payload.get("provider_user_id"))
    if linked_user and linked_user.pk != user.pk:
        return api_error("This social account is already linked.", status=status.HTTP_409_CONFLICT, code="already_linked")

    _link_social_identity(user, payload)
    Config.objects.filter(name=_social_ticket_config_name(ticket)).delete()
    auth_payload = _auth_payload(user, request, auto_login=False)
    response = api_response(data=auth_payload, status=status.HTTP_200_OK)
    _set_auth_cookies(response, request, auth_payload["token"], auth_payload["refresh_token"], False)
    return response


# DRF's ScopedRateThrottle reads the scope from the view class before the view body runs, so it
# has to be set on the generated class (setting request.throttle_scope inside the view did nothing).
login_view.cls.throttle_scope = "auth-login"
social_link_existing_view.cls.throttle_scope = "auth-login"
register_view.cls.throttle_scope = "auth-register"
