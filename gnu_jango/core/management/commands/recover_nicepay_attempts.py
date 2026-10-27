"""Reconcile NICEPAY attempts whose approval result was never safely applied locally."""

import json
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.api.shop_nicepay import recover_nicepay_attempt
from gnu_jango.shop.models import ShopPaymentAttempt

RECOVERY_STATES = ("approving", "uncertain", "approved_local_failed", "pending_deposit")
DEFAULT_MINUTES = 15
DEFAULT_LIMIT = 20
MIN_TIME_BUDGET = 5
MAX_TIME_BUDGET = 55


class Command(BaseCommand):
    help = (
        "Reconcile stale NICEPAY approving/uncertain/approved_local_failed attempts through the "
        "official transaction lookup. It never calls the approval API again."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=DEFAULT_MINUTES,
            help=f"Only attempts older than this many minutes (default {DEFAULT_MINUTES}).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Maximum attempts to inspect (default {DEFAULT_LIMIT}).",
        )
        parser.add_argument("--apply", action="store_true", help="Apply recovery. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        minutes = int(options["minutes"])
        limit = int(options["limit"])
        if minutes < 1 or limit < 1:
            raise CommandError("--minutes and --limit must be positive integers.")
        budget = max(
            MIN_TIME_BUDGET,
            min(
                int(getattr(settings, "SHOP_NICEPAY_RECOVERY_TIME_BUDGET", 40) or 40),
                MAX_TIME_BUDGET,
            ),
        )
        cutoff = timezone.now() - timedelta(minutes=minutes)
        attempts = list(
            ShopPaymentAttempt.objects.select_related("order").filter(
                provider="nicepay",
                state__in=RECOVERY_STATES,
                updated_at__lt=cutoff,
            ).order_by("updated_at")[:limit]
        )
        summary = {
            "applied": bool(options["apply"]),
            "minutes": minutes,
            "limit": limit,
            "time_budget_seconds": budget,
            "inspected": len(attempts),
            "recovered": 0,
            "failed": 0,
            "timed_out": False,
            "samples": [],
        }
        started = time.monotonic()
        for attempt in attempts:
            if time.monotonic() - started >= budget:
                summary["timed_out"] = True
                break
            if not options["apply"]:
                self._sample(summary, attempt, "planned")
                continue
            if attempt.order is None:
                ShopPaymentAttempt.objects.filter(pk=attempt.pk).update(
                    state="failed",
                    last_error="NICEPAY recovery skipped because the order was deleted.",
                    recovery_attempts=attempt.recovery_attempts + 1,
                )
                summary["failed"] += 1
                self._sample(summary, attempt, "failed:order_missing")
                continue
            try:
                recovered, error = recover_nicepay_attempt(attempt)
            except Exception as exc:  # noqa: BLE001 - one bad attempt must not stop the batch
                ShopPaymentAttempt.objects.filter(pk=attempt.pk).update(
                    last_error=str(exc)[:4000],
                    recovery_attempts=attempt.recovery_attempts + 1,
                )
                summary["failed"] += 1
                self._sample(summary, attempt, f"failed:exception:{type(exc).__name__}"[:200])
                continue
            if error is None:
                summary["recovered"] += 1
                self._sample(summary, recovered, f"recovered:{recovered.state}")
            else:
                summary["failed"] += 1
                message = ""
                data = getattr(error, "data", None)
                if isinstance(data, dict):
                    message = str(data.get("message") or data.get("code") or "")
                self._sample(summary, attempt, f"failed:{message}"[:200])
        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "NICEPAY attempt recovery: "
                f"inspected={summary['inspected']} recovered={summary['recovered']} "
                f"failed={summary['failed']} minutes={minutes} budget={budget}s "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )

    def _sample(self, summary, attempt, action):
        if len(summary["samples"]) >= 20:
            return
        summary["samples"].append(
            {
                "attempt_id": attempt.pk,
                "order_id": attempt.od_id,
                "state": attempt.state,
                "action": action,
            }
        )
