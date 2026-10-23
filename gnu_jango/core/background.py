"""Database outbox, bounded retries, leases and inspectable dead letters.

Enqueue only writes to the current DB transaction: no threads, eager tasks or broker I/O on
the request path. Beat publishes due UUIDs. A lost Redis message is republished after a lease.
"""
import logging
import hashlib
import random
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from .background_models import BackgroundJob

logger = logging.getLogger(__name__)
_executing = ContextVar("background_job_executing", default=False)
QUEUES = {"scheduled": "maintenance", "mail": "communications", "sms": "communications",
          "sms_event": "communications", "payment_webhook": "payments", "thumbnail": "media", "image": "media"}
UNCERTAIN_KINDS = {"mail", "sms"}


class PermanentJobError(Exception):
    def __init__(self, message="Operation rejected", *, code="permanent_failure"):
        super().__init__(message)
        self.code = code


class DeliveryUncertain(PermanentJobError):
    """The provider may have accepted a message. Automatic resend risks a duplicate."""


class RetryableJobError(Exception):
    """A known non-delivery, for example an SMTP 4xx rejection before acceptance."""


def enabled():
    return bool(getattr(settings, "BACKGROUND_JOBS_ENABLED", False))


def executing():
    return _executing.get()


@contextmanager
def execution_context():
    token = _executing.set(True)
    try:
        yield
    finally:
        _executing.reset(token)


def enqueue(kind, payload, *, dedupe_key=None, active_key=None, max_attempts=5):
    if kind not in QUEUES:
        raise ValueError("Unknown background job kind")
    try:
        with transaction.atomic():
            operation = str(payload.get("name", kind))[:80] if kind == "scheduled" else kind
            resource_key = resource_digest(payload["name"]) if kind == "image" else ""
            return BackgroundJob.objects.create(kind=kind, operation=operation, resource_key=resource_key,
                                                queue=QUEUES[kind], payload=payload,
                                                dedupe_key=dedupe_key, active_key=active_key,
                                                max_attempts=max_attempts)
    except IntegrityError:
        if dedupe_key:
            existing = BackgroundJob.objects.filter(dedupe_key=dedupe_key).first()
            if existing:
                return existing
        if active_key:
            existing = BackgroundJob.objects.filter(active_key=active_key).first()
            if existing:
                return existing
        raise


def resource_digest(name):
    return hashlib.sha256(str(name).encode()).hexdigest()


def enqueue_scheduled(name):
    from .scheduled_jobs import select_jobs
    job = select_jobs([name])[0]
    now = timezone.now()
    bucket = int(now.timestamp()) // job.interval_seconds
    return enqueue("scheduled", {"name": name}, dedupe_key=f"scheduled:{name}:{bucket}",
                   active_key=f"scheduled:{name}")


def _finish_failure(job, error, *, uncertain=False):
    now = timezone.now()
    uncertain = uncertain or (job.kind in UNCERTAIN_KINDS and not isinstance(error, (RetryableJobError, PermanentJobError)))
    terminal = isinstance(error, PermanentJobError) or uncertain or job.attempts >= job.max_attempts
    code = "delivery_uncertain" if uncertain or isinstance(error, DeliveryUncertain) else getattr(error, "code", type(error).__name__)[:80]
    delay = min(1800, 15 * 2 ** min(job.attempts - 1, 7)) + random.randint(0, 10)
    updates = {"status": "dead" if terminal else "pending", "error_code": code,
               "updated_at": now, "lease_until": None, "claim_token": None, "dispatched_at": None,
               "available_at": now + timedelta(seconds=delay)}
    if terminal:
        updates.update(active_key=None, finished_at=now)
    with transaction.atomic():
        changed = BackgroundJob.objects.filter(pk=job.pk, status="running", claim_token=job.claim_token).update(**updates)
        if terminal and changed:
            from .background_handlers import mail_campaign_finished
            mail_campaign_finished(job, success=False, error_code=code)
    logger.warning("Background job %s kind=%s status=%s error_type=%s", job.pk, job.kind, updates["status"], code)
    return {"id": str(job.pk), "status": updates["status"], "retry_in": delay}


