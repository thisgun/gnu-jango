"""Queueing and sending order messages.

notify() writes one OrderNotice per configured channel and sends them right after they are saved;
a message a channel refuses or does not take in time stays pending and the order_notify_retry job
sends it again, up to MAX_ATTEMPTS times within RETRY_WITHIN. RETRY_WITHIN is days, not hours,
because a site whose scheduler runs once a day (the Vercel cron) still gets a few tries. The job
also deletes sent and failed notices older than KEEP_FOR, so the log does not grow forever. A message is written once per order,
event and channel (the unique key), so a repeated hook never posts twice.

The first send runs inside the customer's (or the PG's) request. After a channel fails with an error
worth retrying, the request-time sends skip it for DOWN_SECONDS and leave its messages to the job,
so a channel that is down costs one timeout, not one per order.

Every sender first claims the notice (pending -> sending in one UPDATE) and only the one that got it
posts, so the request, the job and the admin action never post the same message twice. A claim left
behind by a crashed worker is released after LEASE.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import channels, conf, messages
from .models import OrderNotice

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_WITHIN = timedelta(days=3)
# The request that wrote a notice sends it itself; the retry job leaves fresh ones to it.
RETRY_AFTER = timedelta(minutes=1)
RETRY_BATCH = 50
LEASE = timedelta(minutes=10)
KEEP_FOR = timedelta(days=90)
PURGE_BATCH = 5000
DOWN_SECONDS = 300
KEY_LENGTH = 120

SENT, FAILED, SKIPPED = "sent", "failed", "skipped"


def _down_key(channel):
    return f"order_notify:down:{channel}"


def _key(event, old_status, new_status):
    if event in ("cancelled", "status"):
        return f"{event}:{old_status}>{new_status}"[:KEY_LENGTH]
    return event


def notify(order, event, *, old_status="", new_status=""):
    """Queue the message of ``event`` for every configured channel; the new notices' ids."""
    targets = channels.configured()
    if not targets:
        return []
    text = messages.build(
        order,
        event,
        old_status=old_status,
        new_status=new_status,
        full_name=conf.value("ORDER_NOTIFY_FULL_NAME"),
    )
    key = _key(event, old_status, new_status)
    created = []
    for channel in targets:
        notice, was_created = OrderNotice.objects.get_or_create(
            od_id=order.pk, key=key, channel=channel, defaults={"event": event, "text": text}
        )
        if was_created:
            created.append(notice.pk)
    if created:
        # After the notices are saved, so a send never holds a transaction open; robust: a failure
        # is logged and never reaches the customer's request.
        transaction.on_commit(lambda: send_pending(created, skip_down=True), robust=True)
    return created


def _claim(notice):
    """Take the notice for sending; False when another sender has it (or it is no longer pending)."""
    claimed = OrderNotice.objects.filter(pk=notice.pk, status=OrderNotice.PENDING, attempts=notice.attempts).update(
        status=OrderNotice.SENDING, claimed_at=timezone.now()
    )
    return claimed == 1


def send_notice(notice, *, skip_down=False):
    """Send one notice and record the outcome: SENT, FAILED, or SKIPPED (taken elsewhere, or its
    channel is resting after a failure and ``skip_down`` is set)."""
    if skip_down and cache.get(_down_key(notice.channel)):
        return SKIPPED
    if not _claim(notice):
        return SKIPPED
    attempts = notice.attempts + 1
    try:
        channels.send(notice.channel, notice.text)
    except channels.ChannelError as exc:
        gave_up = not exc.retry or attempts >= MAX_ATTEMPTS
        if exc.retry:
            cache.set(_down_key(notice.channel), True, DOWN_SECONDS)
        OrderNotice.objects.filter(pk=notice.pk).update(
            attempts=attempts,
            last_error=str(exc)[:255],
            status=OrderNotice.FAILED if gave_up else OrderNotice.PENDING,
            claimed_at=None,
        )
        logger.warning("Order notice %s to %s failed (attempt %s): %s", notice.pk, notice.channel, attempts, exc)
        return FAILED
    cache.delete(_down_key(notice.channel))
    OrderNotice.objects.filter(pk=notice.pk).update(
        attempts=attempts, last_error="", status=OrderNotice.SENT, sent_at=timezone.now(), claimed_at=None
    )
    return SENT


def send_pending(ids, *, skip_down=False):
    """Send the pending notices among ``ids``; {"sent": n, "failed": n, "skipped": n}."""
    report = {SENT: 0, FAILED: 0, SKIPPED: 0}
    for notice in OrderNotice.objects.filter(pk__in=list(ids), status=OrderNotice.PENDING).order_by("pk"):
        try:
            outcome = send_notice(notice, skip_down=skip_down)
        except Exception:
            # One broken notice must not stop the rest; its claim is released after LEASE.
            logger.exception("Order notice %s could not be sent", notice.pk)
            outcome = FAILED
        report[outcome] += 1
    return report


def _purgeable(now):
    """Sent and failed notices older than KEEP_FOR; pending and sending ones are never deleted."""
    return OrderNotice.objects.filter(
        status__in=(OrderNotice.SENT, OrderNotice.FAILED), created_at__lt=now - KEEP_FOR
    )


def purge(*, now=None):
    """Delete up to PURGE_BATCH old notices (the next run takes the rest); how many were deleted."""
    ids = list(_purgeable(now or timezone.now()).order_by("pk").values_list("pk", flat=True)[:PURGE_BATCH])
    return OrderNotice.objects.filter(pk__in=ids).delete()[0] if ids else 0


def retry(*, apply, now=None):
    """Send again up to RETRY_BATCH pending notices of the last RETRY_WITHIN; older ones are given up.
    Also deletes old sent and failed notices (purge)."""
    now = now or timezone.now()
    pending = OrderNotice.objects.filter(status=OrderNotice.PENDING)
    stale = OrderNotice.objects.filter(status=OrderNotice.SENDING, claimed_at__lt=now - LEASE)
    expired = pending.filter(created_at__lt=now - RETRY_WITHIN)
    due = pending.filter(created_at__gte=now - RETRY_WITHIN, created_at__lte=now - RETRY_AFTER)
    report = {
        "due": due.count(),
        "expired": expired.count(),
        "released": stale.count(),
        "purged": min(_purgeable(now).count(), PURGE_BATCH),
        SENT: 0,
        FAILED: 0,
        SKIPPED: 0,
        "dry_run": not apply,
    }
    if not apply:
        return report
    # Purge first: it is cheap, and must not depend on the sends below finishing (a serverless cron
    # can be cut off while it waits on a slow channel).
    report["purged"] = purge(now=now)
    stale.update(status=OrderNotice.PENDING, claimed_at=None)
    expired.update(status=OrderNotice.FAILED, last_error=f"{RETRY_WITHIN.days}일 안에 보내지 못했습니다.")
    batch = list(due.order_by("created_at", "pk").values_list("pk", flat=True)[:RETRY_BATCH])
    return {**report, **send_pending(batch)}
