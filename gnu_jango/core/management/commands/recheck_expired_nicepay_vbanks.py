"""Look up, once a day, the NICEPAY virtual accounts this shop expired while NICEPAY kept them open."""

import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q
from django.utils import timezone

from gnu_jango.api.shop_nicepay import recheck_expired_nicepay_vbank
from gnu_jango.api.shop_payments import PaymentCancelError
from gnu_jango.shop.models import ShopPaymentAttempt

logger = logging.getLogger(__name__)

# Banks take no deposit after the deadline, so a deposit found here is already an anomaly; a month
# covers NICEPAY's settlement lag with room to spare, and then the account is left alone.
WATCH_FOR = timedelta(days=30)
# The job is scheduled daily; a run more often than that (by hand, or run_scheduled_jobs, which runs
# every job each time) still asks about each account at most once a day.
ASK_EVERY = timedelta(hours=20)
DEFAULT_LIMIT = 50
LISTED = 20


class Command(BaseCommand):
    help = (
        "Look up the NICEPAY virtual accounts that expired in this shop (attempt state expired) for up "
        "to 30 days, at most once a day each. A deposit found there is kept for a refund."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum lookups (default {DEFAULT_LIMIT}).")
        parser.add_argument("--apply", action="store_true", help="Ask NICEPAY and record the outcome. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"] or 0)
        if limit < 1:
            raise CommandError("--limit must be positive.")
        now = timezone.now()
        # An expired attempt is saved again only when it leaves that state, so updated_at is when it expired.
        attempts = list(
            ShopPaymentAttempt.objects.select_related("order")
            .filter(provider="nicepay", state="expired", order__isnull=False, updated_at__gte=now - WATCH_FOR)
            .filter(Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=now - ASK_EVERY))
            .order_by(F("last_checked_at").asc(nulls_first=True), "pk")[:limit]
        )
        summary = {
            "applied": bool(options["apply"]),
            "inspected": len(attempts),
            "open": 0,
            "closed": 0,
            "late_deposit": 0,
            "failed": 0,
            "samples": [],
        }
        failures = []
        for attempt in attempts:
            if not options["apply"]:
                self.add_sample(summary, attempt, "planned")
                continue
            try:
                outcome = recheck_expired_nicepay_vbank(attempt)
            except PaymentCancelError as exc:
                outcome = "failed"
                failures.append(f"{attempt.od_id}: {exc}")
            except Exception as exc:  # noqa: BLE001 - one account must not stop the others
                logger.exception("order %s: the expired NICEPAY account recheck failed", attempt.od_id)
                outcome = "failed"
                failures.append(f"{attempt.od_id}: {type(exc).__name__}: {exc}")
            summary[outcome] += 1
            self.add_sample(summary, attempt, outcome)

        if options["json"]:
            self.stdout.write(json.dumps({**summary, "failures": failures[:LISTED]}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Expired NICEPAY account recheck: "
                f"inspected={summary['inspected']} open={summary['open']} closed={summary['closed']} "
                f"late_deposit={summary['late_deposit']} failed={summary['failed']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )
            for failure in failures[:LISTED]:
                self.stderr.write(failure)
        if failures:
            raise CommandError(f"Could not recheck {len(failures)} expired NICEPAY account(s).")

    def add_sample(self, summary, attempt, action):
        if len(summary["samples"]) < LISTED:
            summary["samples"].append({"attempt_id": attempt.pk, "order_id": attempt.od_id, "action": action})