def recover_expired(limit=100):
    rows = BackgroundJob.objects.filter(status="running", lease_until__lte=timezone.now()).order_by("lease_until")[:limit]
    for job in rows:
        _finish_failure(job, RuntimeError("Worker lease expired"), uncertain=job.kind in UNCERTAIN_KINDS)


def dispatch_due(limit=100):
    """Publish IDs only. Pending rows survive broker failures and Redis data loss."""
    from example.celery import app
    recover_expired(limit)
    now = timezone.now()
    stale = now - timedelta(seconds=getattr(settings, "BACKGROUND_DISPATCH_LEASE", 60))
    rows = BackgroundJob.objects.filter(status="pending", available_at__lte=now).filter(
        Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=stale)).order_by("available_at")[:limit]
    published = 0
    for job in rows:
        if not BackgroundJob.objects.filter(pk=job.pk, status="pending", dispatched_at=job.dispatched_at).update(dispatched_at=now):
            continue
        try:
            app.send_task("core.execute_background_job", args=[str(job.pk)], queue=job.queue,
                          ignore_result=True, retry=False, argsrepr=f"('{job.pk}',)")
        except Exception as exc:
            BackgroundJob.objects.filter(pk=job.pk, status="pending", dispatched_at=now).update(dispatched_at=None)
            logger.warning("Background dispatch unavailable error_type=%s", type(exc).__name__)
            break  # Avoid holding the dispatcher for one connection timeout per row.
        published += 1
    return {"published": published}


def execute_job(job_id):
    from .background_handlers import handle
    now = timezone.now()
    token = uuid.uuid4()
    lease = now + timedelta(seconds=getattr(settings, "BACKGROUND_JOB_LEASE", 360))
    claimed = BackgroundJob.objects.filter(pk=job_id, status="pending", available_at__lte=now).update(
        status="running", attempts=F("attempts") + 1, claim_token=token, lease_until=lease, updated_at=now)
    if not claimed:
        return {"id": str(job_id), "status": "skipped"}
    job = BackgroundJob.objects.get(pk=job_id, claim_token=token)
    try:
        with execution_context():
            handle(job)
    except Exception as exc:
        # Unknown network outcomes must be reviewed rather than automatically resent.
        return _finish_failure(job, exc)
    with transaction.atomic():
        changed = BackgroundJob.objects.filter(pk=job.pk, status="running", claim_token=token).update(
            status="succeeded", payload={}, active_key=None, claim_token=None, lease_until=None,
            finished_at=timezone.now(), updated_at=timezone.now(), error_code="")
        if changed:
            from .background_handlers import mail_campaign_finished
            mail_campaign_finished(job, success=True)
    return {"id": str(job_id), "status": "succeeded" if changed else "lease_lost"}


def replay(job, *, allow_uncertain=False):
    if job.status != "dead" or not job.payload or job.error_code in {"payload_expired", "source_deleted"}:
        return False
    if job.error_code == "delivery_uncertain" and not allow_uncertain:
        return False
    active_key = None
    if job.kind == "scheduled":
        active_key = f"scheduled:{job.payload['name']}"
    elif job.kind == "thumbnail":
        from .thumbnails import thumbnail_artifact_name
        active_key = f"thumbnail:{thumbnail_artifact_name(**job.payload)}"
    try:
        with transaction.atomic():
            return bool(BackgroundJob.objects.filter(pk=job.pk, status="dead").update(
                status="pending", attempts=0, available_at=timezone.now(), dispatched_at=None,
                finished_at=None, error_code="", updated_at=timezone.now(), active_key=active_key))
    except IntegrityError:
        return False  # Another pending/running job already owns this resource.


def purge_finished():
    now = timezone.now()
    # Erase private payloads independently of the longer, metadata-only failure history.
    scrubbed = BackgroundJob.objects.filter(status="dead", finished_at__lt=now - timedelta(days=7)).exclude(payload={}).update(payload={})
    deleted, _ = BackgroundJob.objects.filter(
        Q(status="succeeded", finished_at__lt=now - timedelta(days=7)) |
        Q(status="dead", finished_at__lt=now - timedelta(days=30))).delete()
    return {"scrubbed": scrubbed, "deleted": deleted}
