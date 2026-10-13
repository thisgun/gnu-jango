"""Authentication hardening: already-issued access tokens die with the event that revokes them, social
login tickets only work in the client that started the flow, and the login-session list is real.

Covers the gaps closed before the open-source release:
- e-mail change, admin block (API and Django admin), admin password change and a stale profile save
  can no longer leave an access token or a refresh token usable;
- a social ticket leaked from one browser cannot be redeemed in another (login CSRF), while a native
  app proves its flow with a PKCE-style client_challenge / client_verifier pair;
- GET /api/v1/auth/sessions lists the member's live refresh sessions with the login time and marks the
  current one, and DELETE /api/v1/auth/sessions/<id> revokes one.
"""

import base64
import hashlib
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken

from gnu_jango.api import v1_auth
from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile

PASSWORD = "Str0ng-pass-99"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
ME_URL = "/api/v1/auth/me"
MEMBER_ME_URL = "/api/v1/members/me"
SESSIONS_URL = "/api/v1/auth/sessions"
EXCHANGE_URL = "/api/v1/auth/social/exchange"
SIGNUP_PROFILE_URL = "/api/v1/auth/social/signup-profile"
LINK_URL = "/api/v1/auth/social/link-existing"
REGISTER_URL = "/api/v1/auth/register"
START_URL = "/api/social/start.php"
SIGNUP_START_URL = "/api/social/signup.php"
CALLBACK_URL = "/api/social/callback.php"
HTTP_PATCH = "gnu_jango.api.v1_auth._http_json_request"
SOCIAL_SETTINGS = {"SOCIAL_KAKAO_REST_KEY": "kakao-key"}
KAKAO_USERINFO = {
    "id": 4242,
    "kakao_account": {"email": "k@example.test", "name": "Kim", "profile": {"nickname": "KakaoNick"}},
}

User = get_user_model()


def query_of(url):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query, keep_blank_values=True).items()}


