"""Member-facing v1 API: auth, captcha, social/cert settings, the member's own profile and lists.

These tests check what the endpoints return and what they change in the database (a profile update
really renames the member, logout really clears the cookies and burns the refresh token, another
member's private data is never exposed). External providers are never called: social login and
identity verification are unconfigured in tests, so only their disabled behaviour is exercised.
"""

import re
import io
import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api import v1_auth
from gnu_jango.config import config as site_config
from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.config.models import Config
from gnu_jango.core.models import VisitLog
from gnu_jango.users.models import Profile, User_Point

PASSWORD = "Str0ng-pass-99"
CAPTCHA_PATCH = "gnu_jango.api.v1_auth._captcha_matches"
AUTH_COOKIES = ("g5_token", "g5_refresh", "g5_auth_hint", "g5_auto_login")


class MemberApiTestBase(TestCase):
    def setUp(self):
        # Login and register are rate limited per client address through the shared cache.
        cache.clear()
        self.addCleanup(cache.clear)
        self.user_model = get_user_model()

    def make_member(self, username, *, nickname=None, level=2, point=0, active=True, **extra):
        user = self.user_model.objects.create_user(
            username=username, email=f"{username}@example.test", password=PASSWORD, is_active=active, **extra
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.nickname = nickname or f"nick-{username}"
        profile.user_level = level
        profile.user_point = point
        profile.save()
        # Hand back a fresh instance: the one create_user returned caches the signal-made profile.
        return self.user_model.objects.get(pk=user.pk)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def bearer_client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def post_json(self, client, url, payload):
        return client.post(url, payload, format="json")

    def register_payload(self, **overrides):
        payload = {
            "mb_id": "reg_member",
            "mb_password": PASSWORD,
            "mb_password_re": PASSWORD,
            "mb_email": "reg-member@example.test",
            "mb_name": "Reg Member",
            "mb_nick": "reg-nick",
            "captcha_key": "123456",
        }
        payload.update(overrides)
        return payload

    def register(self, client=None, **overrides):
        with mock.patch(CAPTCHA_PATCH, return_value=True):
            return (client or APIClient()).post(
                "/api/v1/auth/register", self.register_payload(**overrides), format="json"
            )

    def assert_auth_cookies_cleared(self, response):
        for name in AUTH_COOKIES:
            self.assertIn(name, response.cookies, name)
            cookie = response.cookies[name]
            self.assertEqual(cookie.value, "", name)
            self.assertEqual(int(cookie["max-age"]), 0, name)


class CaptchaTests(MemberApiTestBase):
    def test_the_captcha_is_a_png_and_remembers_its_code_in_the_session(self):
        client = APIClient()
        response = client.get("/api/v1/captcha")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertIn("no-store", response["Cache-Control"])
        code = client.session[v1_auth.CAPTCHA_SESSION_KEY]
        self.assertRegex(code, r"^[2-9]{6}$")

    def test_every_request_issues_a_new_code_and_resets_the_failure_count(self):
        client = APIClient()
        client.get("/api/v1/captcha")
        session = client.session
        session[v1_auth.CAPTCHA_ATTEMPT_SESSION_KEY] = 4
        session.save()
        client.get("/api/v1/captcha")
        self.assertEqual(client.session[v1_auth.CAPTCHA_ATTEMPT_SESSION_KEY], 0)

    def test_the_audio_reads_the_same_code_as_the_image(self):
        client = APIClient()
        client.get("/api/v1/captcha")
        code = client.session[v1_auth.CAPTCHA_SESSION_KEY]
        response = client.get("/api/v1/captcha/audio")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response["Content-Type"], ("audio/wav", "audio/mpeg"))
        self.assertTrue(response.content)
        self.assertEqual(client.session[v1_auth.CAPTCHA_SESSION_KEY], code)
        self.assertIn("no-store", response["Cache-Control"])

    def test_the_audio_without_an_image_first_creates_a_code(self):
        client = APIClient()
        response = client.get("/api/v1/captcha/audio")
        self.assertEqual(response.status_code, 200)
        self.assertRegex(client.session[v1_auth.CAPTCHA_SESSION_KEY], r"^[2-9]{6}$")

    def test_the_generated_wav_has_one_tone_per_digit(self):
        with mock.patch("gnu_jango.api.auth_captcha._captcha_mp3_audio", return_value=b""):
            content, content_type = v1_auth._captcha_audio("234567")
        self.assertEqual(content_type, "audio/wav")
        self.assertTrue(content.startswith(b"RIFF"))
        longer, _ = v1_auth._captcha_audio("23456723")
        self.assertGreater(len(longer), len(content))

    @mock.patch("rest_framework.throttling.ScopedRateThrottle.allow_request", return_value=True)
    def test_the_matcher_only_accepts_the_stored_code_and_gives_up_after_six_misses(self, _throttle):
        # Seven sign-ups exceed the register rate limit, which is tested on its own.
        client = APIClient()
        client.get("/api/v1/captcha")
        code = client.session[v1_auth.CAPTCHA_SESSION_KEY]
        wrong = "222222" if code != "222222" else "333333"
        for _ in range(v1_auth.CAPTCHA_MAX_FAILURES):
            response = client.post("/api/v1/auth/register", self.register_payload(captcha_key=wrong), format="json")
            self.assertEqual(response.status_code, 422)
            self.assertIn("captcha_key", response.json()["errors"])
        # The right code no longer helps once the failures are used up.
        response = client.post("/api/v1/auth/register", self.register_payload(captcha_key=code), format="json")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())


class AvailabilityCheckTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.make_member("taken_id")

    def check_id(self, mb_id):
        response = APIClient().get("/api/v1/auth/check-id", {"mb_id": mb_id})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def check_email(self, mb_email):
        response = APIClient().get("/api/v1/auth/check-email", {"mb_email": mb_email})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_a_free_id_is_available(self):
        self.assertTrue(self.check_id("free_id")["available"])

    def test_a_taken_id_is_not_available_whatever_its_case(self):
        self.assertFalse(self.check_id("taken_id")["available"])
        self.assertFalse(self.check_id("TAKEN_ID")["available"])

    def test_an_empty_or_malformed_id_is_not_available(self):
        for bad in ("", "  ", "ab", "has space", "a" * 21, "bad-dash", "<script>"):
            self.assertFalse(self.check_id(bad)["available"], repr(bad))

    def test_the_id_check_without_a_parameter_is_not_available(self):
        response = APIClient().get("/api/v1/auth/check-id")
        self.assertFalse(response.json()["data"]["available"])

    def test_a_free_email_is_available_and_a_used_one_is_not(self):
        self.assertTrue(self.check_email("free@example.test")["available"])
        self.assertFalse(self.check_email("taken_id@example.test")["available"])
        self.assertFalse(self.check_email("TAKEN_ID@Example.Test")["available"])

    def test_an_email_without_an_at_sign_is_not_available(self):
        self.assertFalse(self.check_email("")["available"])
        self.assertFalse(self.check_email("not-an-email")["available"])
        self.assertFalse(APIClient().get("/api/v1/auth/check-email").json()["data"]["available"])


class LoginTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("login_member", nickname="Login Nick", point=7)

    def login(self, payload, client=None):
        return (client or APIClient()).post("/api/v1/auth/login", payload, format="json")

    def test_a_correct_login_returns_tokens_and_the_member(self):
        response = self.login({"mb_id": "login_member", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["token"])
        self.assertTrue(data["refresh_token"])
        self.assertEqual(data["auto_login"], 0)
        self.assertEqual(data["member"]["mb_id"], "login_member")
        self.assertEqual(data["member"]["mb_nick"], "Login Nick")
        self.assertEqual(data["member"]["mb_email"], "login_member@example.test")
        self.assertFalse(data["is_super_admin"])

    def test_the_issued_access_token_authenticates_later_requests(self):
        data = self.login({"mb_id": "login_member", "password": PASSWORD}).json()["data"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['token']}")
        me = client.get("/api/v1/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["data"]["member"]["mb_id"], "login_member")

    def test_login_sets_http_only_session_cookies(self):
        response = self.login({"mb_id": "login_member", "password": PASSWORD})
        self.assertEqual(response.cookies["g5_token"].value, response.json()["data"]["token"])
        self.assertTrue(response.cookies["g5_token"]["httponly"])
        self.assertEqual(response.cookies["g5_refresh"].value, response.json()["data"]["refresh_token"])
        self.assertTrue(response.cookies["g5_refresh"]["httponly"])
        self.assertEqual(response.cookies["g5_auth_hint"].value, "1")
        self.assertFalse(response.cookies["g5_auth_hint"]["httponly"])

    def test_without_auto_login_the_cookies_are_session_cookies(self):
        response = self.login({"mb_id": "login_member", "password": PASSWORD})
        self.assertEqual(response.cookies["g5_refresh"]["max-age"], "")
        self.assertEqual(response.cookies["g5_auto_login"].value, "")  # a deletion, not a grant

    def test_auto_login_keeps_the_cookies_for_thirty_days(self):
        response = self.login({"mb_id": "login_member", "password": PASSWORD, "auto_login": 1})
        self.assertEqual(response.json()["data"]["auto_login"], 1)
        self.assertEqual(response.cookies["g5_auto_login"].value, "1")
        self.assertEqual(int(response.cookies["g5_refresh"]["max-age"]), 30 * 24 * 60 * 60)
        self.assertEqual(int(response.cookies["g5_auth_hint"]["max-age"]), 30 * 24 * 60 * 60)

    def test_the_legacy_field_names_work(self):
        response = self.login({"mb_id": "login_member", "mb_password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        response = self.login({"username": "login_member", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def test_a_wrong_password_is_refused_without_tokens_or_points(self):
        response = self.login({"mb_id": "login_member", "password": "wrong-password-1"})
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertIn("invalid_login", body["errors"])
        self.assertEqual(body["data"], {})
        self.assertNotIn("g5_token", response.cookies)
        self.assertFalse(User_Point.objects.filter(user=self.member, po_rel_table="@login").exists())

    def test_an_unknown_member_gets_the_same_answer_as_a_wrong_password(self):
        wrong = self.login({"mb_id": "login_member", "password": "wrong-password-1"})
        unknown = self.login({"mb_id": "nobody_here", "password": "wrong-password-1"})
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json()["message"], wrong.json()["message"])

    def test_missing_credentials_are_a_validation_error_naming_the_fields(self):
        response = self.login({})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(set(response.json()["errors"]), {"mb_id", "mb_password"})
        response = self.login({"mb_id": "login_member"})
        self.assertEqual(response.status_code, 422)

    def test_an_inactive_member_cannot_log_in(self):
        self.make_member("sleeping_member", active=False)
        response = self.login({"mb_id": "sleeping_member", "password": PASSWORD})
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(response.json()["success"])
        self.assertNotIn("g5_token", response.cookies)
        self.assertNotIn("token", response.json()["data"])


class RegisterTests(MemberApiTestBase):
    def test_registering_creates_the_member_with_profile_and_signs_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["token"])
        self.assertEqual(data["member"]["mb_id"], "reg_member")
        user = self.user_model.objects.get(username="reg_member")
        self.assertEqual(user.email, "reg-member@example.test")
        self.assertEqual(user.first_name, "Reg Member")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.nickname, "reg-nick")
        self.assertEqual(profile.realname, "Reg Member")
        self.assertEqual(profile.user_level, 2)
        self.assertEqual(response.cookies["g5_token"].value, data["token"])

    def test_a_new_member_can_log_in_afterwards(self):
        self.register()
        response = APIClient().post(
            "/api/v1/auth/login", {"mb_id": "reg_member", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_the_nickname_and_name_default_to_the_id(self):
        payload = self.register_payload()
        for key in ("mb_nick", "mb_name"):
            payload.pop(key)
        with mock.patch(CAPTCHA_PATCH, return_value=True):
            response = APIClient().post("/api/v1/auth/register", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Profile.objects.get(user__username="reg_member").nickname, "reg_member")

    def test_a_wrong_captcha_blocks_registration(self):
        response = APIClient().post("/api/v1/auth/register", self.register_payload(), format="json")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["message"], "Invalid captcha.")
        self.assertEqual(set(response.json()["errors"]), {"captcha_key"})
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_the_real_captcha_flow_registers_once_and_burns_the_code(self):
        client = APIClient()
        client.get("/api/v1/captcha")
        code = client.session[v1_auth.CAPTCHA_SESSION_KEY]
        response = client.post("/api/v1/auth/register", self.register_payload(captcha_key=code), format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertNotIn(v1_auth.CAPTCHA_SESSION_KEY, client.session)
        again = client.post(
            "/api/v1/auth/register",
            self.register_payload(captcha_key=code, mb_id="second_member", mb_email="second@example.test", mb_nick="second"),
            format="json",
        )
        self.assertEqual(again.status_code, 422)
        self.assertFalse(self.user_model.objects.filter(username="second_member").exists())

    def test_a_taken_id_email_or_nickname_is_reported_and_nothing_is_created(self):
        self.make_member("dup_member", nickname="dup-nick")
        before = self.user_model.objects.count()
        cases = (
            ({"mb_id": "DUP_MEMBER"}, "mb_id"),
            ({"mb_email": "dup_member@example.test"}, "mb_email"),
            ({"mb_nick": "DUP-nick"}, "mb_nick"),
        )
        for override, field in cases:
            response = self.register(**override)
            self.assertEqual(response.status_code, 422, override)
            self.assertIn(field, response.json()["errors"], override)
        self.assertEqual(self.user_model.objects.count(), before)

    def test_every_invalid_field_is_reported_together(self):
        response = self.register(mb_id="x", mb_password="abc", mb_password_re="abd", mb_email="nope", mb_name=" ", mb_nick=" ")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["message"], "Validation failed.")
        errors = response.json()["errors"]
        self.assertTrue({"mb_id", "mb_password_re", "mb_email"} <= set(errors), errors)

    def test_mismatching_password_confirmation_is_refused(self):
        response = self.register(mb_password_re=PASSWORD + "x")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_password_re", response.json()["errors"])
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_a_weak_password_is_refused_by_the_password_validators(self):
        for weak in ("short1", "12345678", "password"):
            response = self.register(mb_password=weak, mb_password_re=weak)
            self.assertEqual(response.status_code, 422, weak)
            self.assertIn("mb_password", response.json()["errors"], weak)
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_a_missing_password_is_refused(self):
        response = self.register(mb_password="", mb_password_re="")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_password", response.json()["errors"])

    def test_ids_with_unsupported_characters_are_refused(self):
        for bad in ("a b", "ab", "a" * 21, "한글아이디", "x;drop"):
            response = self.register(mb_id=bad)
            self.assertEqual(response.status_code, 422, bad)
            self.assertIn("mb_id", response.json()["errors"], bad)

    def test_the_registration_result_shows_the_member_who_just_registered(self):
        client = APIClient()
        self.register(client)
        response = client.get("/api/v1/auth/register-result")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["mb_id"], "reg_member")
        self.assertEqual(data["mb_nick"], "reg-nick")
        self.assertEqual(data["mb_email"], "reg-member@example.test")
        self.assertFalse(data["requires_email_verification"])
        self.assertNotIn("password", json.dumps(data).lower())

    def test_the_registration_result_is_not_found_for_a_stranger(self):
        self.register()
        self.assertEqual(APIClient().get("/api/v1/auth/register-result").status_code, 404)

    def test_the_registration_result_falls_back_to_the_signed_in_member(self):
        member = self.make_member("result_member")
        response = self.bearer_client(member).get("/api/v1/auth/register-result")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["mb_id"], "result_member")


class SessionLifecycleTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("life_member", point=3)

    def login_data(self):
        response = APIClient().post(
            "/api/v1/auth/login", {"mb_id": "life_member", "password": PASSWORD}, format="json"
        )
        return response.json()["data"]

    def test_me_returns_the_signed_in_member_from_a_bearer_token(self):
        response = self.bearer_client(self.member).get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["member"]["mb_id"], "life_member")
        # 3 points plus the daily login points (default 100) granted on the first visit of the day.
        self.assertEqual(data["member"]["mb_point"], 103)
        self.assertFalse(data["is_super_admin"])
        self.assertNotIn("password", json.dumps(data).lower())

    def test_me_accepts_the_auth_cookie(self):
        client = APIClient()
        client.cookies["g5_token"] = str(RefreshToken.for_user(self.member).access_token)
        response = client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "life_member")

    def test_me_reports_super_admins(self):
        admin = self.user_model.objects.create_superuser("life_admin", "life-admin@example.test", PASSWORD)
        response = self.bearer_client(admin).get("/api/v1/auth/me")
        self.assertTrue(response.json()["data"]["is_super_admin"])
        self.assertTrue(response.json()["data"]["member"]["is_superuser"])

    def test_me_without_credentials_is_unauthorized(self):
        response = APIClient().get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["success"])

    def test_me_rejects_a_garbage_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not.a.token")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_me_rejects_a_refresh_token_used_as_an_access_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.member)}")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_refresh_with_a_body_token_returns_a_new_working_pair(self):
        data = self.login_data()
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": data["refresh_token"]}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        fresh = response.json()["data"]
        self.assertEqual(fresh["member"]["mb_id"], "life_member")
        self.assertNotEqual(fresh["refresh_token"], data["refresh_token"])
        self.assertEqual(response.cookies["g5_token"].value, fresh["token"])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh['token']}")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_refresh_reads_the_refresh_cookie(self):
        client = APIClient()
        client.cookies["g5_refresh"] = self.login_data()["refresh_token"]
        response = client.post("/api/v1/auth/refresh", {}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_a_rotated_refresh_token_cannot_be_used_twice(self):
        old = self.login_data()["refresh_token"]
        first = APIClient().post("/api/v1/auth/refresh", {"refresh_token": old}, format="json")
        self.assertEqual(first.status_code, 200)
        replay = APIClient().post("/api/v1/auth/refresh", {"refresh_token": old}, format="json")
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json()["message"], "Invalid or expired refresh token.")

    def test_the_access_token_of_a_deactivated_member_stops_working(self):
        token = self.login_data()["token"]
        self.user_model.objects.filter(pk=self.member.pk).update(is_active=False)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(client.get("/api/v1/members/me").status_code, 401)

    def test_refresh_without_a_token_is_unauthorized(self):
        response = APIClient().post("/api/v1/auth/refresh", {}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("refresh_required", response.json()["errors"])

    def test_refresh_with_a_bad_token_is_refused_and_clears_the_cookies(self):
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": "garbage"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid_refresh", response.json()["errors"])
        self.assert_auth_cookies_cleared(response)

    def test_an_access_token_is_not_accepted_for_refresh(self):
        access = self.login_data()["token"]
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": access}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_an_expired_refresh_token_is_refused(self):
        token = RefreshToken.for_user(self.member)
        token.set_exp(lifetime=-timedelta(seconds=5))
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": str(token)}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_the_refresh_token_of_a_deleted_member_is_refused(self):
        token = str(RefreshToken.for_user(self.member))
        self.member.delete()
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": token}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_the_cookies_and_burns_the_refresh_token(self):
        data = self.login_data()
        client = APIClient()
        client.cookies["g5_refresh"] = data["refresh_token"]
        client.cookies["g5_token"] = data["token"]
        response = client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["logged_out"])
        self.assert_auth_cookies_cleared(response)
        reuse = APIClient().post("/api/v1/auth/refresh", {"refresh_token": data["refresh_token"]}, format="json")
        self.assertEqual(reuse.status_code, 401)

    def test_logout_takes_the_refresh_token_from_the_body_too(self):
        data = self.login_data()
        APIClient().post("/api/v1/auth/logout", {"refresh": data["refresh_token"]}, format="json")
        reuse = APIClient().post("/api/v1/auth/refresh", {"refresh_token": data["refresh_token"]}, format="json")
        self.assertEqual(reuse.status_code, 401)

    def test_logout_without_or_with_a_bad_token_still_succeeds_and_clears_cookies(self):
        for payload in ({}, {"refresh_token": "garbage"}):
            response = APIClient().post("/api/v1/auth/logout", payload, format="json")
            self.assertEqual(response.status_code, 200, payload)
            self.assert_auth_cookies_cleared(response)

    def test_sessions_require_a_signed_in_member(self):
        self.assertEqual(APIClient().get("/api/v1/auth/sessions").status_code, 401)
        self.assertEqual(APIClient().post("/api/v1/auth/sessions/revoke", {}, format="json").status_code, 401)

    def test_sessions_list_the_current_browser(self):
        login = APIClient().post(
            "/api/v1/auth/login",
            {"mb_id": "life_member", "password": PASSWORD},
            format="json",
            HTTP_USER_AGENT="UnitTest/1.0",
        )
        self.assertEqual(login.status_code, 200, login.content[:200])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['data']['token']}")
        response = client.get("/api/v1/auth/sessions")
        self.assertEqual(response.status_code, 200)
        sessions = response.json()["data"]["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["user_agent"], "UnitTest/1.0")
        self.assertTrue(sessions[0]["device_label"])

    def test_revoking_a_missing_session_returns_not_found(self):
        response = self.bearer_client(self.member).post(
            "/api/v1/auth/sessions/revoke", {"token_id": 9_223_372_036_854_775_807}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "session_not_found")


class SocialLoginTests(MemberApiTestBase):
    def make_ticket(self, kind, user=None, **profile):
        base = {
            "provider": "kakao",
            "provider_label": "Kakao",
            "provider_user_id": "kakao-123",
            "email": "social-person@example.test",
            "name": "Social Person",
            "nickname": "SocialNick",
        }
        base.update(profile)
        session = self.social_client.session
        ticket, _ = v1_auth._create_social_ticket(base, kind=kind, user=user, session=session)
        session.save()
        return ticket

    @property
    def social_client(self):
        """The browser the tickets belong to: a ticket only works where the social login started."""
        if not hasattr(self, "_social_client"):
            self._social_client = APIClient()
        return self._social_client

    def test_every_provider_is_disabled_when_nothing_is_configured(self):
        response = self.social_client.get("/api/v1/auth/social/providers")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["enabled"])
        self.assertEqual(
            {provider["name"] for provider in data["providers"]},
            {"naver", "kakao", "google", "facebook", "twitter", "payco"},
        )
        for provider in data["providers"]:
            self.assertFalse(provider["enabled"], provider["name"])
            self.assertFalse(provider["has_api_key"], provider["name"])

    @override_settings(SOCIAL_KAKAO_REST_KEY="kakao-test-key")
    def test_a_provider_with_an_api_key_is_reported_enabled_and_secrets_are_not_leaked(self):
        response = self.social_client.get("/api/v1/auth/social/providers")
        data = response.json()["data"]
        self.assertTrue(data["enabled"])
        kakao = next(provider for provider in data["providers"] if provider["name"] == "kakao")
        self.assertTrue(kakao["enabled"])
        self.assertNotIn("kakao-test-key", response.content.decode())
        naver = next(provider for provider in data["providers"] if provider["name"] == "naver")
        self.assertFalse(naver["enabled"])

    @override_settings(SOCIAL_NAVER_CLIENT_ID="naver-id")
    def test_a_provider_that_needs_a_secret_stays_disabled_without_it(self):
        data = self.social_client.get("/api/v1/auth/social/providers").json()["data"]
        naver = next(provider for provider in data["providers"] if provider["name"] == "naver")
        self.assertFalse(naver["has_api_key"])
        self.assertFalse(naver["enabled"])

    def test_the_site_setting_alone_enables_a_provider_only_with_the_global_switch(self):
        Config.objects.update_or_create(name="cf_kakao_rest_key", defaults={"value": "db-key"})
        data = self.social_client.get("/api/v1/auth/social/providers").json()["data"]
        self.assertFalse(data["enabled"])
        Config.objects.update_or_create(name="cf_social_login_use", defaults={"value": "1"})
        data = self.social_client.get("/api/v1/auth/social/providers").json()["data"]
        self.assertTrue(data["enabled"])
        Config.objects.update_or_create(name="cf_social_servicelist", defaults={"value": "naver,google"})
        data = self.social_client.get("/api/v1/auth/social/providers").json()["data"]
        self.assertFalse(data["enabled"])

    def test_the_start_endpoint_redirects_back_with_an_error_when_disabled(self):
        response = self.social_client.get("/api/social/start.php", {"provider": "kakao", "redirect": "https://evil.example/x"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("error=social_disabled", response["Location"])
        self.assertNotIn("evil.example", response["Location"])

    def test_an_unknown_ticket_cannot_be_exchanged(self):
        for payload in ({}, {"ticket": "nope"}, {"ticket": "../../etc"}, {"ticket": "x" * 200}):
            response = self.social_client.post("/api/v1/auth/social/exchange", payload, format="json")
            self.assertEqual(response.status_code, 404, payload)
            self.assertNotIn("g5_token", response.cookies)

    def test_a_login_ticket_signs_the_linked_member_in_once(self):
        member = self.make_member("social_member")
        ticket = self.make_ticket("login", user=member)
        response = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "social_member")
        self.assertEqual(response.cookies["g5_token"].value, response.json()["data"]["token"])
        replay = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(replay.status_code, 404)

    def test_a_signup_ticket_cannot_be_exchanged_for_a_login(self):
        ticket = self.make_ticket("signup")
        response = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_an_expired_ticket_is_refused_and_removed(self):
        member = self.make_member("social_expired")
        ticket = self.make_ticket("login", user=member)
        name = v1_auth._social_ticket_config_name(ticket)
        payload = json.loads(Config.objects.get(name=name).value)
        payload["expires_at"] = int(timezone.now().timestamp()) - 1
        Config.objects.filter(name=name).update(value=json.dumps(payload))
        response = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Config.objects.filter(name=name).exists())

    def test_a_ticket_for_an_inactive_member_is_refused(self):
        member = self.make_member("social_inactive", active=False)
        ticket = self.make_ticket("login", user=member)
        response = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("g5_token", response.cookies)

    def test_the_signup_profile_shows_what_the_provider_returned(self):
        ticket = self.make_ticket("signup")
        response = self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": ticket})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["provider"], "kakao")
        self.assertEqual(data["email"], "social-person@example.test")
        self.assertEqual(data["name"], "Social Person")
        self.assertEqual(data["suggested_mb_id"], "social-person".replace("-", "_"))
        self.assertEqual(data["suggested_nick"], "SocialNick")

    def test_the_signup_profile_refuses_unknown_and_login_tickets(self):
        member = self.make_member("social_other")
        login_ticket = self.make_ticket("login", user=member)
        self.assertEqual(self.social_client.get("/api/v1/auth/social/signup-profile").status_code, 404)
        self.assertEqual(self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": "nope"}).status_code, 404)
        self.assertEqual(
            self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": login_ticket}).status_code, 404
        )

    def test_suggested_ids_and_nicknames_avoid_existing_ones(self):
        self.make_member("social_person", nickname="SocialNick")
        ticket = self.make_ticket("signup", email="social_person@example.test")
        data = self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": ticket}).json()["data"]
        self.assertNotEqual(data["suggested_mb_id"].lower(), "social_person")
        self.assertTrue(v1_auth.MEMBER_ID_RE.match(data["suggested_mb_id"]))
        self.assertNotEqual(data["suggested_nick"].lower(), "socialnick")

    def test_registering_with_a_signup_ticket_needs_no_captcha_and_links_the_identity(self):
        ticket = self.make_ticket("signup")
        response = self.social_client.post(
            "/api/v1/auth/register", {"social_signup_ticket": ticket}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        user = self.user_model.objects.get(username="social_person")
        self.assertEqual(user.email, "social-person@example.test")
        self.assertEqual(Profile.objects.get(user=user).nickname, "SocialNick")
        self.assertEqual(v1_auth._social_identity_user("kakao", "kakao-123"), user)
        self.assertFalse(Config.objects.filter(name=v1_auth._social_ticket_config_name(ticket)).exists())

    def test_registering_with_an_unknown_signup_ticket_is_not_found(self):
        response = self.social_client.post("/api/v1/auth/register", {"social_signup_ticket": "nope"}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_a_linked_identity_signs_in_through_the_exchange(self):
        self.social_client.post(
            "/api/v1/auth/register", {"social_signup_ticket": self.make_ticket("signup")}, format="json"
        )
        user = self.user_model.objects.get(username="social_person")
        ticket = self.make_ticket("login", user=v1_auth._social_identity_user("kakao", "kakao-123"))
        response = self.social_client.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_id"], user.username)

    def test_linking_an_existing_member_needs_the_right_password(self):
        member = self.make_member("link_member")
        ticket = self.make_ticket("signup")
        response = self.social_client.post(
            "/api/v1/auth/social/link-existing",
            {"ticket": ticket, "mb_id": "link_member", "password": "wrong-password-1"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(v1_auth._social_identity_user("kakao", "kakao-123"))
        self.assertTrue(Config.objects.filter(name=v1_auth._social_ticket_config_name(ticket)).exists())
        self.assertTrue(self.user_model.objects.filter(pk=member.pk).exists())

    def test_linking_an_existing_member_links_signs_in_and_uses_up_the_ticket(self):
        member = self.make_member("link_member")
        ticket = self.make_ticket("signup")
        response = self.social_client.post(
            "/api/v1/auth/social/link-existing",
            {"social_signup_ticket": ticket, "mb_id": "link_member", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "link_member")
        self.assertEqual(response.cookies["g5_token"].value, response.json()["data"]["token"])
        self.assertEqual(v1_auth._social_identity_user("kakao", "kakao-123"), member)
        self.assertFalse(Config.objects.filter(name=v1_auth._social_ticket_config_name(ticket)).exists())

    def test_an_identity_linked_to_someone_else_cannot_be_linked_again(self):
        first = self.make_member("link_first")
        self.make_member("link_second")
        v1_auth._link_social_identity(first, {"provider": "kakao", "provider_user_id": "kakao-123"})
        response = self.social_client.post(
            "/api/v1/auth/social/link-existing",
            {"ticket": self.make_ticket("signup"), "mb_id": "link_second", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(v1_auth._social_identity_user("kakao", "kakao-123"), first)

    def test_linking_with_an_unknown_ticket_or_an_inactive_member_is_refused(self):
        self.make_member("link_sleeper", active=False)
        unknown = self.social_client.post(
            "/api/v1/auth/social/link-existing",
            {"ticket": "nope", "mb_id": "link_sleeper", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(unknown.status_code, 404)
        inactive = self.social_client.post(
            "/api/v1/auth/social/link-existing",
            {"ticket": self.make_ticket("signup"), "mb_id": "link_sleeper", "password": PASSWORD},
            format="json",
        )
        self.assertIn(inactive.status_code, (401, 403))
        self.assertIsNone(v1_auth._social_identity_user("kakao", "kakao-123"))


class CertificationConfigTests(MemberApiTestBase):
    def cert_config(self):
        response = APIClient().get("/api/v1/auth/cert/config")
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_identity_verification_is_disabled_by_default(self):
        data = self.cert_config()
        self.assertFalse(data["enabled"])
        self.assertEqual(data["mode"], 0)
        self.assertFalse(data["required"])
        self.assertFalse(data["find_enabled"])
        self.assertEqual((data["simple"], data["hp"], data["ipin"]), ("", "", ""))

    def test_the_site_settings_switch_it_on(self):
        for name, value in (
            ("cf_cert_use", "1"), ("cf_cert_req", "1"), ("cf_cert_find", "1"),
            ("cf_cert_hp", "kcp"), ("cf_cert_simple", "inicis"), ("cf_cert_ipin", "kcb"),
        ):
            Config.objects.update_or_create(name=name, defaults={"value": value})
        data = self.cert_config()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["mode"], 1)
        self.assertTrue(data["required"])
        self.assertTrue(data["find_enabled"])
        self.assertEqual((data["simple"], data["hp"], data["ipin"]), ("inicis", "kcp", "kcb"))

    def test_an_unknown_provider_name_is_ignored(self):
        Config.objects.update_or_create(name="cf_cert_use", defaults={"value": "2"})
        Config.objects.update_or_create(name="cf_cert_hp", defaults={"value": "evil-provider"})
        data = self.cert_config()
        self.assertEqual(data["mode"], 2)
        self.assertEqual(data["hp"], "")

    def test_a_garbage_or_negative_mode_leaves_it_disabled(self):
        Config.objects.update_or_create(name="cf_cert_use", defaults={"value": "yes please"})
        self.assertFalse(self.cert_config()["enabled"])
        Config.objects.filter(name="cf_cert_use").update(value="-3")
        self.assertFalse(self.cert_config()["enabled"])

    @override_settings(GNUBOARD_CERT_USE="1", GNUBOARD_CERT_HP="kcp_v2")
    def test_environment_settings_override_the_site_settings(self):
        Config.objects.update_or_create(name="cf_cert_hp", defaults={"value": "kcp"})
        data = self.cert_config()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["hp"], "kcp_v2")

    def test_the_start_page_reports_a_disabled_provider_without_calling_out(self):
        response = APIClient().get("/api/cert/kcp_start.php")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cert_provider_disabled", response.content.decode())
        self.assertIn("identity-verification-result", response.content.decode())

    def test_an_enabled_provider_without_an_adapter_reports_it_is_not_implemented(self):
        Config.objects.update_or_create(name="cf_cert_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="cf_cert_hp", defaults={"value": "kcp"})
        response = APIClient().get("/api/cert/kcp_start.php")
        self.assertIn("cert_provider_unimplemented", response.content.decode())

    def test_the_find_page_is_refused_unless_the_find_option_is_on(self):
        Config.objects.update_or_create(name="cf_cert_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="cf_cert_hp", defaults={"value": "kcp"})
        response = APIClient().get("/api/cert/kcp_start.php", {"pageType": "find"})
        self.assertIn("cert_find_disabled", response.content.decode())

    def test_an_unknown_page_type_is_refused(self):
        response = APIClient().get("/api/cert/kcp_start.php", {"pageType": "../x"})
        self.assertIn("invalid_cert_page_type", response.content.decode())


class MemberProfileTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("me_member", nickname="Me Nick", point=50, first_name="Me Name")
        self.client = self.client_for(self.member)

    def test_get_me_requires_authentication(self):
        response = APIClient().get("/api/v1/members/me")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["success"])

    def test_get_me_returns_the_members_own_data(self):
        Profile.objects.filter(user=self.member).update(
            user_hp="010-1234-5678",
            user_zip="12345",
            user_addr1="서울시 어딘가",
            user_addr2="101호",
            user_addr_jibeon="지번주소",
        )
        response = self.client.get("/api/v1/members/me")
        self.assertEqual(response.status_code, 200)
        member = response.json()["data"]["member"]
        self.assertEqual(member["mb_id"], "me_member")
        self.assertEqual(member["mb_nick"], "Me Nick")
        self.assertEqual(member["mb_email"], "me_member@example.test")
        self.assertEqual(member["mb_point"], 50)
        self.assertEqual(member["mb_level"], 2)
        self.assertEqual(member["mb_hp"], "010-1234-5678")
        self.assertEqual(member["mb_zip"], "12345")
        self.assertEqual(member["mb_addr1"], "서울시 어딘가")
        self.assertEqual(member["mb_addr2"], "101호")
        self.assertEqual(member["mb_addr3"], "지번주소")
        self.assertIn("mb_datetime", member)
        self.assertIn("mb_today_login", member)
        self.assertNotIn("password", json.dumps(member).lower())

    def test_get_me_works_with_a_real_bearer_token(self):
        response = self.bearer_client(self.member).get("/api/v1/members/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "me_member")

    def test_patching_the_nickname_changes_it_in_the_database(self):
        response = self.client.patch("/api/v1/members/me", {"mb_nick": "Brand New"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["member"]["mb_nick"], "Brand New")
        self.assertEqual(Profile.objects.get(user=self.member).nickname, "Brand New")
        self.assertEqual(self.client.get("/api/v1/members/me").json()["data"]["member"]["mb_nick"], "Brand New")

    def test_patching_the_name_and_email_changes_them(self):
        response = self.client.patch(
            "/api/v1/members/me",
            {"mb_name": "Renamed Person", "mb_email": "renamed@example.test", "mb_password_current": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, "Renamed Person")
        self.assertEqual(self.member.email, "renamed@example.test")
        self.assertEqual(Profile.objects.get(user=self.member).realname, "Renamed Person")
        self.assertEqual(response.json()["data"]["member"]["mb_name"], "Renamed Person")

    def test_an_empty_patch_changes_nothing(self):
        response = self.client.patch("/api/v1/members/me", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "me_member@example.test")
        self.assertEqual(Profile.objects.get(user=self.member).nickname, "Me Nick")

    def test_keeping_the_same_nickname_is_not_a_duplicate(self):
        response = self.client.patch("/api/v1/members/me", {"mb_nick": "Me Nick"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_another_members_nickname_is_refused_whatever_its_case(self):
        self.make_member("other_member", nickname="Taken Nick")
        response = self.client.patch("/api/v1/members/me", {"mb_nick": "taken nick"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("nickname_exists", response.json()["errors"])
        self.assertEqual(Profile.objects.get(user=self.member).nickname, "Me Nick")

    def test_another_members_email_is_refused_and_nothing_else_is_saved(self):
        self.make_member("other_member")
        response = self.client.patch(
            "/api/v1/members/me", {"mb_email": "OTHER_MEMBER@example.test", "mb_nick": "Half Applied"}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("email_exists", response.json()["errors"])
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "me_member@example.test")
        self.assertEqual(Profile.objects.get(user=self.member).nickname, "Me Nick")

    def test_a_patch_never_touches_level_points_or_staff_flags(self):
        response = self.client.patch(
            "/api/v1/members/me",
            {"mb_level": 10, "mb_point": 99999, "is_staff": True, "is_superuser": True, "user_level": 10},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        profile = Profile.objects.get(user=self.member)
        self.assertEqual((profile.user_level, profile.user_point), (2, 50))
        self.assertFalse(self.member.is_staff or self.member.is_superuser)

    def test_changing_the_password_needs_the_current_one(self):
        response = self.client.patch(
            "/api/v1/members/me",
            {"mb_password": "Another-pass-77", "mb_password_re": "Another-pass-77"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_password_current", response.json()["errors"])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_a_wrong_current_password_leaves_the_password_alone(self):
        response = self.client.patch(
            "/api/v1/members/me",
            {"mb_password_current": "wrong-password-1", "mb_password": "Another-pass-77", "mb_password_re": "Another-pass-77"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_a_mismatching_or_weak_new_password_is_refused(self):
        mismatch = self.client.patch(
            "/api/v1/members/me",
            {"mb_password_current": PASSWORD, "mb_password": "Another-pass-77", "mb_password_re": "Different-pass-1"},
            format="json",
        )
        self.assertEqual(mismatch.status_code, 422)
        weak = self.client.patch(
            "/api/v1/members/me",
            {"mb_password_current": PASSWORD, "mb_password": "12345678", "mb_password_re": "12345678"},
            format="json",
        )
        self.assertEqual(weak.status_code, 422)
        self.assertIn("mb_password", weak.json()["errors"])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_a_valid_password_change_takes_effect_for_the_next_login(self):
        response = self.client.patch(
            "/api/v1/members/me",
            {"mb_password_current": PASSWORD, "mb_password": "Another-pass-77", "mb_password_re": "Another-pass-77"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("Another-pass-77"))
        self.assertFalse(self.member.check_password(PASSWORD))
        old = APIClient().post("/api/v1/auth/login", {"mb_id": "me_member", "password": PASSWORD}, format="json")
        new = APIClient().post("/api/v1/auth/login", {"mb_id": "me_member", "password": "Another-pass-77"}, format="json")
        self.assertEqual(old.status_code, 401)
        self.assertEqual(new.status_code, 200)

    def test_anonymous_patch_is_unauthorized(self):
        response = APIClient().patch("/api/v1/members/me", {"mb_nick": "Hacked"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Profile.objects.get(user=self.member).nickname, "Me Nick")


class MemberIconTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        media_root = tempfile.mkdtemp(prefix="member-media-")
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=media_root)
        media.enable()
        self.addCleanup(media.disable)
        self.member = self.make_member("icon_member")
        self.client = self.client_for(self.member)

    def png(self, name="icon.png"):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 30, 30)).save(buffer, format="PNG")
        return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

    def test_uploading_an_icon_stores_it_and_returns_its_url(self):
        response = self.client.post("/api/v1/members/me/icon", {"mb_icon": self.png()}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content[:300])
        profile = Profile.objects.get(user=self.member)
        self.assertTrue(profile.icon.name)
        self.assertTrue(profile.icon.storage.exists(profile.icon.name))
        icon_path = response.json()["data"]["member"]["mb_icon_path"]
        self.assertTrue(icon_path.startswith("http"))
        self.assertIn(profile.icon.name.replace("\\", "/").split("/")[-1], icon_path)

    def test_the_file_may_be_sent_under_the_icon_or_file_field(self):
        for field in ("icon", "file"):
            response = self.client.post("/api/v1/members/me/icon", {field: self.png()}, format="multipart")
            self.assertEqual(response.status_code, 200, field)

    def test_a_request_without_a_file_is_a_validation_error(self):
        response = self.client.post("/api/v1/members/me/icon", {}, format="multipart")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_icon", response.json()["errors"])
        self.assertFalse(Profile.objects.get(user=self.member).icon)

    def test_a_file_that_is_not_really_an_image_is_refused(self):
        fake = SimpleUploadedFile("icon.png", b"<?php echo 1; ?>", content_type="image/png")
        response = self.client.post("/api/v1/members/me/icon", {"mb_icon": fake}, format="multipart")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Profile.objects.get(user=self.member).icon)

    def test_anonymous_upload_is_unauthorized(self):
        response = APIClient().post("/api/v1/members/me/icon", {"mb_icon": self.png()}, format="multipart")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Profile.objects.get(user=self.member).icon)


class OtherMemberProfileTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.viewer = self.make_member("viewer_member")
        self.target = self.make_member(
            "target_member", nickname="Target Nick", point=1234, first_name="Secret Real Name"
        )
        Profile.objects.filter(user=self.target).update(user_homepage="https://target.example.test", realname="Secret Real Name")

    def test_the_profile_requires_authentication(self):
        self.assertEqual(APIClient().get("/api/v1/members/target_member/profile").status_code, 401)

    def test_the_profile_shows_public_data_only(self):
        response = self.client_for(self.viewer).get("/api/v1/members/target_member/profile")
        self.assertEqual(response.status_code, 200)
        member = response.json()["data"]["member"]
        self.assertEqual(member["mb_id"], "target_member")
        self.assertEqual(member["mb_nick"], "Target Nick")
        self.assertEqual(member["mb_homepage"], "https://target.example.test")
        self.assertIn("reg_days", member)
        for private in ("mb_email", "mb_name", "mb_no", "is_staff", "is_superuser", "mb_today_login"):
            self.assertNotIn(private, member, private)
        body = response.content.decode()
        self.assertNotIn("target_member@example.test", body)
        self.assertNotIn("Secret Real Name", body)

    def test_an_unknown_member_is_not_found(self):
        response = self.client_for(self.viewer).get("/api/v1/members/ghost_member/profile")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])

    def test_the_registration_age_counts_whole_days(self):
        self.user_model.objects.filter(pk=self.target.pk).update(date_joined=timezone.now() - timedelta(days=10, hours=1))
        member = self.client_for(self.viewer).get("/api/v1/members/target_member/profile").json()["data"]["member"]
        self.assertEqual(member["reg_days"], 10)


class MemberActivityListTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.me = self.make_member("list_me", point=10)
        self.other = self.make_member("list_other", point=10)
        group = Group.objects.create(gr_id="member-group", gr_subject="Members")
        self.board = Board.objects.create(
            group=group, bo_subject="회원게시판", bo_table="member-board", bo_skin="basic", bo_mobile_skin="basic",
            bo_write_level=1, bo_comment_level=1, bo_read_level=1, bo_list_level=1, bo_reply_level=1,
        )
        self.me_client = self.client_for(self.me)
        self.other_client = self.client_for(self.other)

    def write(self, client, subject):
        response = client.post(
            f"/api/v1/boards/{self.board.bo_table}/posts", {"wr_subject": subject, "wr_content": "Body"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response.json()["data"]["wr_id"]

    def comment(self, client, wr_id, text):
        response = client.post(f"/api/v1/comments/{self.board.bo_table}/{wr_id}", {"wr_content": text}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response.json()["data"]["id"]

    def test_the_lists_require_authentication(self):
        for path in ("posts", "comments", "points"):
            self.assertEqual(APIClient().get(f"/api/v1/members/me/{path}").status_code, 401, path)

    def test_my_posts_lists_only_my_posts_newest_first(self):
        first = self.write(self.me_client, "My first")
        second = self.write(self.me_client, "My second")
        self.write(self.other_client, "Not mine")
        response = self.me_client.get("/api/v1/members/me/posts")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual([row["wr_id"] for row in rows], [second, first])
        self.assertEqual(rows[0]["wr_subject"], "My second")
        self.assertEqual(rows[0]["bo_table"], "member-board")
        self.assertEqual(rows[0]["bo_subject"], "회원게시판")
        self.assertEqual(response.json()["meta"]["total"], 2)

    def test_my_posts_paginates(self):
        for index in range(3):
            self.write(self.me_client, f"Post {index}")
        response = self.me_client.get("/api/v1/members/me/posts", {"per_page": 2, "page": 2})
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json()["meta"]["total"], 3)

    def test_my_posts_is_empty_for_a_member_with_none(self):
        response = self.me_client.get("/api/v1/members/me/posts")
        self.assertEqual(response.json()["data"], [])

    def test_a_deleted_post_leaves_the_list(self):
        wr_id = self.write(self.me_client, "Short lived")
        Post.objects.filter(pk=wr_id).delete()
        self.assertEqual(self.me_client.get("/api/v1/members/me/posts").json()["data"], [])

    def test_my_comments_lists_only_my_comments_with_their_post(self):
        wr_id = self.write(self.other_client, "Other post")
        mine = self.comment(self.me_client, wr_id, "My comment text")
        self.comment(self.other_client, wr_id, "Their comment text")
        response = self.me_client.get("/api/v1/members/me/comments")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual([row["wr_id"] for row in rows], [mine])
        self.assertEqual(rows[0]["wr_content"], "My comment text")
        self.assertEqual(rows[0]["wr_parent"], Comment.objects.get(pk=mine).post_id)
        self.assertEqual(rows[0]["bo_table"], "member-board")
        self.assertNotIn("Their comment text", response.content.decode())

    def test_my_comments_on_a_post_I_may_no_longer_read_are_hidden(self):
        wr_id = self.write(self.other_client, "Soon restricted")
        self.comment(self.me_client, wr_id, "Visible comment")
        Board.objects.filter(pk=self.board.pk).update(bo_read_level=9)
        response = self.me_client.get("/api/v1/members/me/comments")
        self.assertEqual(response.json()["data"], [])

    def test_my_points_lists_only_my_history_newest_first(self):
        now = timezone.now()
        old = User_Point.objects.create(
            user=self.me, po_datetime=now - timedelta(days=2), po_content="older", po_point=5, po_mb_point=5
        )
        new = User_Point.objects.create(
            user=self.me, po_datetime=now - timedelta(days=1), po_content="newer", po_point=-2, po_mb_point=3,
            po_rel_table="free", po_rel_action="읽기",
        )
        User_Point.objects.create(user=self.other, po_datetime=now, po_content="not mine", po_point=99, po_mb_point=99)
        response = self.me_client.get("/api/v1/members/me/points")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual([row["po_id"] for row in rows], [new.pk, old.pk])
        self.assertEqual(rows[0]["po_content"], "newer")
        self.assertEqual(rows[0]["po_point"], -2)
        self.assertEqual(rows[0]["po_mb_point"], 3)
        self.assertEqual(rows[0]["po_rel_table"], "free")
        self.assertEqual(response.json()["meta"]["total"], 2)
        self.assertNotIn("not mine", response.content.decode())

    def test_my_points_paginates_fifteen_at_a_time(self):
        for index in range(17):
            User_Point.objects.create(
                user=self.me, po_datetime=timezone.now() - timedelta(minutes=index), po_content=f"p{index}", po_point=1, po_mb_point=index
            )
        first = self.me_client.get("/api/v1/members/me/points").json()
        second = self.me_client.get("/api/v1/members/me/points", {"page": 2}).json()
        self.assertEqual(len(first["data"]), 15)
        self.assertEqual(len(second["data"]), 2)
        self.assertEqual(first["meta"]["total"], 17)


class SettingsEndpointTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        # The settings endpoint reads the process-wide site config cache.
        site_config.clear()
        self.addCleanup(site_config.clear)

    def test_settings_are_public_and_expose_the_site_title(self):
        Config.objects.update_or_create(name="cf_title", defaults={"value": "Member Test Site"})
        response = APIClient().get("/api/v1/settings")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["cf_title"], "Member Test Site")
        for key in ("cf_company_name", "cf_company_email", "visit", "infinite_scroll", "pwa_enabled"):
            self.assertIn(key, data)
        self.assertIsInstance(data["cf_bbs_rewrite"], int)

    def test_settings_do_not_leak_secrets(self):
        Config.objects.update_or_create(name="cf_naver_secret", defaults={"value": "super-secret-value"})
        Config.objects.update_or_create(name="cf_recaptcha_secret_key", defaults={"value": "recaptcha-secret"})
        body = APIClient().get("/api/v1/settings").content.decode()
        self.assertNotIn("super-secret-value", body)
        self.assertNotIn("recaptcha-secret", body)

    def test_visit_counts_cover_today_yesterday_and_the_busiest_day(self):
        cache.clear()  # past days' counts are cached (api.v1_community.visit_stats)
        now = timezone.now()
        yesterday = now - timedelta(days=1)

        def visit(when, **kwargs):
            values = {"method": "GET", "path": "/boards/free", "status_code": 200}
            values.update(kwargs)
            log = VisitLog.objects.create(**values)
            VisitLog.objects.filter(pk=log.pk).update(created_at=when)

        for _ in range(3):
            visit(now)
        visit(yesterday)
        visit(now, path="/api/v1/status")          # API calls are not page views
        visit(now, status_code=404)                # neither are errors
        visit(now, method="POST")                  # nor writes
        visit(now, is_staff_area=True)             # nor admin pages
        stats = APIClient().get("/api/v1/settings").json()["data"]["visit"]
        self.assertEqual(stats["today"], 3)
        self.assertEqual(stats["yesterday"], 1)
        self.assertEqual(stats["max"], 3)
        self.assertEqual(stats["total"], 4)


class PasswordResetTests(MemberApiTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("reset_member")
        self.url = "/api/v1/auth/password-reset"

    def request_reset(self, **overrides):
        payload = {"step": "request", "mb_id": "reset_member", "mb_email": "reset_member@example.test"}
        payload.update(overrides)
        return APIClient().post(self.url, payload, format="json")

    def issue_token(self, **overrides):
        """Request a reset and read the token from the mailed link (it is never in the response)."""
        mail.outbox.clear()
        response = self.request_reset(**overrides)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertNotIn("token", response.content.decode().lower())
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"uid=([\w-]+)&token=([\w-]+)", mail.outbox[0].body)
        self.assertIsNotNone(link, mail.outbox[0].body)
        return f"{link.group(1)}:{link.group(2)}"

    def reset(self, reset_token, password=PASSWORD + "new", confirm=None, **extra):
        payload = {
            "step": "reset", "reset_token": reset_token, "mb_password": password,
            "mb_password_re": password if confirm is None else confirm, **extra,
        }
        return APIClient().post(self.url, payload, format="json")

    def test_the_reset_link_is_mailed_and_never_returned(self):
        response = self.request_reset()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["sent"], True)
        self.assertNotIn("token", response.content.decode().lower())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reset_member@example.test"])
        self.assertIn("/forgot-password?uid=", mail.outbox[0].body)

    def test_an_unknown_pair_gets_the_same_answer_and_no_mail(self):
        expected = self.request_reset().json()
        mail.outbox.clear()
        for overrides in ({"mb_id": "nobody_here"}, {"mb_email": "wrong@example.test"}):
            response = self.request_reset(**overrides)
            self.assertEqual(response.status_code, 200, overrides)
            self.assertEqual(response.json(), expected)
        self.assertEqual(mail.outbox, [])

    def test_both_fields_are_required(self):
        for overrides in ({"mb_email": ""}, {"mb_id": ""}):
            self.assertEqual(self.request_reset(**overrides).status_code, 422, overrides)

    def test_an_inactive_member_gets_no_mail(self):
        self.make_member("reset_sleeper", active=False)
        response = self.request_reset(mb_id="reset_sleeper", mb_email="reset_sleeper@example.test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_the_email_match_ignores_case(self):
        self.issue_token(mb_email="RESET_MEMBER@EXAMPLE.TEST")

    def test_a_malformed_member_id_in_the_token_is_refused(self):
        for token in ("YWJj:x", "!!!:x"):
            response = self.reset(token, "Zzz-pass-123")
            self.assertEqual(response.status_code, 422, token)

    def test_the_whole_reset_flow_changes_the_password(self):
        new_password = "Brand-new-pass-42"
        response = self.reset(self.issue_token(), new_password)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(response.json()["data"]["reset"])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(new_password))
        self.assertFalse(self.member.check_password(PASSWORD))
        login = APIClient().post("/api/v1/auth/login", {"mb_id": "reset_member", "password": new_password}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_the_uid_and_token_may_be_sent_separately(self):
        uid, token = self.issue_token().split(":", 1)
        response = self.reset("", "Brand-new-pass-42", uid=uid, token=token)
        self.assertEqual(response.status_code, 200, response.content[:300])

    def test_a_reset_token_works_only_once(self):
        token = self.issue_token()
        self.assertEqual(self.reset(token, "Brand-new-pass-42").status_code, 200)
        again = self.reset(token, "Another-new-pass-43")
        self.assertEqual(again.status_code, 422)
        self.assertIn("invalid_reset_token", again.json()["errors"])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("Brand-new-pass-42"))

    def test_a_forged_or_malformed_token_is_refused(self):
        uid = self.issue_token().split(":", 1)[0]
        for token in ("", "garbage", f"{uid}:not-a-token", f"{uid}:", ":"):
            response = self.reset(token)
            self.assertEqual(response.status_code, 422, token)
            self.assertIn("invalid_reset_token", response.json()["errors"], token)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))

    def test_a_token_for_another_member_does_not_reset_this_one(self):
        other = self.make_member("reset_other")
        token = self.issue_token(mb_id="reset_other", mb_email="reset_other@example.test")
        self.assertEqual(self.reset(token, "Brand-new-pass-42").status_code, 200)
        self.member.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))
        self.assertTrue(other.check_password("Brand-new-pass-42"))

    def test_a_token_stops_working_when_the_member_is_deactivated(self):
        token = self.issue_token()
        self.user_model.objects.filter(pk=self.member.pk).update(is_active=False)
        self.assertEqual(self.reset(token).status_code, 422)

    def test_a_mismatching_or_weak_new_password_is_refused_and_the_token_survives(self):
        token = self.issue_token()
        self.assertEqual(self.reset(token, "Brand-new-pass-42", confirm="Different-pass-1").status_code, 422)
        self.assertEqual(self.reset(token, "").status_code, 422)
        weak = self.reset(token, "12345678")
        self.assertEqual(weak.status_code, 422)
        self.assertIn("mb_password", weak.json()["errors"])
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(PASSWORD))
        self.assertEqual(self.reset(token, "Brand-new-pass-42").status_code, 200)

    def test_the_identity_verification_step_is_unconfigured(self):
        response = APIClient().post(self.url, {"step": "cert_request"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertIn("cert_password_reset_unconfigured", response.json()["errors"])

    def test_an_unknown_step_is_refused(self):
        response = APIClient().post(self.url, {"step": "explode"}, format="json")
        self.assertEqual(response.status_code, 422)


class AuthRateLimitTests(MemberApiTestBase):
    """Login and register are rate limited per client (10/min and 5/min); the limit used to be ignored."""

    def test_the_eleventh_login_attempt_in_a_minute_is_refused(self):
        self.make_member("rate_member")
        client = APIClient()
        codes = [
            client.post("/api/v1/auth/login", {"mb_id": "rate_member", "password": "wrong-pass-1"}, format="json").status_code
            for _ in range(11)
        ]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10], 429)

    def test_the_sixth_registration_in_a_minute_is_refused(self):
        client = APIClient()
        codes = [client.post("/api/v1/auth/register", {"mb_id": f"rate_new{i}"}, format="json").status_code for i in range(6)]
        self.assertNotIn(429, codes[:5])
        self.assertEqual(codes[5], 429)


class MemberAccountHardeningTests(MemberApiTestBase):
    """Fixes for gaps the member tests found: refresh, profile validation, token revocation."""

    def setUp(self):
        super().setUp()
        self.member = self.make_member("harden_member")

    def login(self):
        response = APIClient().post("/api/v1/auth/login", {"mb_id": "harden_member", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_a_deactivated_member_cannot_refresh(self):
        refresh = self.login()["refresh_token"]
        self.user_model.objects.filter(pk=self.member.pk).update(is_active=False)
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": refresh}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_an_invalid_email_or_overlong_nickname_is_refused(self):
        client = APIClient()
        client.force_authenticate(user=self.member)
        self.assertEqual(client.patch("/api/v1/members/me", {"mb_email": "not-an-email"}, format="json").status_code, 422)
        self.assertEqual(client.patch("/api/v1/members/me", {"mb_nick": "n" * 101}, format="json").status_code, 422)
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "harden_member@example.test")

    def test_a_member_without_a_profile_row_can_still_update(self):
        Profile.objects.filter(user=self.member).delete()
        member = self.user_model.objects.get(pk=self.member.pk)
        client = APIClient()
        client.force_authenticate(user=member)
        response = client.patch("/api/v1/members/me", {"mb_nick": "rebuilt-nick"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(Profile.objects.get(user=member).nickname, "rebuilt-nick")

    def test_changing_the_password_logs_out_other_devices_but_keeps_this_one(self):
        current_device = self.login()
        other_device = self.login()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {current_device['token']}")
        response = client.patch(
            "/api/v1/members/me",
            {"mb_password_current": PASSWORD, "mb_password": "Changed-pass-77", "mb_password_re": "Changed-pass-77"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        fresh = response.json()["data"]
        self.assertEqual(APIClient().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {current_device['token']}").status_code, 401)
        self.assertEqual(APIClient().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {other_device['token']}").status_code, 401)
        self.assertEqual(APIClient().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {fresh['token']}").status_code, 200)
        self.assertEqual(APIClient().post("/api/v1/auth/refresh", {"refresh_token": other_device["refresh_token"]}, format="json").status_code, 401)
        self.assertEqual(APIClient().post("/api/v1/auth/refresh", {"refresh_token": fresh["refresh_token"]}, format="json").status_code, 200)

    def test_a_password_reset_logs_out_every_device(self):
        device = self.login()
        mail.outbox.clear()
        APIClient().post("/api/v1/auth/password-reset", {"step": "request", "mb_id": "harden_member", "mb_email": "harden_member@example.test"}, format="json")
        link = re.search(r"uid=([\w-]+)&token=([\w-]+)", mail.outbox[0].body)
        reset = APIClient().post(
            "/api/v1/auth/password-reset",
            {"step": "reset", "uid": link.group(1), "token": link.group(2), "mb_password": "Reset-pass-88", "mb_password_re": "Reset-pass-88"},
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.content[:300])
        self.assertEqual(APIClient().post("/api/v1/auth/refresh", {"refresh_token": device["refresh_token"]}, format="json").status_code, 401)
        self.assertEqual(APIClient().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {device['token']}").status_code, 401)

    def test_logout_immediately_revokes_this_access_token_only(self):
        current = self.login()
        other = self.login()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {current['token']}")

        response = client.post("/api/v1/auth/logout", {"refresh_token": current["refresh_token"]}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(APIClient().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {other['token']}").status_code, 200)
        self.assertEqual(APIClient().post("/api/v1/auth/refresh", {"refresh_token": other["refresh_token"]}, format="json").status_code, 200)


class WithdrawnProfileTests(MemberApiTestBase):
    def test_a_deactivated_members_profile_is_not_found(self):
        viewer = self.make_member("profile_viewer")
        self.make_member("profile_gone", active=False)
        client = APIClient()
        client.force_authenticate(user=viewer)
        self.assertEqual(client.get("/api/v1/members/profile_gone/profile").status_code, 404)
