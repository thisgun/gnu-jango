"""Reconcile NICEPAY attempts whose approval result was never safely applied locally."""

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gnu_jango.api.shop_nicepay import recover_nicepay_attempt
from gnu_jango.shop.models import ShopPaymentAttempt

RECOVERY_STATES = ("approving", "uncertain", "approved_local_failed")
DEFAULT_MINUTES = 15


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
        parser.add_argument("--limit", type=int, default=100, help="Maximum attempts to inspect.")
        parser.add_argument("--apply", action="store_true", help="Apply recovery. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        minutes = int(options["minutes"])
        limit = int(options["limit"])
        if minutes < 1 or limit < 1:
            raise CommandError("--minutes and --limit must be positive integers.")
        cutoff = timezone.now() - timedelta(minutes=minutes)
        attempts = list(
            ShopPaymentAttempt.objects.filter(
                provider="nicepay",
                state__in=RECOVERY_STATES,
                updated_at__lt=cutoff,
            ).order_by("updated_at")[:limit]
        )
        summary = {
            "applied": bool(options["apply"]),
            "minutes": minutes,
            "inspected": len(attempts),
            "recovered": 0,
            "failed": 0,
            "samples": [],
        }
        for attempt in attempts:
            if not options["apply"]:
                self._sample(summary, attempt, "planned")
                continue
            recovered, error = recover_nicepay_attempt(attempt)
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
                f"failed={summary['failed']} minutes={minutes} "
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
