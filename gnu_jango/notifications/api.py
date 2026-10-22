import logging

from django.conf import settings
from django.utils.cache import patch_cache_control
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

from gnu_jango.api.authentication import SessionJWTAuthentication
from gnu_jango.api.response import api_error, api_response

from .tickets import issue_ticket

logger = logging.getLogger(__name__)


class TicketThrottle(UserRateThrottle):
    scope = "notification-ticket"
    rate = "30/min"


@api_view(["POST"])
@authentication_classes([SessionJWTAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([TicketThrottle])
def ticket_view(request):
    if not settings.NOTIFICATION_WS_ENABLED:
        response = api_response(data={"enabled": False})
    else:
        try:
            ticket = issue_ticket(request)
        except Exception as exc:
            logger.warning("notification_ticket_failed error_type=%s", type(exc).__name__)
            response = api_error("Realtime notifications are temporarily unavailable.", status=503, code="realtime_unavailable")
        else:
            response = api_response(data={
                "enabled": True, "ticket": ticket, "expires_in": settings.NOTIFICATION_TICKET_TTL,
                "websocket_url": settings.NOTIFICATION_WS_URL,
            })
    patch_cache_control(response, private=True, no_store=True)
    return response
