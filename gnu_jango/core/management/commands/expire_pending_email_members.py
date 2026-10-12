"""Expire members whose Gnuboard e-mail certification link has timed out."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gnu_jango.api.member_certify import email_certify_enabled, email_certify_expired, email_certify_minutes
from gnu_jango.api.member_lifecycle import leave_member
from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile

DEFAULT_LIMIT = 200


class Command(BaseCommand):
    help = (
        "Mark expired, uncertified members as withdrawn (Gnuboard5 g5_leave_member). "
        "Without --apply, list the work without changing data."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum expired members to handle (default {DEFAULT_LIMIT}).")
        parser.add_argument("--apply", action="store_true", help="Mark expired members as withdrawn. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("--limit must be positive.")

        now = timezone.now()
        minutes = email_certify_minutes()
        admin_id = (Config.objects.filter(name="cf_admin").values_list("value", flat=True).first() or "").strip()
        summary = {
            "applied": bool(options["apply"]),
            "minutes": minutes,
            "inspected": 0,
            "expired": 0,
            "left": 0,
            "skipped": 0,
            "disabled": not email_certify_enabled() or minutes < 1,
            "samples": [],
        }

        if not summary["disabled"]:
            candidates = (
                Profile.objects.filter(
                    email_certify__isnull=True,
                    leave_date__isnull=True,
                    user__is_active=True,
                )
                .exclude(user__username=admin_id)
                .select_related("user")
                .order_by("user__date_joined", "user_id")
            )
            for profile in candidates.iterator(chunk_size=200):
                summary["inspected"] += 1
                if not email_certify_expired(profile.user, profile, minutes, now):
                    continue
                summary["expired"] += 1
                action = "planned"
                if options["apply"]:
                    action = self._leave_if_still_expired(profile, admin_id)
                    if action == "left":
                        summary["left"] += 1
                    else:
                        summary["skipped"] += 1
                self._sample(summary, profile.user_id, action)
                if summary["expired"] >= limit:
                    break

        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Pending e-mail certification expiry: "
                f"inspected={summary['inspected']} expired={summary['expired']} left={summary['left']} "
                f"skipped={summary['skipped']} minutes={minutes} disabled={summary['disabled']} "
                f"mode={'apply' if options['apply'] else 'dry-run'}"
            )

    def _leave_if_still_expired(self, candidate, admin_id):
        with transaction.atomic():
            profile = Profile.objects.select_for_update().filter(pk=candidate.pk).first()
            if not profile:
                return "state_changed"
            user = profile.user
            if (
                not user.is_active
                or profile.email_certify is not None
                or profile.leave_date is not None
                or user.get_username() == admin_id
                or not email_certify_expired(user, profile, email_certify_minutes())
            ):
                return "state_changed"
            return "left" if leave_member(user) else "state_changed"

    def _sample(self, summary, user_id, action):
        if len(summary["samples"]) < 20:
            summary["samples"].append({"user_id": user_id, "action": action})
