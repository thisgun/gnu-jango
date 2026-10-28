"""Support impersonation: superuser-only, audited, read-only, and reversible."""

from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken

from gnu_jango.users.impersonation import (
    IMPERSONATION_HINT_COOKIE,
    IMPERSONATION_MAX_SECONDS,
    SESSION_IMPERSONATOR_KEY,
    SESSION_REFRESH_JTI_KEY,
    SESSION_STARTED_KEY,
    SESSION_TARGET_KEY,
)


class ImpersonationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="support-admin", email="support@example.test", password="password"
        )
        self.member = get_user_model().objects.create_user(
            username="support-member", email="member@example.test", password="password"
        )
        self.start_url = reverse("admin:auth_user_impersonate", args=[self.member.pk])
        self.client.force_login(self.admin)

    def start(self):
        return self.client.post(self.start_url)

    def test_the_user_change_page_shows_the_impersonation_button(self):
        response = self.client.get(reverse("admin:auth_user_change", args=[self.member.pk]))

        self.assertContains(response, reverse("admin:auth_user_impersonate", args=[self.member.pk]))
        self.assertContains(response, "이 회원으로 보기")

    def test_start_switches_the_session_and_sets_a_short_lived_member_cookie(self):
        response = self.start()

        self.assertRedirects(response, reverse("impersonation"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.member.pk))
        self.assertEqual(self.client.session[SESSION_IMPERSONATOR_KEY], self.admin.pk)
        self.assertEqual(self.client.session[SESSION_TARGET_KEY], self.member.pk)
        self.assertIn("g5_token", response.cookies)
        self.assertEqual(response.cookies["g5_refresh"].value, "")
        self.assertEqual(AccessToken(response.cookies["g5_token"].value)["imp"], str(self.admin.pk))
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                object_id=str(self.member.pk),
                change_message__contains="Impersonation started; ip=127.0.0.1",
            ).exists()
        )

    def test_start_sets_a_readable_banner_cookie_with_the_preview_expiry(self):
        before = int(timezone.now().timestamp())

        response = self.start()

        cookie = response.cookies[IMPERSONATION_HINT_COOKIE]
        self.assertFalse(cookie["httponly"])
        expires_at = int(cookie.value)
        token_expires_at = int(AccessToken(response.cookies["g5_token"].value)["exp"])
        self.assertGreater(expires_at, before)
        self.assertLessEqual(expires_at, min(token_expires_at, before + IMPERSONATION_MAX_SECONDS) + 2)
        self.assertAlmostEqual(int(cookie["max-age"]), expires_at - before, delta=2)

    def test_stop_and_logout_clear_the_banner_cookie(self):
        self.start()
        response = self.client.post(reverse("impersonation-stop"), {"password": "password"})
        self.assertEqual(response.cookies[IMPERSONATION_HINT_COOKIE].value, "")

        self.start()
        response = self.client.post(reverse("impersonation-logout"))
        self.assertEqual(response.cookies[IMPERSONATION_HINT_COOKIE].value, "")

    def test_stop_requires_the_admin_password_and_restores_the_admin_session(self):
        self.start()

        response = self.client.post(reverse("impersonation-stop"), {"password": "wrong"})

        self.assertRedirects(response, reverse("impersonation"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.member.pk))

        response = self.client.post(reverse("impersonation-stop"), {"password": "password"})

        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))
        self.assertNotIn(SESSION_IMPERSONATOR_KEY, self.client.session)
        self.assertEqual(response.cookies["g5_token"].value, "")
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="Impersonation stopped",
            ).exists()
        )

    def test_logout_without_password_revokes_the_preview(self):
        self.start()
        refresh_jti = self.client.session[SESSION_REFRESH_JTI_KEY]

        response = self.client.post(reverse("impersonation-logout"))

        self.assertRedirects(response, reverse("admin:login"), fetch_redirect_response=False)
        self.assertEqual(response.cookies["g5_token"].value, "")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh_jti).exists())
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="Impersonation ended by logout; ip=",
            ).exists()
        )

    def test_admin_logout_during_impersonation_is_an_escape_hatch(self):
        self.start()
        refresh_jti = self.client.session[SESSION_REFRESH_JTI_KEY]

        response = self.client.post(reverse("admin:logout"))

        self.assertRedirects(response, reverse("admin:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh_jti).exists())
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="Impersonation ended by logout",
            ).exists()
        )

    def test_missing_acting_admin_still_revokes_the_preview_token(self):
        self.start()
        refresh_jti = self.client.session[SESSION_REFRESH_JTI_KEY]
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])

        response = self.client.post(reverse("impersonation-stop"), {"password": "password"})

        self.assertRedirects(response, reverse("admin:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh_jti).exists())

    def test_repeated_wrong_stop_passwords_end_the_preview(self):
        self.start()
        refresh_jti = self.client.session[SESSION_REFRESH_JTI_KEY]

        for _ in range(5):
            response = self.client.post(reverse("impersonation-stop"), {"password": "wrong"})

        self.assertRedirects(response, reverse("admin:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh_jti).exists())
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="repeated password failures",
            ).exists()
        )

    def test_expiry_is_audited_with_the_request_ip(self):
        self.start()
        session = self.client.session
        session[SESSION_STARTED_KEY] = (timezone.now() - timedelta(hours=1)).isoformat()
        session.save()

        response = self.client.get("/api/v1/status")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="Impersonation expired; ip=127.0.0.1",
            ).exists()
        )

    def test_the_impersonation_session_is_read_only_for_unsafe_api_requests(self):
        self.start()

        response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 403)
        self.assertIn("읽기 전용", response.json()["detail"])

    def test_an_impersonated_access_token_alone_cannot_mutate(self):
        self.start()
        self.client.cookies.pop("sessionid", None)

        response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 403)
        self.assertIn("읽기 전용", response.json()["detail"])

    def test_an_expired_impersonation_stops_browsing_until_password_is_entered(self):
        self.start()
        session = self.client.session
        session[SESSION_STARTED_KEY] = (timezone.now() - timedelta(hours=1)).isoformat()
        session.save()

        response = self.client.get("/api/v1/status")

        self.assertEqual(response.status_code, 403)
        self.assertIn("시간이 끝났습니다", response.json()["detail"])

    def test_a_staff_user_cannot_impersonate(self):
        staff = get_user_model().objects.create_user(
            "support-staff", "staff@example.test", "pw", is_staff=True
        )
        self.client.force_login(staff)

        response = self.client.post(self.start_url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.session["_auth_user_id"], str(staff.pk))

    def test_staff_and_superuser_targets_are_refused(self):
        other_admin = get_user_model().objects.create_superuser(
            "other-admin", "other@example.test", "pw"
        )
        response = self.client.post(
            reverse("admin:auth_user_impersonate", args=[other_admin.pk])
        )

        self.assertRedirects(
            response,
            reverse("admin:auth_user_change", args=[other_admin.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))

    def test_inactive_targets_are_refused(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])

        response = self.start()

        self.assertRedirects(
            response,
            reverse("admin:auth_user_change", args=[self.member.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))

    def test_the_start_endpoint_is_post_only(self):
        self.assertEqual(self.client.get(self.start_url).status_code, 405)

    def test_the_impersonation_page_requires_an_active_preview(self):
        self.assertRedirects(
            self.client.get(reverse("impersonation")),
            reverse("index"),
            fetch_redirect_response=False,
        )
