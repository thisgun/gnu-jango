"""Persist change hints without Redis I/O in a web request."""

import logging
import uuid

from django.conf import settings
from django.db import transaction

from gnu_jango.core.models import NotificationWork

from .context import events_suppressed

logger = logging.getLogger(__name__)


def user_group(user_id):
    return f"notifications.user.{user_id}"


def queue_hints(user_ids, *, using="default"):
    """Call in the caller's transaction when a batch must be atomic."""
    if not settings.NOTIFICATION_WS_ENABLED or events_suppressed():
        return
    NotificationWork.objects.using(using).bulk_create([
        NotificationWork(event_key=f"hint:{uuid.uuid4().hex}", kind="hint", user_id=user_id)
        for user_id in set(user_ids) if user_id
    ], batch_size=100)


def invalidate_on_commit(user_id, *, using="default", notification_id=None):
    if not user_id or not settings.NOTIFICATION_WS_ENABLED or events_suppressed():
        return

    def persist():
        try:
            queue_hints([user_id], using=using)
        except Exception as exc:
            # Inbox state is committed and remains available through REST.
            logger.error("notification_hint_enqueue_failed error_type=%s", type(exc).__name__)

    transaction.on_commit(persist, using=using, robust=True)
