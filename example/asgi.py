"""HTTP plus an explicitly enabled, origin-restricted private notification socket."""

import os

from django.core.asgi import get_asgi_application
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'example.settings')

django_application = get_asgi_application()

if settings.NOTIFICATION_WS_ENABLED:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.security.websocket import OriginValidator
    from django.core.exceptions import ImproperlyConfigured
    from django.urls import path

    from gnu_jango.notifications.checks import realtime_checks
    from gnu_jango.notifications.consumers import NotificationConsumer

    if realtime_checks(None):
        raise ImproperlyConfigured("Invalid notification transport settings; run manage.py check.")
    application = ProtocolTypeRouter({
        "http": django_application,
        "websocket": OriginValidator(
            URLRouter([path("ws/notifications/", NotificationConsumer.as_asgi())]),
            settings.NOTIFICATION_WS_ORIGINS,
        ),
    })
else:
    async def application(scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await django_application(scope, receive, send)
