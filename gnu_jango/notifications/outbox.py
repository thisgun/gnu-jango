"""Isolate auxiliary notification writes from source transactions and retry durably."""

import asyncio
import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from gnu_jango.core.models import Notification, NotificationWork

from .delivery import user_group

logger = logging.getLogger(__name__)


def event_on_commit(user_id, event_key, payload, *, using="default"):
    """Source rollback discards this callback; notification failure cannot undo a payment."""
    def persist():
        try:
            work, _ = NotificationWork.objects.using(using).get_or_create(
                event_key=event_key, defaults={"kind": "create", "user_id": user_id, "payload": payload},
            )
            # Keep REST creation immediate in WSGI installs. No Redis or Celery I/O.
            process_one(work.pk, using=using)
        except Exception as exc:
            # An unavailable outbox cannot promise durability: alert explicitly.
            logger.error("notification_event_enqueue_failed event_key=%s error_type=%s", event_key, type(exc).__name__)

    transaction.on_commit(persist, using=using, robust=True)


async def _send_hint(user_id):
    from channels.layers import get_channel_layer

    async with asyncio.timeout(2):
        await get_channel_layer().group_send(user_group(user_id), {"type": "notifications.changed"})


def process_one(pk, *, using="default"):
    """Successful inbox creation and completion commit together; only workers send hints."""
    now = timezone.now()
    with transaction.atomic(using=using):
        rows = NotificationWork.objects.using(using).select_for_update(
            **({"skip_locked": True} if connections[using].features.has_select_for_update_skip_locked else {})
        )
        work = rows.filter(pk=pk, completed_at__isnull=True, available_at__lte=now).first()
        if work is None:
            return "skipped"
        try:
            with transaction.atomic(using=using):
                if work.kind == "create":
                    Notification.objects.using(using).get_or_create(
                        event_key=work.event_key, defaults={"user_id": work.user_id, **work.payload},
                    )
                elif work.kind == "hint":
                    if settings.NOTIFICATION_WS_ENABLED:
                        async_to_sync(_send_hint)(work.user_id)
                else:
                    raise ValueError("Unknown notification work kind")
        except Exception as exc:
            work.attempts += 1
            work.error_type = type(exc).__name__[:80]
            work.available_at = now + timedelta(seconds=min(3600, 5 * 2 ** min(work.attempts - 1, 10)))
            work.save(using=using, update_fields=["attempts", "error_type", "available_at"])
            logger.warning("notification_work_retry kind=%s error_type=%s", work.kind, work.error_type)
            return "failed_hint" if work.kind == "hint" else "failed"
        work.completed_at = timezone.now()
        work.error_type = ""
        work.save(using=using, update_fields=["completed_at", "error_type"])
    return "completed"


def process_pending(*, limit=50, using="default", dry_run=False):
    pending = NotificationWork.objects.using(using).filter(completed_at__isnull=True)
    due = pending.filter(available_at__lte=timezone.now())
    report = {"pending": pending.count(), "due": due.count(), "completed": 0, "failed": 0, "skipped": 0, "dry_run": dry_run}
    if dry_run:
        return report
    rows = list(due.order_by("available_at", "pk").values_list("pk", "kind")[:limit])
    redis_failed = False
    for pk, kind in rows:
        if kind == "hint" and redis_failed:
            report["skipped"] += 1
            continue
        result = process_one(pk, using=using)
        if result == "failed_hint":
            redis_failed = True  # one timeout per batch, not 50 during an outage
            result = "failed"
        report[result] += 1
    return report
