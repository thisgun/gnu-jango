"""Support impersonation: superuser-only, audited, read-only, and reversible."""

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext

from gnu_jango.users.impersonation import (
    SESSION_IMPERSONATOR_KEY,
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
        self.assertContains(response, gettext("View as this member"))

    def test_start_switches_the_session_and_sets_a_short_lived_member_cookie(self):
        response = self.start()

        self.assertRedirects(response, reverse("impersonation"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.member.pk))
        self.assertEqual(self.client.session[SESSION_IMPERSONATOR_KEY], self.admin.pk)
        self.assertEqual(self.client.session[SESSION_TARGET_KEY], self.member.pk)
        self.assertIn("g5_token", response.cookies)
        self.assertEqual(response.cookies["g5_refresh"].value, "")
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                object_id=str(self.member.pk),
                change_message__contains="Impersonation started",
            ).exists()
        )

    def test_stop_restores_the_admin_session_and_previous_auth_cookie(self):
        self.client.cookies["g5_token"] = "admin-token"
        self.start()

        response = self.client.post(reverse("impersonation-stop"))

        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))
        self.assertNotIn(SESSION_IMPERSONATOR_KEY, self.client.session)
        self.assertEqual(response.cookies["g5_token"].value, "admin-token")
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=self.admin.pk,
                change_message__contains="Impersonation stopped",
            ).exists()
        )

    def test_the_impersonation_session_is_read_only_for_unsafe_api_requests(self):
        self.start()

        response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 403)
        self.assertIn("read-only", response.json()["detail"])

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
