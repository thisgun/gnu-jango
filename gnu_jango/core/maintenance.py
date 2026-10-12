"""Small, explicit maintenance operations exposed to trusted administrators."""

from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.db import DatabaseError
from django.utils import timezone


def maintenance_snapshot():
    session_engine = getattr(settings, "SESSION_ENGINE", "")
    expired_sessions = None
    if session_engine in {
        "django.contrib.sessions.backends.db",
        "django.contrib.sessions.backends.cached_db",
    }:
        try:
            from django.contrib.sessions.models import Session

            expired_sessions = Session.objects.filter(expire_date__lt=timezone.now()).count()
        except DatabaseError:
            expired_sessions = None

    session_cache_alias = getattr(settings, "SESSION_CACHE_ALIAS", "default")
    cache_session_warning = (
        session_engine == "django.contrib.sessions.backends.cache"
        and session_cache_alias == "default"
    )
    return {
        "cache_backend": settings.CACHES.get("default", {}).get("BACKEND", ""),
        "session_engine": session_engine,
        "session_cache_alias": session_cache_alias,
        "cache_session_warning": cache_session_warning,
        "expired_sessions": expired_sessions,
    }


def run_maintenance_action(action):
    if action == "clear_cache":
        caches["default"].clear()
        return "Default cache entries cleared."
    if action == "clear_expired_sessions":
        call_command("clearsessions", verbosity=0)
        return "Expired sessions cleared. Active sessions were left untouched."
    if action == "cleanup_thumbnails":
        call_command("thumbnail", "cleanup", verbosity=0)
        return "Stale thumbnail references and derived files cleaned up. Original media files were left untouched."
    raise ValueError("Unknown maintenance action.")
