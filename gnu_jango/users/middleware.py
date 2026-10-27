"""Safety guard for support impersonation sessions."""

from django.http import HttpResponse, JsonResponse

from .impersonation import SESSION_IMPERSONATOR_KEY, STOP_PATH


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
        if (
            session is not None
            and session.get(SESSION_IMPERSONATOR_KEY)
            and request.method not in self.SAFE_METHODS
            and request.path.rstrip("/") != STOP_PATH.rstrip("/")
        ):
            message = "Impersonation is read-only. Stop impersonation before changing member data."
            if request.path.startswith("/api/"):
                return JsonResponse({"detail": message}, status=403)
            return HttpResponse(message, status=403, content_type="text/plain; charset=utf-8")
        return self.get_response(request)
