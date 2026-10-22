from importlib.util import find_spec
from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, register


@register()
def realtime_checks(app_configs, **kwargs):
    if not getattr(settings, "NOTIFICATION_WS_ENABLED", False):
        return []
    errors = []
    if any(find_spec(package) is None for package in ("channels", "channels_redis")):
        errors.append(Error("Install requirements-realtime.txt before enabling notifications.", id="notifications.E001"))
    origins = settings.NOTIFICATION_WS_ORIGINS
    if not origins or any(not _valid_origin(origin) for origin in origins):
        errors.append(Error("NOTIFICATION_WS_ORIGINS requires explicit http(s) origins, without wildcards or paths.", id="notifications.E002"))
    url = settings.NOTIFICATION_WS_URL
    try:
        parsed = urlsplit(url)
        relative = url == "/ws/notifications/"
        absolute = parsed.scheme in ("ws", "wss") and parsed.hostname and parsed.path == "/ws/notifications/"
        valid_url = bool(
            (relative or absolute) and "*" not in url and parsed.port != 0
            and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        errors.append(Error("NOTIFICATION_WS_URL must point to /ws/notifications/ using ws(s) or a relative path.", id="notifications.E003"))
    if not settings.DEBUG and (url.startswith("ws:") or any(not origin.startswith("https://") for origin in origins)):
        errors.append(Error("Production notification transport requires HTTPS origins and WSS.", id="notifications.E004"))
    return errors


def _valid_origin(origin):
    try:
        url = urlsplit(origin)
        return bool(
            url.scheme in ("http", "https") and url.hostname and url.port != 0
            and "*" not in origin and not url.path and not url.query and not url.fragment
            and not url.username and not url.password
        )
    except ValueError:
        return False
