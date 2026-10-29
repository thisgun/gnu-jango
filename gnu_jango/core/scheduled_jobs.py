"""The periodic maintenance jobs, run by `manage.py run_scheduled_jobs` or GET/POST /api/internal/cron.

Each job is an existing management command. They are idempotent and lock rows themselves
(select_for_update), so a duplicate cron delivery is harmless; a cache lock additionally skips a run
that overlaps one still in progress (effective across processes only with a shared cache backend).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command

logger = logging.getLogger(__name__)

LOCK_KEY = "gnu_jango:scheduled-jobs:lock"
LOCK_TIMEOUT_SECONDS = 15 * 60
MAX_TEXT_LENGTH = 300


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    apply_args: tuple[str, ...]
    dry_run_args: tuple[str, ...]
    interval_seconds: int = 300

    def args(self, dry_run: bool) -> tuple[str, ...]:
        return self.dry_run_args if dry_run else self.apply_args


SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob("expire_pending_payment_orders", ("--apply", "--json"), ("--json",), 60),
    ScheduledJob("expire_pending_email_members", ("--apply", "--json"), ("--json",), 3600),
    ScheduledJob("expire_toss_vbank_orders", ("--apply", "--json"), ("--json",), 60),
    ScheduledJob("recover_nicepay_attempts", ("--apply", "--json"), ("--json",), 300),
    # This one applies by default and takes --dry-run instead of --apply.
    ScheduledJob("cleanup_admin_privacy", (), ("--dry-run",), 86400),
    ScheduledJob("cleanup_search_clicks", ("--json",), ("--dry-run", "--json"), 86400),
    ScheduledJob("process_notifications", ("--apply", "--json"), ("--json",), 10),
    ScheduledJob("retry_search_index", ("--apply", "--json"), ("--json",), 30),
    ScheduledJob("check_search_health", ("--json",), ("--json", "--audit-limit", "0"), 600),
    ScheduledJob("save_order_points", ("--apply", "--json"), ("--json",)),
)

try:
    _AUDIT_RETENTION_DAYS = max(0, int(getattr(settings, "AUDIT_RETENTION_DAYS", 0) or 0))
except (TypeError, ValueError):
    _AUDIT_RETENTION_DAYS = 0

if _AUDIT_RETENTION_DAYS:
    _AUDIT_RETENTION_DAYS_TEXT = str(_AUDIT_RETENTION_DAYS)
    SCHEDULED_JOBS += (
        ScheduledJob(
            "purge_audit_history",
            ("--days", _AUDIT_RETENTION_DAYS_TEXT),
            ("--days", _AUDIT_RETENTION_DAYS_TEXT, "--dry-run"),
        ),
    )

# Optional semantic search: keep embeddings in step with edits. Incremental (unchanged text is
# skipped) and capped per run so one run stays inside the worker time limit.
if getattr(settings, "G5_AI_SEMANTIC_SEARCH", False) and str(getattr(settings, "G5_AI_BASE_URL", "") or "").strip():
    SCHEDULED_JOBS += (
        ScheduledJob("build_embeddings", ("--json", "--limit", "200"), ("--json", "--dry-run"), 900),
    )

# Optional review summaries: hourly, at most 20 model calls (about a second each on a warm local
# model), so new reviews show up in the summary within the hour.
if (
    getattr(settings, "G5_AI_REVIEW_SUMMARIES", False)
    and str(getattr(settings, "G5_AI_BASE_URL", "") or "").strip()
    and str(getattr(settings, "G5_AI_CHAT_MODEL", "") or "").strip()
):
    SCHEDULED_JOBS += (
        ScheduledJob("summarize_reviews", ("--json", "--limit", "20"), ("--json", "--dry-run"), 3600),
    )

JOB_NAMES = tuple(job.name for job in SCHEDULED_JOBS)


def default_runner(name, *args, stdout=None, stderr=None):
    call_command(name, *args, stdout=stdout, stderr=stderr)


@contextmanager
def job_lock():
    """Yield True when this process holds the run lock, False when another run holds it."""
    token = uuid.uuid4().hex
    try:
        acquired = cache.add(LOCK_KEY, token, LOCK_TIMEOUT_SECONDS)
    except Exception:  # A broken cache must not stop maintenance; run unlocked and say so.
        logger.warning("Scheduled jobs: cache lock unavailable, running without it.", exc_info=True)
        yield True
        return
    try:
        yield acquired
    finally:
        if acquired:
            try:
                if cache.get(LOCK_KEY) == token:
                    cache.delete(LOCK_KEY)
            except Exception:
                logger.warning("Scheduled jobs: could not release the cache lock.", exc_info=True)


def _summarize_output(output: str):
    """Keep scalar counters from a --json report (no per-row samples); else the last output line."""
    text = output.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1][:MAX_TEXT_LENGTH]
    if not isinstance(parsed, dict):
        return text[:MAX_TEXT_LENGTH]
    return {key: value for key, value in parsed.items() if isinstance(value, (str, int, float, bool)) or value is None}


def run_job(job: ScheduledJob, *, dry_run: bool, runner) -> dict:
    stdout, stderr = StringIO(), StringIO()
    started = time.monotonic()
    error = ""
    try:
        runner(job.name, *job.args(dry_run), stdout=stdout, stderr=stderr)
    except Exception as exc:  # Isolate every job: one failure must not stop the others.
        logger.exception("Scheduled job %s failed.", job.name)
        error = f"{type(exc).__name__}: {exc}"[:MAX_TEXT_LENGTH]
    return {
        "name": job.name,
        "status": "failed" if error else "ok",
        "duration_ms": int((time.monotonic() - started) * 1000),
        "summary": _summarize_output(stdout.getvalue()),
        "error": error,
    }


def run_scheduled_jobs(*, dry_run: bool = False, jobs=None, runner=None) -> dict:
    """Run every job (or the given subset) and return a JSON-serialisable report."""
    selected = tuple(jobs) if jobs is not None else SCHEDULED_JOBS
    runner = runner or default_runner
    report = {"dry_run": dry_run, "skipped": False, "ok": True, "succeeded": 0, "failed": 0, "jobs": []}

    with job_lock() as acquired:
        if not acquired:
            return {**report, "skipped": True, "reason": "Another scheduled-jobs run is still in progress."}
        results = [run_job(job, dry_run=dry_run, runner=runner) for job in selected]

    failed = sum(1 for result in results if result["status"] == "failed")
    return {**report, "ok": failed == 0, "succeeded": len(results) - failed, "failed": failed, "jobs": results}


def select_jobs(names) -> tuple[ScheduledJob, ...]:
    if not names:
        return SCHEDULED_JOBS
    unknown = sorted(set(names) - set(JOB_NAMES))
    if unknown:
        raise ValueError(f"Unknown scheduled job(s): {', '.join(unknown)}. Known: {', '.join(JOB_NAMES)}.")
    return tuple(job for job in SCHEDULED_JOBS if job.name in set(names))
