"""Short-lived, opaque, single-use socket credentials. Never put JWTs in URLs."""

import secrets
import time
from importlib import import_module
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user
from django.core.cache import caches
from rest_framework_simplejwt.settings import api_settings

from gnu_jango.api.authentication import SessionJWTAuthentication


class _Claims(dict):
    @property
    def payload(self):
        return self


def issue_ticket(request):
    user = request.user
    if request.auth is not None and hasattr(request.auth, "payload"):
        payload = request.auth.payload
        claims = {key: payload[key] for key in {api_settings.USER_ID_CLAIM, "exp", "tv", "sid", "jti"} if key in payload}
        identity = {"mode": "jwt", "claims": claims}
    else:
        session_key = request.session.session_key
        if not session_key:
            raise ValueError("A login session is required.")
        identity = {"mode": "session", "session_key": session_key}
    identity["user_id"] = user.pk
    ticket = secrets.token_urlsafe(32)
    caches["notifications"].set(f"ticket.{ticket}", identity, timeout=settings.NOTIFICATION_TICKET_TTL)
    return ticket


def consume_ticket(ticket):
    if not isinstance(ticket, str) or len(ticket) != 43 or not all(c.isalnum() or c in "_-" for c in ticket):
        return None
    cache = caches["notifications"]
    key = f"ticket.{ticket}"
    identity = cache.get(key)
    # Redis SET NX elects exactly one consumer, even on different ASGI workers.
    if not identity or not cache.add(f"consumed.{ticket}", True, timeout=settings.NOTIFICATION_TICKET_TTL + 5):
        return None
    cache.delete(key)
    return identity


def identity_is_valid(identity):
    if identity["mode"] == "jwt":
        claims = identity["claims"]
        if claims.get("exp", 0) <= time.time():
            return False
        user = SessionJWTAuthentication().get_user(_Claims(claims))
    else:
        engine = import_module(settings.SESSION_ENGINE)
        session = engine.SessionStore(session_key=identity["session_key"])
        user = get_user(SimpleNamespace(session=session))
    return bool(user.is_authenticated and user.is_active and user.pk == identity["user_id"])
