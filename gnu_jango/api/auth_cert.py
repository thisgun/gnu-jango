"""Identity verification (Gnuboard5 cert) bridge of the auth API."""

import json
import urllib.parse

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny


from .response import api_response

from .auth_common import (
    _config_value,
    _current_origin,
    _is_loopback_host,
    _iter_configured_origins,
    _normalize_origin,
    _setting_value,
    _truthy,
)


CERT_RETURN_ORIGIN_SESSION_KEY = "ss_nextjs25_cert_return_origin"


def _cert_value(config_name, setting_name="", default=""):
    setting = _setting_value(setting_name) if setting_name else ""
    if setting:
        return setting
    return _config_value(config_name, default)


def _cert_int_value(config_name, setting_name="", default=0):
    try:
        return int(str(_cert_value(config_name, setting_name, default)).strip() or default)
    except (TypeError, ValueError):
        return default


def _cert_provider_value(config_name, setting_name="", allowed=()):
    provider = str(_cert_value(config_name, setting_name, "") or "").strip().lower()
    if allowed and provider not in set(allowed):
        return ""
    return provider


def _cert_config_payload():
    mode = max(0, _cert_int_value("cf_cert_use", "GNUBOARD_CERT_USE", 0))
    simple = _cert_provider_value("cf_cert_simple", "GNUBOARD_CERT_SIMPLE", {"", "inicis", "kcb"})
    hp = _cert_provider_value("cf_cert_hp", "GNUBOARD_CERT_HP", {"", "kcp", "kcp_v2", "kcb", "lg"})
    ipin = _cert_provider_value("cf_cert_ipin", "GNUBOARD_CERT_IPIN", {"", "kcp", "kcb"})
    return {
        "enabled": mode > 0,
        "mode": mode,
        "required": _truthy(_cert_value("cf_cert_req", "GNUBOARD_CERT_REQUIRED", "0")),
        "find_enabled": _truthy(_cert_value("cf_cert_find", "GNUBOARD_CERT_FIND", "0")),
        "simple": simple,
        "hp": hp,
        "ipin": ipin,
        "use_hp": _truthy(_cert_value("cf_use_hp", "GNUBOARD_CERT_USE_HP", "0")),
        "require_hp": _truthy(_cert_value("cf_req_hp", "GNUBOARD_CERT_REQUIRE_HP", "0")),
    }


def _cert_allowed_post_message_origins(request):
    origins = {_normalize_origin(_current_origin(request))}
    for setting_name in ("SOCIAL_APP_BASE_URL", "GNUBOARD_CERT_APP_BASE_URL"):
        origin = _normalize_origin(_setting_value(setting_name))
        if origin:
            origins.add(origin)

    for setting_name in ("SOCIAL_ALLOWED_REDIRECT_ORIGINS", "GNUBOARD_CERT_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS"):
        origins.update(_iter_configured_origins(getattr(settings, setting_name, [])))
    return {origin for origin in origins if origin}


def _cert_origin_allowed(request, origin):
    if origin in _cert_allowed_post_message_origins(request):
        return True
    if settings.DEBUG:
        try:
            return _is_loopback_host(urllib.parse.urlparse(origin).hostname)
        except ValueError:
            return False
    return False


def _cert_post_message_origin(request):
    requested = _normalize_origin(request.GET.get("returnOrigin"))
    if requested and _cert_origin_allowed(request, requested):
        request.session[CERT_RETURN_ORIGIN_SESSION_KEY] = requested
        request.session.modified = True
        return requested

    stored = _normalize_origin(request.session.get(CERT_RETURN_ORIGIN_SESSION_KEY))
    if stored and _cert_origin_allowed(request, stored):
        return stored

    # with no trusted origin the popup posts nothing rather than broadcasting to any opener
    return _normalize_origin(_current_origin(request)) or ""


def _cert_adapter_url(request, endpoint):
    base = _setting_value("GNUBOARD_CERT_ADAPTER_BASE_URL")
    if not base:
        return ""

    adapter_origin = _normalize_origin(base)
    current_origin = _normalize_origin(_current_origin(request))
    if adapter_origin and adapter_origin == current_origin:
        return ""

    root = base.rstrip("/")
    if not root.endswith("/api/cert"):
        root = f"{root}/api/cert"
    target = f"{root}/{endpoint.lstrip('/')}"

    query = request.GET.copy()
    return_origin = _normalize_origin(query.get("returnOrigin"))
    if return_origin and _cert_origin_allowed(request, return_origin):
        query["returnOrigin"] = return_origin
    else:
        query.pop("returnOrigin", None)

    encoded = query.urlencode()
    return f"{target}?{encoded}" if encoded else target


_SCRIPT_JSON_ESCAPES = str.maketrans({"<": "\\u003C", ">": "\\u003E", "&": "\\u0026"})


def _script_json(value):
    # JSON placed inside a <script> block: no markup character may survive ("</script", "<!--").
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).translate(_SCRIPT_JSON_ESCAPES)


