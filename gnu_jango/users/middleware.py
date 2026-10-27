"""Safety guard for support impersonation sessions."""

from django.http import HttpResponse, JsonResponse
from rest_framework_simplejwt.tokens import AccessToken

from .impersonation import (
    IMPERSONATION_PAGE_PATH,
    SESSION_IMPERSONATOR_KEY,
    STOP_PATH,
    impersonation_expired,
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
        expired = marker and impersonation_expired(request)

        # An expired preview is closed to browsing. The stop page remains reachable so the acting
        # admin can authenticate and end it.
        if expired and path not in {stop_path, page_path}:
            return self._forbidden(request, "Impersonation expired. Stop it with the admin password.")

        if (marker or token_impersonated) and request.method not in self.SAFE_METHODS and path != stop_path:
            return self._forbidden(
                request,
                "Impersonation is read-only. Stop impersonation before changing member data.",
            )
        return self.get_response(request)

    @staticmethod
    def _forbidden(request, message):
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": message}, status=403)
        return HttpResponse(message, status=403, content_type="text/plain; charset=utf-8")