def bearer(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def s256(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class HardeningBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def make_member(self, username, **extra):
        user = User.objects.create_user(
            username=username, email=f"{username}@example.test", password=PASSWORD, **extra
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.nickname = f"nick-{username}"
        profile.save()
        return User.objects.get(pk=user.pk)

    def login(self, username, agent="Test Browser", password=PASSWORD):
        response = APIClient().post(
            LOGIN_URL, {"mb_id": username, "mb_password": password}, format="json", HTTP_USER_AGENT=agent
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()["data"]

    def assert_signed_out(self, device):
        self.assertEqual(bearer(device["token"]).get(ME_URL).status_code, 401)
        self.assertEqual(
            APIClient().post(REFRESH_URL, {"refresh_token": device["refresh_token"]}, format="json").status_code, 401
        )

    def assert_signed_in(self, device):
        self.assertEqual(bearer(device["token"]).get(ME_URL).status_code, 200)

    def token_version(self, user):
        return Profile.objects.get(user=user).token_version


class AccessTokenRevocationTests(HardeningBase):
    def test_access_and_refresh_tokens_carry_the_members_token_version(self):
        member = self.make_member("tv_claims")
        Profile.objects.filter(user=member).update(token_version=7)
        device = self.login("tv_claims")
        self.assertEqual(AccessToken(device["token"])["tv"], 7)

    def test_an_access_token_of_an_older_token_version_is_refused_everywhere(self):
        member = self.make_member("tv_old")
        device = self.login("tv_old")
        Profile.objects.filter(user=member).update(token_version=5)
        self.assertEqual(bearer(device["token"]).get(ME_URL).status_code, 401)
        # The DRF authentication class used by the member views refuses it too.
        self.assertEqual(bearer(device["token"]).get(MEMBER_ME_URL).status_code, 401)

    def test_changing_the_e_mail_address_signs_out_every_other_device_and_reissues_this_one(self):
        member = self.make_member("mail_mover")
        current = self.login("mail_mover", "Current")
        other = self.login("mail_mover", "Other")
        version = self.token_version(member)

        response = bearer(current["token"]).patch(
            MEMBER_ME_URL, {"mb_email": "moved@example.test", "mb_password_current": PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        fresh = response.json()["data"]
        self.assertGreater(self.token_version(member), version)
        self.assert_signed_out(other)
        self.assertEqual(bearer(current["token"]).get(ME_URL).status_code, 401)
        self.assertEqual(AccessToken(fresh["token"])["tv"], self.token_version(member))
        self.assert_signed_in(fresh)

    def test_a_profile_edit_without_a_new_address_or_password_keeps_every_device(self):
        self.make_member("plain_editor")
        current = self.login("plain_editor", "Current")
        other = self.login("plain_editor", "Other")
        response = bearer(current["token"]).patch(MEMBER_ME_URL, {"mb_name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assert_signed_in(current)
        self.assert_signed_in(other)

    def test_an_e_mail_change_that_needs_certification_bumps_the_token_version(self):
        Config.objects.update_or_create(name="cf_use_email_certify", defaults={"value": "1"})
        member = self.make_member("mail_certify")
        device = self.login("mail_certify")
        version = self.token_version(member)
        with mock.patch("gnu_jango.api.v1_community.issue_email_certify"):
            response = bearer(device["token"]).patch(
                MEMBER_ME_URL, {"mb_email": "new-certify@example.test", "mb_password_current": PASSWORD}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertGreater(self.token_version(member), version)
        self.assert_signed_out(device)

    def test_a_password_reset_bumps_the_token_version(self):
        member = self.make_member("reset_tv")
        device = self.login("reset_tv")
        version = self.token_version(member)
        response = APIClient().post(
            "/api/v1/auth/password-reset",
            {
                "step": "reset",
                "uid": urlsafe_base64_encode(force_bytes(member.pk)),
                "token": default_token_generator.make_token(member),
                "mb_password": "Reset-pass-88",
                "mb_password_re": "Reset-pass-88",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertGreater(self.token_version(member), version)
        self.assert_signed_out(device)

    def test_leaving_bumps_the_token_version(self):
        member = self.make_member("leaver_tv")
        device = self.login("leaver_tv")
        version = self.token_version(member)
        response = bearer(device["token"]).post("/api/v1/members/me/leave", {"mb_password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertGreater(self.token_version(member), version)
        self.assert_signed_out(device)

    def test_a_stale_profile_save_cannot_bring_back_a_revoked_token_version(self):
        member = self.make_member("stale_profile")
        stale = Profile.objects.get(user=member)
        v1_auth.bump_token_version(member)
        bumped = self.token_version(member)

        stale.nickname = "edited-elsewhere"
        stale.save()
        User.objects.get(pk=member.pk).save()  # the post_save hook saves the cached profile as well

        self.assertEqual(self.token_version(member), bumped)
        self.assertEqual(Profile.objects.get(user=member).nickname, "edited-elsewhere")


class AdminBlockRevocationTests(HardeningBase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(username="site_admin", email="admin@example.test", password=PASSWORD)

    def test_the_block_action_revokes_the_tokens_for_good_even_after_the_block_is_lifted(self):
        member = self.make_member("action_blocked")
        device = self.login("action_blocked")
        admin_client = Client()
        admin_client.force_login(self.admin_user)

        response = admin_client.post(
            reverse("admin:auth_user_changelist"),
            {"action": "block_selected_members", "_selected_action": [member.pk]},
        )

        self.assertEqual(response.status_code, 302, response.content[:300])
        self.assert_signed_out(device)
        User.objects.filter(pk=member.pk).update(is_active=True)
        self.assert_signed_out(device)

    def django_admin_save(self, member, changed):
        model_admin = admin.site._registry[User]
        request = RequestFactory().post("/admin/")
        request.user = self.admin_user
        form = mock.Mock(changed_data=changed, instance=member)
        model_admin.save_model(request, member, form, True)
        model_admin.save_related(request, form, [], True)

    def test_a_django_admin_block_revokes_the_tokens_for_good(self):
        member = self.make_member("admin_blocked")
        device = self.login("admin_blocked")
        member.is_active = False
        self.django_admin_save(member, ["is_active"])
        User.objects.filter(pk=member.pk).update(is_active=True)
        self.assert_signed_out(device)

    def test_a_django_admin_e_mail_change_revokes_the_tokens(self):
        member = self.make_member("admin_mail")
        device = self.login("admin_mail")
        member.email = "admin-moved@example.test"
        self.django_admin_save(member, ["email"])
        self.assert_signed_out(device)

    def test_a_django_admin_edit_of_other_fields_keeps_the_tokens(self):
        member = self.make_member("admin_other")
        device = self.login("admin_other")
        member.first_name = "Changed"
        self.django_admin_save(member, ["first_name"])
        self.assert_signed_in(device)

    def test_a_django_admin_password_change_revokes_the_tokens(self):
        member = self.make_member("admin_pw")
        device = self.login("admin_pw")
        browser = self.client
        browser.force_login(self.admin_user)
        url = reverse(f"admin:{User._meta.app_label}_{User._meta.model_name}_password_change", args=[member.pk])
        response = browser.post(url, {"password1": "Admin-set-pass-1", "password2": "Admin-set-pass-1", "usable_password": "true"})
        self.assertIn(response.status_code, (200, 302))
        member.refresh_from_db()
        self.assertTrue(member.check_password("Admin-set-pass-1"), "the admin password form did not save")
        self.assert_signed_out(device)


class LoginSessionTests(HardeningBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("sessions_owner")
        self.other_member = self.make_member("sessions_other")

    def sessions(self, device):
        response = bearer(device["token"]).get(SESSIONS_URL)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()["data"]["sessions"]

    def test_the_list_marks_the_current_session_and_records_the_agent_and_address(self):
        current = self.login("sessions_owner", "Current Agent")
        self.login("sessions_owner", "Other Agent")

        sessions = self.sessions(current)

        self.assertEqual(len(sessions), 2)
        by_agent = {session["user_agent"]: session for session in sessions}
        self.assertTrue(by_agent["Current Agent"]["current"])
        self.assertFalse(by_agent["Other Agent"]["current"])
        self.assertEqual(by_agent["Current Agent"]["ip"], "127.0.0.1")
        for session in sessions:
            self.assertEqual(session["id"], session["token_id"])
            for field in ("created_at", "last_used_at", "expires_at"):
                self.assertTrue(session[field], field)

    def test_a_refresh_keeps_the_login_time_of_the_session(self):
        device = self.login("sessions_owner", "Rotating Agent")
        before = self.sessions(device)[0]

        refreshed = APIClient().post(
            REFRESH_URL, {"refresh_token": device["refresh_token"]}, format="json", HTTP_USER_AGENT="Rotating Agent"
        ).json()["data"]
        after = self.sessions(refreshed)

        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["created_at"], before["created_at"])
        self.assertTrue(after[0]["current"])
        self.assertNotEqual(after[0]["id"], before["id"])

    def test_delete_revokes_another_session_and_its_access_token(self):
        current = self.login("sessions_owner", "Current Agent")
        other = self.login("sessions_owner", "Other Agent")
        target = next(session for session in self.sessions(current) if not session["current"])

        response = bearer(current["token"]).delete(f"{SESSIONS_URL}/{target['id']}")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"], {"revoked": True, "current": False})
        self.assert_signed_out(other)
        self.assert_signed_in(current)
        self.assertEqual(len(self.sessions(current)), 1)

    def test_delete_of_the_current_session_signs_this_client_out(self):
        current = self.login("sessions_owner", "Current Agent")
        target = self.sessions(current)[0]

        response = bearer(current["token"]).delete(f"{SESSIONS_URL}/{target['id']}")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(response.json()["data"]["current"])
        self.assertEqual(int(response.cookies["g5_token"]["max-age"]), 0)
        self.assert_signed_out(current)

    def test_delete_refuses_another_members_session_and_unknown_ids(self):
        current = self.login("sessions_owner")
        other_device = self.login("sessions_other")
        foreign_id = OutstandingToken.objects.filter(user=self.other_member).values_list("pk", flat=True).first()

        foreign = bearer(current["token"]).delete(f"{SESSIONS_URL}/{foreign_id}")
        unknown = bearer(current["token"]).delete(f"{SESSIONS_URL}/999999")

        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json()["code"], "session_not_found")
        self.assertEqual(unknown.status_code, 404)
        self.assert_signed_in(other_device)

    def test_delete_needs_a_signed_in_member(self):
        self.login("sessions_owner")
        token_id = OutstandingToken.objects.filter(user=self.member).values_list("pk", flat=True).first()
        response = APIClient().delete(f"{SESSIONS_URL}/{token_id}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")

    def test_sessions_revoked_by_a_password_change_disappear_from_the_list(self):
        current = self.login("sessions_owner", "Current Agent")
        self.login("sessions_owner", "Other Agent")
        response = bearer(current["token"]).patch(
            MEMBER_ME_URL,
            {"mb_password_current": PASSWORD, "mb_password": "Changed-pass-77", "mb_password_re": "Changed-pass-77"},
            format="json",
        )
        fresh = response.json()["data"]
        sessions = self.sessions(fresh)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["current"])


@override_settings(**SOCIAL_SETTINGS)
class SocialTicketBindingTests(HardeningBase):
    def provider_http(self):
        spec = v1_auth.SOCIAL_PROVIDER_SPECS["kakao"]

        def fake(url, **kwargs):
            return {"access_token": "at-1"} if url == spec["token_url"] else KAKAO_USERINFO

        return mock.patch(HTTP_PATCH, side_effect=fake)

    def run_flow(self, client, *, mode="login", **params):
        start = client.get(SIGNUP_START_URL if mode == "signup" else START_URL, {"provider": "kakao", **params})
        self.assertEqual(start.status_code, 302, start.content[:200])
        state = query_of(start["Location"]).get("state", "")
        with self.provider_http():
            return client.get(CALLBACK_URL, {"state": state, "code": "auth-code"})

    def linked_member(self):
        member = self.make_member("social_owner")
        v1_auth._link_social_identity(
            member, {"provider": "kakao", "provider_label": "Kakao", "provider_user_id": "4242"}
        )
        return member

    def test_a_login_ticket_is_redeemed_in_the_browser_that_started_the_flow(self):
        self.linked_member()
        browser = APIClient()
        ticket = query_of(self.run_flow(browser, redirect="/after")["Location"])["ticket"]
        response = browser.post(EXCHANGE_URL, {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "social_owner")

    def test_a_leaked_login_ticket_is_refused_in_another_browser_and_stays_usable_for_its_owner(self):
        self.linked_member()
        victim = APIClient()
        ticket = query_of(self.run_flow(victim, redirect="/after")["Location"])["ticket"]

        stolen = APIClient().post(EXCHANGE_URL, {"ticket": ticket}, format="json")

        self.assertEqual(stolen.status_code, 404)
        self.assertEqual(stolen.json()["code"], "social_ticket_not_found")
        self.assertEqual(victim.post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 200)

    def test_a_signup_ticket_is_refused_in_another_browser(self):
        browser = APIClient()
        ticket = query_of(self.run_flow(browser, mode="signup")["Location"])["social_signup_ticket"]
        intruder = APIClient()

        self.assertEqual(intruder.get(SIGNUP_PROFILE_URL, {"ticket": ticket}).status_code, 404)
        self.assertEqual(
            intruder.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_id": "intruder_id"}, format="json").status_code,
            404,
        )
        self.make_member("link_target")
        linked = intruder.post(LINK_URL, {"ticket": ticket, "mb_id": "link_target", "password": PASSWORD}, format="json")
        self.assertEqual(linked.status_code, 404)
        self.assertEqual(linked.json()["code"], "social_signup_not_found")

        self.assertEqual(browser.get(SIGNUP_PROFILE_URL, {"ticket": ticket}).status_code, 200)
        linked = browser.post(LINK_URL, {"ticket": ticket, "mb_id": "link_target", "password": PASSWORD}, format="json")
        self.assertEqual(linked.status_code, 200, linked.content[:300])

    def test_a_ticket_without_any_binding_is_never_redeemed(self):
        member = self.make_member("unbound_owner")
        ticket, _ = v1_auth._create_social_ticket(
            {"provider": "kakao", "provider_label": "Kakao", "provider_user_id": "unbound"}, kind="login", user=member
        )
        self.assertEqual(APIClient().post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 404)

    @override_settings(SOCIAL_ALLOWED_REDIRECT_SCHEMES=["dday-app"])
    def test_a_native_app_redeems_its_ticket_with_the_verifier_of_its_challenge(self):
        self.linked_member()
        verifier = "v" * 20 + "-app-verifier-0123456789_abcdefghij"
        system_browser = APIClient()
        callback = self.run_flow(
            system_browser,
            redirect="dday-app://social-callback?state=app-state-1",
            client_challenge=s256(verifier),
            client_challenge_method="S256",
        )
        location = callback["Location"]
        self.assertTrue(location.startswith("dday-app://social-callback?"), location)
        params = query_of(location)
        self.assertEqual(params["state"], "app-state-1")

        # The app's own HTTP client shares no cookies with the system browser.
        wrong = APIClient().post(EXCHANGE_URL, {"ticket": params["ticket"], "client_verifier": "w" * 43}, format="json")
        missing = APIClient().post(EXCHANGE_URL, {"ticket": params["ticket"]}, format="json")
        right = APIClient().post(EXCHANGE_URL, {"ticket": params["ticket"], "client_verifier": verifier}, format="json")

        self.assertEqual(wrong.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(right.status_code, 200, right.content[:300])
        self.assertEqual(right.json()["data"]["member"]["mb_id"], "social_owner")

    @override_settings(SOCIAL_ALLOWED_REDIRECT_SCHEMES=["dday-app"])
    def test_an_app_redirect_without_a_challenge_or_with_a_malformed_one_is_not_followed(self):
        self.linked_member()
        for extra in ({}, {"client_challenge": "short"}, {"client_challenge": s256("x" * 43), "client_challenge_method": "plain"}):
            callback = self.run_flow(APIClient(), redirect="dday-app://social-callback", **extra)
            self.assertTrue(callback["Location"].startswith("http://testserver/"), (extra, callback["Location"]))

    def test_an_app_scheme_that_is_not_configured_is_not_followed(self):
        self.linked_member()
        callback = self.run_flow(APIClient(), redirect="dday-app://social-callback", client_challenge=s256("y" * 43))
        self.assertTrue(callback["Location"].startswith("http://testserver/"), callback["Location"])

    def test_a_web_flow_with_a_challenge_still_works_in_its_own_browser_only(self):
        self.linked_member()
        verifier = "z" * 43
        browser = APIClient()
        ticket = query_of(self.run_flow(browser, redirect="/after", client_challenge=s256(verifier))["Location"])["ticket"]
        self.assertEqual(APIClient().post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 404)
        self.assertEqual(browser.post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 200)
