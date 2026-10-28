"""Safety guard for support impersonation sessions."""

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from .impersonation import (
    ADMIN_LOGOUT_PATH,
    IMPERSONATION_LOGOUT_PATH,
    IMPERSONATION_PAGE_PATH,
    SESSION_IMPERSONATOR_KEY,
    STOP_PATH,
    _clear_auth_cookies,
    end_impersonation_session,
    impersonation_expired,
    log_impersonation_expiry,
)


def _impersonated_token(request):
    raw_token = request.COOKIES.get("g5_token", "")
    authorization = request.headers.get("Authorization") or ""
    if authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1].strip()
    if not raw_token:
        return ""
    try:
        payload = AccessToken(raw_token).payload
    except Exception:
        return ""
    return str(payload.get("imp") or "")


class ImpersonationReadOnlyMiddleware:
    """Reject state-changing requests while an admin is viewing as a member.

    The member access cookie is intentionally short-lived. While the admin session is in
    impersonation mode, only GET/HEAD/OPTIONS/TRACE requests and the explicit stop endpoint are
    allowed. This keeps CS previews from placing orders, changing addresses, or writing content.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        marker = bool(session is not None and session.get(SESSION_IMPERSONATOR_KEY))
        token_impersonated = (
            bool(_impersonated_token(request)) if not marker and request.method not in self.SAFE_METHODS else False
        )
        path = request.path.rstrip("/")
        stop_path = STOP_PATH.rstrip("/")
        page_path = IMPERSONATION_PAGE_PATH.rstrip("/")
        logout_paths = {
            IMPERSONATION_LOGOUT_PATH.rstrip("/"),
            ADMIN_LOGOUT_PATH.rstrip("/"),
        }
        expired = marker and impersonation_expired(request)

        if expired:
            log_impersonation_expiry(request)

        # A target member must always be able to abandon the preview without knowing the admin
        # password. The standard admin logout URL is wrapped here so its session flush still
        # revokes the issued refresh token and clears the storefront cookies.
        if marker and request.method == "POST" and path == ADMIN_LOGOUT_PATH.rstrip("/"):
            end_impersonation_session(request, "Impersonation ended by logout")
            response = HttpResponseRedirect(reverse("admin:login"))
            _clear_auth_cookies(response)
            return response

        # An expired preview is closed to browsing. The stop page remains reachable so the acting
        # admin can authenticate and end it, and logout is always available as an escape hatch.
        if expired and path not in {stop_path, page_path, *logout_paths}:
            return self._forbidden(request, "회원 미리보기 시간이 끝났습니다. 관리자 비밀번호로 미리보기를 종료하세요.")

        if (
            (marker or token_impersonated)
            and request.method not in self.SAFE_METHODS
            and path not in {stop_path, *logout_paths}
        ):
            return self._forbidden(
                request,
                "회원 미리보기는 읽기 전용입니다. 미리보기를 종료한 뒤 변경하세요.",
            )
        return self.get_response(request)

    @staticmethod
    def _forbidden(request, message):
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": message}, status=403)
        return HttpResponse(message, status=403, content_type="text/plain; charset=utf-8")
