"""Which scheduled jobs a site runs, worked out from its settings values.

This module never reads django.conf.settings. example/settings/base.py builds CELERY_BEAT_SCHEDULE
from it while the settings are still loading, when django.conf.settings would load a half-imported
settings module and miss every optional and plugin job. core.scheduled_jobs builds the same list
again from django.conf.settings once they are ready.
"""

from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from gnu_jango.plugins import load_plugins


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    apply_args: tuple[str, ...]
    dry_run_args: tuple[str, ...]
    interval_seconds: int = 300
    plugin: str = ""  # the slug of the plugin that owns the job; skipped while it is switched off

    def args(self, dry_run: bool) -> tuple[str, ...]:
        return self.dry_run_args if dry_run else self.apply_args


CORE_JOBS: tuple[ScheduledJob, ...] = (
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
    # Each kind of alert checks its own shop setting, so the job does nothing until one is on.
    ScheduledJob("send_shop_alerts", ("--apply", "--json"), ("--json",), 600),
)


def _text(value):
    return str(value or "").strip()


def _audit_retention_days(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def build_scheduled_jobs(get):
    """The jobs for the settings that ``get(name, default)`` reads."""
    jobs = list(CORE_JOBS)

    retention_days = _audit_retention_days(get("AUDIT_RETENTION_DAYS", 0))
    if retention_days:
        days = str(retention_days)
        jobs.append(ScheduledJob("purge_audit_history", ("--days", days), ("--days", days, "--dry-run")))

    # Optional semantic search: keep embeddings in step with edits. Incremental (unchanged text is
    # skipped) and capped per run so one run stays inside the worker time limit.
    if get("G5_AI_SEMANTIC_SEARCH", False) and _text(get("G5_AI_BASE_URL", "")):
        jobs.append(ScheduledJob("build_embeddings", ("--json", "--limit", "200"), ("--json", "--dry-run"), 900))

    # Optional review summaries: hourly, at most 20 model calls (about a second each on a warm local
    # model), so new reviews show up in the summary within the hour.
    if get("G5_AI_REVIEW_SUMMARIES", False) and _text(get("G5_AI_BASE_URL", "")) and _text(get("G5_AI_CHAT_MODEL", "")):
        jobs.append(ScheduledJob("summarize_reviews", ("--json", "--limit", "20"), ("--json", "--dry-run"), 3600))

    # Optional 정기구독 (Toss card billing): hourly, so a due subscription is charged early in its day
    # and a charge whose answer was lost is looked up within the hour; at most 50 a run (the rest wait
    # for the next hour), as an approval may take up to 60 s. The command itself does nothing
    # while the admin switch de_subscription_use is off.
    if get("SHOP_SUBSCRIPTIONS_ENABLED", False):
        jobs.append(
            ScheduledJob("charge_shop_subscriptions", ("--apply", "--json", "--limit", "50"), ("--json",), 3600)
        )

    # Optional shipment tracking (Delivery Tracker): every 5 minutes, at most 30 lookups per run. The
    # keys live in the shop settings, so the command itself also does nothing until 배송조회 is on
    # with both keys saved.
    if get("SHOP_DELIVERY_TRACKING_JOB", False):
        jobs.append(ScheduledJob("track_shipments", ("--apply", "--json", "--limit", "30"), ("--json",), 300))

    # Plugins (G5_PLUGINS) schedule their own management commands.
    for plugin in load_plugins(get("G5_PLUGINS", ()) or ()):
        jobs.extend(
            ScheduledJob(job.command, job.apply_args, job.dry_run_args, job.interval_seconds, plugin=plugin.slug)
            for job in plugin.jobs
        )

    names = [job.name for job in jobs]
    if len(set(names)) != len(names):
        raise ImproperlyConfigured(f"Two scheduled jobs share a name: {sorted(names)}")
    return tuple(jobs)
