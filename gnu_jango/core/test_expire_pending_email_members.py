import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile


class ExpirePendingEmailMembersCommandTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.now = timezone.now()
        Config.objects.update_or_create(name="cf_use_email_certify", defaults={"value": "1"})
        Config.objects.update_or_create(name="cf_email_certify_minutes", defaults={"value": "60"})
        Config.objects.update_or_create(name="cf_admin", defaults={"value": "expiry-admin"})

    def make_member(self, username, *, issued_at, joined_at=None, certified=False, superuser=False):
        user = self.User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="Password-for-tests-123",
            is_superuser=superuser,
            date_joined=joined_at or issued_at,
        )
        profile = Profile.objects.get(user=user)
        profile.email_certify = issued_at if certified else None
        profile.email_certify_token = f"test-token.{int(issued_at.timestamp())}"
        profile.save(update_fields=["email_certify", "email_certify_token"])
        return user, profile

    def run_command(self, *args):
        output = StringIO()
        call_command("expire_pending_email_members", *args, stdout=output)
        return json.loads(output.getvalue())

    def test_dry_run_reports_expired_members_without_changing_them(self):
        issued_at = self.now - timedelta(hours=2)
        user, profile = self.make_member("pending_dry", issued_at=issued_at)

        summary = self.run_command("--json")

        self.assertEqual((summary["expired"], summary["left"], summary["applied"]), (1, 0, False))
        self.assertEqual(summary["samples"], [{"user_id": user.pk, "action": "planned"}])
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNone(profile.leave_date)
        self.assertTrue(profile.email_certify_token)

    def test_apply_withdraws_only_expired_members_and_revokes_their_tokens(self):
        issued_at = self.now - timedelta(hours=3)
        user, profile = self.make_member("pending_apply", issued_at=issued_at)
        refresh = RefreshToken.for_user(user)
        refresh_jti = refresh["jti"]
        Config.objects.create(
            name="social_id_expiry-test",
            value=json.dumps({"user_id": user.pk, "provider": "google"}),
        )
        self.make_member(
            "pending_recent",
            issued_at=self.now - timedelta(minutes=10),
            joined_at=self.now - timedelta(days=30),
        )
        self.make_member("expiry-admin", issued_at=issued_at, superuser=True)

        summary = self.run_command("--apply", "--json")

        self.assertEqual((summary["expired"], summary["left"], summary["skipped"]), (1, 1, 0))
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(profile.leave_date, timezone.localdate())
        self.assertEqual(profile.email_certify_token, "")
        self.assertEqual(profile.token_version, 1)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh_jti).exists())
        self.assertFalse(Config.objects.filter(name="social_id_expiry-test").exists())
        self.assertTrue(self.User.objects.get(username="pending_recent").is_active)
        self.assertTrue(self.User.objects.get(username="expiry-admin").is_active)

    def test_disabled_certification_or_zero_minutes_never_withdraws_members(self):
        self.make_member("pending_disabled", issued_at=self.now - timedelta(hours=3))
        for enabled, minutes in (("0", "60"), ("1", "0")):
            with self.subTest(enabled=enabled, minutes=minutes):
                Config.objects.update_or_create(name="cf_use_email_certify", defaults={"value": enabled})
                Config.objects.update_or_create(name="cf_email_certify_minutes", defaults={"value": minutes})
                summary = self.run_command("--apply", "--json")
                self.assertTrue(summary["disabled"])
                self.assertEqual(summary["left"], 0)
        self.assertTrue(self.User.objects.get(username="pending_disabled").is_active)

    def test_an_already_certified_member_is_not_a_candidate(self):
        self.make_member("pending_certified", issued_at=self.now - timedelta(hours=3), certified=True)

        summary = self.run_command("--apply", "--json")

        self.assertEqual((summary["expired"], summary["left"]), (0, 0))
