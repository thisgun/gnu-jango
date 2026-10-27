"""Superuser-only, audited member impersonation for support.

The Django admin session is switched to the member, and a short-lived member access cookie is set
so the Next.js/API storefront also renders as that member. The session keeps the acting admin id.
``/impersonation/stop/`` requires the acting admin's password, restores the admin session, and clears
the storefront auth cookies.

The read-only middleware rejects unsafe requests while impersonating, including token-only requests
that carry the ``imp`` claim. A preview expires after 30 minutes. Stop the impersonation before
performing any operation that changes member data.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
    logout,
)
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from gnu_jango.api.auth_sessions import issue_refresh_token
from gnu_jango.utils.lib import get_client_ip

User = get_user_model()

SESSION_IMPERSONATOR_KEY = "g5_impersonator_id"
SESSION_TARGET_KEY = "g5_impersonation_target_id"
SESSION_STARTED_KEY = "g5_impersonation_started_at"
SESSION_REFRESH_JTI_KEY = "g5_impersonation_refresh_jti"
SESSION_EXPIRY_LOGGED_KEY = "g5_impersonation_expiry_logged"
SESSION_STOP_ATTEMPTS_KEY = "g5_impersonation_stop_attempts"
STOP_PATH = "/impersonation/stop/"
IMPERSONATION_PAGE_PATH = "/impersonation/"
IMPERSONATION_LOGOUT_PATH = "/impersonation/logout/"
ADMIN_LOGOUT_PATH = "/admin/logout/"
IMPERSONATION_MAX_SECONDS = 30 * 60
STOP_MAX_ATTEMPTS = 5
AUTH_COOKIE_NAMES = ("g5_token", "g5_refresh", "g5_auth_hint", "g5_auto_login")


def _cookie_kwargs(request):
    return {"path": "/", "secure": request.is_secure(), "samesite": "Lax"}


def _clear_auth_cookies(response):
    for name in AUTH_COOKIE_NAMES:
        response.delete_cookie(name, path="/", samesite="Lax")


def _blacklist_refresh(jti):
    if not jti:
        return
    row = OutstandingToken.objects.filter(jti=jti).first()
    if row is not None:
        BlacklistedToken.objects.get_or_create(token=row)


def impersonation_expired(request):
    raw_started = request.session.get(SESSION_STARTED_KEY)
    if not raw_started:
        return False
    try:
        started = datetime.fromisoformat(raw_started)
    except (TypeError, ValueError):
        return True
    if timezone.is_naive(started):
        started = timezone.make_aware(started)
    return timezone.now() - started > timedelta(seconds=IMPERSONATION_MAX_SECONDS)


def _switch_session_user(request, user):
    """Set Django's session auth keys without calling login().

    ``login()`` flushes the session when the user changes, which would discard the impersonation
    marker and the saved cookies. It also updates last_login; a support preview should not look like
    a member sign-in. The session hash keeps the normal AuthenticationMiddleware checks in place.
    """
    request.session.cycle_key()
    request.session[SESSION_KEY] = str(user.pk)
    request.session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    request.session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    request.user = user
    request.session.modified = True


def _audit(admin, target, message, *, request=None):
    # Django 6.1 removed LogEntryManager.log_action; log_actions accepts the affected objects.
    client_ip = get_client_ip(request) if request is not None else ""
    detail = f"{message}; ip={client_ip or '-'}"
    LogEntry.objects.log_actions(admin.pk, [target], CHANGE, detail, single_object=True)


def end_impersonation_session(request, reason):
    """End a preview without the admin password: logout, audit, revoke, clear cookies."""
    admin_id = request.session.get(SESSION_IMPERSONATOR_KEY)
    target_id = request.session.get(SESSION_TARGET_KEY)
    jti = request.session.get(SESSION_REFRESH_JTI_KEY, "")
    admin = User.objects.filter(pk=admin_id).first() if admin_id else None
    target = User.objects.filter(pk=target_id).first() if target_id else None
    _blacklist_refresh(jti)
    if admin is not None:
        _audit(admin, target or admin, reason, request=request)
    logout(request)


def log_impersonation_expiry(request):
    if not request.session.get(SESSION_IMPERSONATOR_KEY) or request.session.get(SESSION_EXPIRY_LOGGED_KEY):
        return
    admin_id = request.session.get(SESSION_IMPERSONATOR_KEY)
    target_id = request.session.get(SESSION_TARGET_KEY)
    admin = User.objects.filter(pk=admin_id).first() if admin_id else None
    target = User.objects.filter(pk=target_id).first() if target_id else None
    if admin is not None:
        _audit(admin, target or admin, "Impersonation expired", request=request)
    request.session[SESSION_EXPIRY_LOGGED_KEY] = True
    request.session.modified = True


def _set_member_access_cookie(response, request, access_token):
    lifetime = settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    response.set_cookie(
        "g5_token",
        access_token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        **_cookie_kwargs(request),
    )
    response.set_cookie(
        "g5_auth_hint",
        "1",
        max_age=int(lifetime.total_seconds()),
        httponly=False,
        **_cookie_kwargs(request),
    )
    # Never let the admin's refresh cookie silently refresh the member preview or vice versa.
    response.delete_cookie("g5_refresh", path="/", samesite="Lax")
    response.delete_cookie("g5_auto_login", path="/", samesite="Lax")


@require_POST
def start_impersonation(request, object_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers may impersonate members.")
    target = get_object_or_404(User, pk=object_id)
    if target.pk == request.user.pk:
        messages.error(request, "You cannot impersonate yourself.")
        return redirect("admin:auth_user_change", object_id=target.pk)
    if target.is_staff or target.is_superuser:
        messages.error(request, "Admin and staff accounts cannot be impersonated.")
        return redirect("admin:auth_user_change", object_id=target.pk)
    if not target.is_active:
        messages.error(request, "Inactive members cannot be impersonated.")
        return redirect("admin:auth_user_change", object_id=target.pk)
    if request.session.get(SESSION_IMPERSONATOR_KEY):
        messages.error(request, "Stop the current impersonation before starting another one.")
        return redirect("impersonation")

    admin = request.user
    _switch_session_user(request, target)
    request.session[SESSION_IMPERSONATOR_KEY] = admin.pk
    request.session[SESSION_TARGET_KEY] = target.pk
    request.session[SESSION_STARTED_KEY] = timezone.now().isoformat()
    refresh = issue_refresh_token(target, request)
    request.session[SESSION_REFRESH_JTI_KEY] = str(refresh["jti"])
    access = refresh.access_token
    access["imp"] = str(admin.pk)
    _audit(admin, target, "Impersonation started", request=request)

    response = redirect("impersonation")
    _set_member_access_cookie(response, request, str(access))
    return response


def impersonation_page(request):
    admin_id = request.session.get(SESSION_IMPERSONATOR_KEY)
    if not admin_id:
        return redirect("index")
    target = User.objects.filter(pk=request.session.get(SESSION_TARGET_KEY)).first()
    admin = User.objects.filter(pk=admin_id).first()
    return render(
        request,
        "users/impersonation.html",
        {
            "target": target,
            "admin": admin,
            "started_at": request.session.get(SESSION_STARTED_KEY, ""),
            "expired": impersonation_expired(request),
        },
    )


@require_POST
def stop_impersonation(request):
    admin_id = request.session.get(SESSION_IMPERSONATOR_KEY)
    if not admin_id:
        return redirect("index")
    target_id = request.session.get(SESSION_TARGET_KEY)
    target = User.objects.filter(pk=target_id).first()
    refresh_jti = request.session.get(SESSION_REFRESH_JTI_KEY, "")
    admin = User.objects.filter(pk=admin_id, is_active=True, is_staff=True).first()

    if admin is None:
        _blacklist_refresh(refresh_jti)
        logout(request)
        response = HttpResponseRedirect(reverse("admin:login"))
        _clear_auth_cookies(response)
        return response
    if not admin.check_password(str(request.POST.get("password") or "")):
        attempts = int(request.session.get(SESSION_STOP_ATTEMPTS_KEY) or 0) + 1
        request.session[SESSION_STOP_ATTEMPTS_KEY] = attempts
        if attempts >= STOP_MAX_ATTEMPTS:
            _blacklist_refresh(refresh_jti)
            _audit(admin, target or admin, "Impersonation stopped after repeated password failures", request=request)
            logout(request)
            response = HttpResponseRedirect(reverse("admin:login"))
            _clear_auth_cookies(response)
            return response
        messages.error(request, "Enter the acting admin password to stop impersonation.")
        return redirect("impersonation")

    _blacklist_refresh(refresh_jti)
    _switch_session_user(request, admin)
    for key in (
        SESSION_IMPERSONATOR_KEY,
        SESSION_TARGET_KEY,
        SESSION_STARTED_KEY,
        SESSION_REFRESH_JTI_KEY,
        SESSION_EXPIRY_LOGGED_KEY,
        SESSION_STOP_ATTEMPTS_KEY,
    ):
        request.session.pop(key, None)
    _audit(admin, target or admin, "Impersonation stopped", request=request)
    response = redirect("admin:index")
    _clear_auth_cookies(response)
    return response


@require_POST
def logout_impersonation(request):
    """Allow a previewing admin to end the session without knowing the password."""
    end_impersonation_session(request, "Impersonation ended by logout")
    response = HttpResponseRedirect(reverse("admin:login"))
    _clear_auth_cookies(response)
    return response
