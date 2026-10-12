"""GET/POST /api/internal/cron -- run the scheduled jobs from an HTTP scheduler.

Vercel Cron calls the path with ``Authorization: Bearer <CRON_SECRET>``; Supabase pg_cron (pg_net) or any
external scheduler can send the same header. With CRON_SECRET unset the endpoint does not exist (404).
"""

import hmac

from django.conf import settings
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny

from gnu_jango.core import scheduled_jobs

from .response import api_error, api_response

BEARER_PREFIX = "Bearer "
# Shorter secrets are treated as unset: the endpoint has no throttle, so the secret must not be guessable.
MIN_SECRET_LENGTH = 16


def _has_valid_bearer(request, secret):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith(BEARER_PREFIX):
        return False
    supplied = header[len(BEARER_PREFIX):]
    return hmac.compare_digest(supplied.encode("utf-8"), secret.encode("utf-8"))


def _is_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@never_cache
@extend_schema(exclude=True)
@api_view(["GET", "POST"])
# The bearer token is the cron secret, not a JWT: keep DRF's JWT/session authenticators away from it.
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def cron_view(request):
    secret = str(getattr(settings, "CRON_SECRET", "") or "")
    if len(secret) < MIN_SECRET_LENGTH:
        return api_error("Not found.", status=404, code="not_found")
    if not _has_valid_bearer(request, secret):
        return api_error("Invalid or missing cron credentials.", status=401, code="unauthorized")

    report = scheduled_jobs.run_scheduled_jobs(dry_run=_is_truthy(request.query_params.get("dry_run")))
    if report["failed"]:
        errors = {job["name"]: job["error"] for job in report["jobs"] if job["status"] == "failed"}
        return api_response(report, errors=errors, status=500, ok=False)
    return api_response(report)