def _cert_bridge_html(request, payload, *, clear_return_origin=True):
    payload = dict(payload)
    payload.setdefault("type", "identity-verification-result")
    payload.setdefault("status", "error")
    payload_json = _script_json(payload)
    target_origin_json = _script_json(_cert_post_message_origin(request))
    if clear_return_origin:
        request.session[CERT_RETURN_ORIGIN_SESSION_KEY] = ""
        request.session.modified = True
    return HttpResponse(
        f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>본인확인</title></head>
<body>
<script>
(function () {{
  var payload = {payload_json};
  var targetOrigin = {target_origin_json};
  try {{
    if (targetOrigin && window.opener && !window.opener.closed) {{
      window.opener.postMessage(payload, targetOrigin);
    }}
  }} catch (e) {{}}
  if (payload && payload.status === "error" && payload.message) {{
    try {{ alert(payload.message); }} catch (e) {{}}
  }}
  try {{ window.close(); }} catch (e) {{}}
}}());
</script>
<p style="font-family:sans-serif;color:#555;text-align:center;margin-top:2rem;">
본인확인 처리가 완료되었습니다. 이 창은 자동으로 닫힙니다.
</p>
</body>
</html>""",
        content_type="text/html; charset=utf-8",
    )


def _cert_error_and_close(request, message, *, code="cert_error"):
    return _cert_bridge_html(
        request,
        {
            "status": "error",
            "code": code,
            "message": str(message),
        },
    )


def _cert_page_type(request):
    page_type = str(request.GET.get("pageType") or request.POST.get("pageType") or "register").strip().lower()
    return page_type if page_type in {"register", "find"} else ""


def _cert_method_enabled(kind, provider):
    config = _cert_config_payload()
    if not config["enabled"]:
        return False
    if not provider:
        return False
    if kind == "simple":
        return config["simple"] == provider
    if kind == "hp":
        return config["hp"] == provider
    if kind == "ipin":
        return config["ipin"] == provider
    return False


def _cert_start_view(request, *, kind, provider, disabled_message, adapter_endpoint=""):
    page_type = _cert_page_type(request)
    if not page_type:
        return _cert_error_and_close(request, "잘못된 접근입니다.", code="invalid_cert_page_type")

    config = _cert_config_payload()
    if page_type == "find" and not config["find_enabled"]:
        return _cert_error_and_close(
            request,
            "본인확인을 이용한 아이디/비밀번호 찾기가 비활성화되어 있습니다.",
            code="cert_find_disabled",
        )

    if not _cert_method_enabled(kind, provider):
        return _cert_error_and_close(request, disabled_message, code="cert_provider_disabled")

    adapter_url = _cert_adapter_url(request, adapter_endpoint) if adapter_endpoint else ""
    if adapter_url:
        return HttpResponseRedirect(adapter_url)

    return _cert_error_and_close(
        request,
        "Django 본인확인 연동은 provider SDK와 실서비스 키 설정이 필요합니다.",
        code="cert_provider_unimplemented",
    )


def _cert_result_view(request, *, kind, provider, disabled_message):
    if not _cert_method_enabled(kind, provider):
        return _cert_error_and_close(request, disabled_message, code="cert_provider_disabled")

    return _cert_error_and_close(
        request,
        "Django 본인확인 결과 검증 SDK가 설정되지 않았습니다.",
        code="cert_result_unimplemented",
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def cert_config_view(request):
    return api_response(data=_cert_config_payload())


@never_cache
def cert_inicis_start_view(request):
    return _cert_start_view(
        request,
        kind="simple",
        provider="inicis",
        disabled_message="KG이니시스 간편인증이 비활성화되어 있습니다.",
        adapter_endpoint="inicis_start.php",
    )


@csrf_exempt
@never_cache
def cert_inicis_result_view(request):
    return _cert_result_view(
        request,
        kind="simple",
        provider="inicis",
        disabled_message="KG이니시스 간편인증이 비활성화되어 있습니다.",
    )


@never_cache
def cert_kcp_start_view(request):
    return _cert_start_view(
        request,
        kind="hp",
        provider="kcp",
        disabled_message="NHN KCP 휴대폰 본인확인이 비활성화되어 있습니다.",
        adapter_endpoint="kcp_start.php",
    )


@csrf_exempt
@never_cache
def cert_kcp_result_view(request):
    return _cert_result_view(
        request,
        kind="hp",
        provider="kcp",
        disabled_message="NHN KCP 휴대폰 본인확인이 비활성화되어 있습니다.",
    )


@never_cache
def cert_kcp_v2_start_view(request):
    return _cert_start_view(
        request,
        kind="hp",
        provider="kcp_v2",
        disabled_message="NHN KCP 휴대폰 본인확인(api_v2)이 비활성화되어 있습니다.",
        adapter_endpoint="kcp_v2_start.php",
    )


@csrf_exempt
@never_cache
def cert_kcp_v2_result_view(request):
    return _cert_result_view(
        request,
        kind="hp",
        provider="kcp_v2",
        disabled_message="NHN KCP 휴대폰 본인확인(api_v2)이 비활성화되어 있습니다.",
    )
