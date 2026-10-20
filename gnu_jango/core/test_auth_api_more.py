"""More v1 auth API tests: login/register input handling, cookies, refresh rotation, logout, and the
whole social login round trip (start, callback, exchange, link-existing) with the provider HTTP mocked.

Gnuboard5 references: bbs/login_check.php, bbs/register_form_update.php, lib/register.lib.php
(reserve_mb_id, reserve_mb_nick, prohibit_mb_email, valid_mb_email, valid_mb_nick) and plugin/social.
"""

import json
import urllib.error
from io import BytesIO
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api import v1_auth
from gnu_jango.api.shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile, User_Point

PASSWORD = "Str0ng-pass-99"
CAPTCHA_PATCH = "gnu_jango.api.v1_auth._captcha_matches"
HTTP_PATCH = "gnu_jango.api.v1_auth._http_json_request"
AUTH_COOKIES = ("g5_token", "g5_refresh", "g5_auth_hint", "g5_auto_login")
LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
EXCHANGE_URL = "/api/v1/auth/social/exchange"
LINK_URL = "/api/v1/auth/social/link-existing"
START_URL = "/api/social/start.php"
SIGNUP_START_URL = "/api/social/signup.php"
CALLBACK_URL = "/api/social/callback.php"

SOCIAL_SETTINGS = {
    "SOCIAL_KAKAO_REST_KEY": "kakao-key",
    "SOCIAL_NAVER_CLIENT_ID": "naver-id",
    "SOCIAL_NAVER_CLIENT_SECRET": "naver-secret",
    "SOCIAL_GOOGLE_CLIENT_ID": "google-id",
    "SOCIAL_GOOGLE_CLIENT_SECRET": "google-secret",
    "SOCIAL_FACEBOOK_APP_ID": "facebook-id",
    "SOCIAL_FACEBOOK_APP_SECRET": "facebook-secret",
    "SOCIAL_TWITTER_CLIENT_ID": "twitter-id",
    "SOCIAL_TWITTER_CLIENT_SECRET": "twitter-secret",
    "SOCIAL_PAYCO_CLIENT_ID": "payco-id",
    "SOCIAL_PAYCO_CLIENT_SECRET": "payco-secret",
    "SOCIAL_PAYCO_SERVICE_PROVIDER_CODE": "FRIENDS",
}

USERINFO = {
    "naver": {"response": {"id": "n-1", "email": "n@example.test", "name": "Nam", "nickname": "NaverNick", "mobile": "010", "profile_image": "http://img/n.png"}},
    "kakao": {"id": 4242, "kakao_account": {"email": "k@example.test", "name": "Kim", "phone_number": "+82", "profile": {"nickname": "KakaoNick", "profile_image_url": "http://img/k.png"}}},
    "google": {"sub": "g-1", "email": "g@example.test", "name": "Gil", "picture": "http://img/g.png"},
    "facebook": {"id": "f-1", "email": "f@example.test", "name": "Fay", "picture": {"data": {"url": "http://img/f.png"}}},
    "twitter": {"data": {"id": "t-1", "confirmed_email": "t@example.test", "name": "Tae", "username": "taeuser", "profile_image_url": "http://img/t.png"}},
    "payco": {"data": {"member": {"idNo": "p-1", "email": "p@example.test", "name": "Pay", "mobile": "010"}}},
}


class AuthTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user_model = get_user_model()

    def make_member(self, username, *, active=True, **extra):
        user = self.user_model.objects.create_user(
            username=username, email=f"{username}@example.test", password=PASSWORD, is_active=active, **extra
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.nickname = f"nick-{username}"
        profile.user_level = 2
        profile.save()
        return self.user_model.objects.get(pk=user.pk)

    def login(self, payload, client=None, **extra):
        return (client or APIClient()).post(LOGIN_URL, payload, format="json", **extra)

    def register(self, client=None, **overrides):
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
        with mock.patch(CAPTCHA_PATCH, return_value=True):
            return (client or APIClient()).post(REGISTER_URL, payload, format="json")

    def set_config(self, name, value):
        Config.objects.update_or_create(name=name, defaults={"value": value})


class LoginInputTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("login_in")

    def test_the_member_can_log_in_with_the_e_mail_address_in_any_case(self):
        response = self.login({"mb_id": "LOGIN_IN@Example.Test", "mb_password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response.json()["data"]["member"]["mb_id"], "login_in")

    def test_the_member_id_is_matched_without_regard_to_case_and_outer_spaces(self):
        response = self.login({"mb_id": "  LOGIN_in ", "mb_password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.content[:200])

    def test_a_blocked_member_with_the_right_password_gets_the_wrong_password_answer(self):
        self.make_member("login_blocked", active=False)
        wrong = self.login({"mb_id": "login_in", "mb_password": "wrong-password-1"})
        blocked = self.login({"mb_id": "login_blocked", "mb_password": PASSWORD})
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json()["message"], wrong.json()["message"])
        self.assertNotIn("g5_token", blocked.cookies)

    def test_an_inactive_account_that_slips_past_the_backend_is_still_refused(self):
        inactive = self.make_member("login_slip", active=False)
        with mock.patch("gnu_jango.api.v1_auth.authenticate", return_value=inactive):
            response = self.login({"mb_id": "login_slip", "mb_password": PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "inactive_member")
        self.assertNotIn("g5_token", response.cookies)

    def test_a_body_that_is_not_an_object_is_a_validation_error(self):
        for body in ([], ["mb_id"], "text", None):
            response = APIClient().post(LOGIN_URL, body, format="json")
            self.assertEqual(response.status_code, 422, body)

    def test_unparseable_json_is_a_client_error(self):
        response = APIClient().post(LOGIN_URL, "{not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)


    def test_blank_and_whitespace_credentials_are_refused_as_missing(self):
        self.assertEqual(self.login({"mb_id": "   ", "mb_password": PASSWORD}).status_code, 422)
        self.assertEqual(self.login({"mb_id": "login_in", "mb_password": ""}).status_code, 422)

    def test_sql_wildcards_and_quotes_in_the_id_match_nobody(self):
        for probe in ("' OR '1'='1", "login_in' --", "%", "login_%", "\u0000", "日本語", "😀" * 30):
            response = self.login({"mb_id": probe, "mb_password": PASSWORD})
            self.assertEqual(response.status_code, 401, repr(probe))

    def test_a_very_long_id_and_password_are_refused_without_an_error(self):
        response = self.login({"mb_id": "a" * 5000, "mb_password": "p" * 5000})
        self.assertEqual(response.status_code, 401)

    # A number, list or object as mb_id is a validation error, never a server error.
    def test_a_json_number_as_the_id_is_refused_not_a_server_error(self):
        for payload in ({"mb_id": 12345, "mb_password": PASSWORD}, {"mb_id": ["a"], "mb_password": PASSWORD}, {"mb_id": {"a": 1}, "mb_password": PASSWORD}):
            response = self.login(payload)
            self.assertIn(response.status_code, (401, 422), payload)

    def test_a_json_number_as_the_password_is_refused_not_a_server_error(self):
        response = self.login({"mb_id": "login_in", "mb_password": 12345678})
        self.assertIn(response.status_code, (401, 422))

    # login_check.php auto-logs-in only when the auto_login checkbox is on: "0", "false" and "" are off.
    def test_a_form_post_saying_auto_login_zero_does_not_keep_the_login_for_thirty_days(self):
        response = APIClient().post(LOGIN_URL, {"mb_id": "login_in", "mb_password": PASSWORD, "auto_login": "0"})
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response.json()["data"]["auto_login"], 0)
        self.assertEqual(response.cookies["g5_refresh"]["max-age"], "")

    def test_the_login_points_of_the_day_are_granted_once(self):
        self.set_config("cf_login_point", "10")
        self.login({"mb_id": "login_in", "mb_password": PASSWORD})
        self.login({"mb_id": "login_in", "mb_password": PASSWORD})
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@login").count(), 1)

    def test_every_login_issues_its_own_token_pair(self):
        first = self.login({"mb_id": "login_in", "mb_password": PASSWORD}).json()["data"]
        second = self.login({"mb_id": "login_in", "mb_password": PASSWORD}).json()["data"]
        self.assertNotEqual(first["refresh_token"], second["refresh_token"])
        self.assertNotEqual(first["token"], second["token"])

    def test_the_password_is_never_part_of_the_response(self):
        response = self.login({"mb_id": "login_in", "mb_password": PASSWORD})
        self.assertNotIn(PASSWORD, response.content.decode())
        self.assertNotIn("password", json.dumps(response.json()["data"]["member"]).lower())


class LoginSessionsTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("session_member")
        self.other = self.make_member("session_other")

    def login_with_agent(self, username, agent):
        response = self.login(
            {"mb_id": username, "mb_password": PASSWORD},
            HTTP_USER_AGENT=agent,
        )
        self.assertEqual(response.status_code, 200, response.content[:200])
        return response.json()["data"]

    def client_for(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_the_session_list_contains_the_members_unexpired_refresh_tokens(self):
        first = self.login_with_agent("session_member", "Session Browser One")
        self.login_with_agent("session_member", "Session Browser Two")
        self.login_with_agent("session_other", "Other Member Browser")

        response = self.client_for(first["token"]).get("/api/v1/auth/sessions")

        self.assertEqual(response.status_code, 200, response.content[:200])
        sessions = response.json()["data"]["sessions"]
        self.assertEqual(len(sessions), 2)
        self.assertEqual({session["user_agent"] for session in sessions}, {"Session Browser One", "Session Browser Two"})
        self.assertEqual(
            {session["token_id"] for session in sessions},
            set(OutstandingToken.objects.filter(user=self.member).values_list("pk", flat=True)),
        )
        self.assertTrue(all(session["expires_at"] for session in sessions))
        self.assertTrue(all("token" not in session for session in sessions))

    def test_revoking_another_session_invalidates_its_access_and_refresh_tokens(self):
        current = self.login_with_agent("session_member", "Current Browser")
        other = self.login_with_agent("session_member", "Other Browser")
        client = self.client_for(current["token"])
        sessions = client.get("/api/v1/auth/sessions").json()["data"]["sessions"]
        other_session = next(session for session in sessions if session["user_agent"] == "Other Browser")

        response = client.post("/api/v1/auth/sessions/revoke", {"token_id": other_session["token_id"]}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertTrue(response.json()["data"]["revoked"])
        self.assertFalse(response.json()["data"]["current"])
        self.assertEqual(self.client_for(current["token"]).get(ME_URL).status_code, 200)
        self.assertEqual(self.client_for(other["token"]).get(ME_URL).status_code, 401)
        self.assertEqual(APIClient().post(REFRESH_URL, {"refresh_token": other["refresh_token"]}, format="json").status_code, 401)

    def test_revoking_the_current_session_invalidates_it_and_clears_auth_cookies(self):
        current = self.login_with_agent("session_member", "Current Browser")
        client = self.client_for(current["token"])
        session = client.get("/api/v1/auth/sessions").json()["data"]["sessions"][0]

        response = client.post("/api/v1/auth/sessions/revoke", {"token_id": session["token_id"]}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertTrue(response.json()["data"]["current"])
        self.assertEqual(int(response.cookies["g5_token"]["max-age"]), 0)
        self.assertEqual(client.get(ME_URL).status_code, 401)

    def test_a_member_cannot_revoke_another_members_session(self):
        member_session = self.login_with_agent("session_member", "Member Browser")
        other_session = self.login_with_agent("session_other", "Other Browser")
        token_id = OutstandingToken.objects.get(user=self.member).pk

        response = self.client_for(other_session["token"]).post(
            "/api/v1/auth/sessions/revoke", {"token_id": token_id}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(APIClient().post(REFRESH_URL, {"refresh_token": member_session["refresh_token"]}, format="json").status_code, 200)


class LoginCartMergeTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("cart_merge")
        self.name = auth_cart_config_name(self.member)

    def log_in_with_guest_cart(self, rows):
        client = APIClient()
        session = client.session
        session[SHOP_CART_SESSION_KEY] = rows
        session.save()
        response = self.login({"mb_id": "cart_merge", "mb_password": PASSWORD}, client=client)
        self.assertEqual(response.status_code, 200, response.content[:200])
        return client

    def test_the_guest_cart_moves_into_the_member_cart_at_login(self):
        client = self.log_in_with_guest_cart([{"ct_id": 1, "it_id": "a"}, {"ct_id": 2, "it_id": "b"}])
        self.assertEqual([row["ct_id"] for row in json.loads(Config.objects.get(name=self.name).value)], [1, 2])
        self.assertNotIn(SHOP_CART_SESSION_KEY, client.session)

    def test_rows_already_in_the_member_cart_are_not_duplicated(self):
        self.set_config(self.name, json.dumps([{"ct_id": 1, "it_id": "a"}]))
        self.log_in_with_guest_cart([{"ct_id": 1, "it_id": "a"}, {"ct_id": 3, "it_id": "c"}, "junk"])
        self.assertEqual([row["ct_id"] for row in json.loads(Config.objects.get(name=self.name).value)], [1, 3])

    def test_a_corrupt_stored_cart_is_replaced_by_the_guest_cart(self):
        for stored in ("{not json", json.dumps({"ct_id": 1})):
            self.set_config(self.name, stored)
            self.log_in_with_guest_cart([{"ct_id": 9, "it_id": "z"}])
            rows = json.loads(Config.objects.get(name=self.name).value)
            # the moved line is stamped with when it was put in the cart (de_cart_keep_term)
            self.assertEqual([{key: row[key] for key in ("ct_id", "it_id")} for row in rows], [{"ct_id": 9, "it_id": "z"}])
            self.assertIsInstance(rows[0]["ct_time"], int)

    def test_login_without_a_guest_cart_leaves_the_member_cart_alone(self):
        self.set_config(self.name, json.dumps([{"ct_id": 5}]))
        self.login({"mb_id": "cart_merge", "mb_password": PASSWORD})
        self.assertEqual(json.loads(Config.objects.get(name=self.name).value), [{"ct_id": 5}])


class AuthCookieTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.make_member("cookie_member")

    def test_over_plain_http_the_cookies_are_not_marked_secure(self):
        response = self.login({"mb_id": "cookie_member", "mb_password": PASSWORD})
        for name in ("g5_token", "g5_refresh", "g5_auth_hint"):
            self.assertEqual(response.cookies[name]["secure"], "", name)

    def test_over_https_every_auth_cookie_is_secure_and_lax(self):
        response = self.login({"mb_id": "cookie_member", "mb_password": PASSWORD}, secure=True)
        for name in ("g5_token", "g5_refresh", "g5_auth_hint"):
            self.assertTrue(response.cookies[name]["secure"], name)
            self.assertEqual(response.cookies[name]["samesite"], "Lax", name)
            self.assertEqual(response.cookies[name]["path"], "/", name)

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_behind_a_tls_terminating_proxy_the_cookies_are_secure(self):
        response = self.login(
            {"mb_id": "cookie_member", "mb_password": PASSWORD}, HTTP_X_FORWARDED_PROTO="https"
        )
        self.assertTrue(response.cookies["g5_token"]["secure"])

    def test_only_the_tokens_are_http_only(self):
        response = self.login({"mb_id": "cookie_member", "mb_password": PASSWORD, "auto_login": True})
        self.assertTrue(response.cookies["g5_token"]["httponly"])
        self.assertTrue(response.cookies["g5_refresh"]["httponly"])
        self.assertFalse(response.cookies["g5_auth_hint"]["httponly"])
        self.assertFalse(response.cookies["g5_auto_login"]["httponly"])

    def test_the_hint_cookies_never_carry_a_token(self):
        response = self.login({"mb_id": "cookie_member", "mb_password": PASSWORD, "auto_login": True})
        data = response.json()["data"]
        for name in ("g5_auth_hint", "g5_auto_login"):
            self.assertEqual(response.cookies[name].value, "1")
            self.assertNotIn(data["token"], response.cookies[name].value)

    def test_logout_deletes_the_cookies_with_the_path_and_samesite_they_were_set_with(self):
        response = APIClient().post(LOGOUT_URL, {}, format="json")
        for name in AUTH_COOKIES:
            self.assertEqual(response.cookies[name]["path"], "/", name)
            self.assertEqual(response.cookies[name]["samesite"], "Lax", name)
            self.assertEqual(int(response.cookies[name]["max-age"]), 0, name)

    def test_logout_is_post_only(self):
        self.assertEqual(APIClient().get(LOGOUT_URL).status_code, 405)

    def test_the_cookie_alone_authenticates_me_and_a_garbage_cookie_does_not(self):
        data = self.login({"mb_id": "cookie_member", "mb_password": PASSWORD}).json()["data"]
        client = APIClient()
        client.cookies["g5_token"] = data["token"]
        self.assertEqual(client.get(ME_URL).status_code, 200)
        client.cookies["g5_token"] = "garbage.token.value"
        self.assertEqual(client.get(ME_URL).status_code, 401)


class RegisterInputTests(AuthTestBase):
    def test_a_registration_cannot_choose_its_level_or_staff_flags(self):
        response = self.register(mb_level=10, is_staff=True, is_superuser=True, mb_point=99999, user_level=10)
        self.assertEqual(response.status_code, 201, response.content[:200])
        user = self.user_model.objects.get(username="reg_member")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(Profile.objects.get(user=user).user_level, 2)
        self.assertNotEqual(Profile.objects.get(user=user).user_point, 99999)
        self.assertFalse(response.json()["data"]["is_super_admin"])

    def test_ids_of_the_wrong_length_or_alphabet_are_refused(self):
        for bad in ("ab", "a" * 21, "has space", "hy-phen", "dot.id", "한글아이디", "１２３４", "a@b", "x';--"):
            cache.clear()  # registration is limited to five a minute
            response = self.register(mb_id=bad)
            self.assertEqual(response.status_code, 422, bad)
            self.assertIn("mb_id", response.json()["errors"], bad)
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_an_id_that_differs_only_in_case_is_taken(self):
        self.make_member("Case_Taken")
        response = self.register(mb_id="case_taken", mb_email="other@example.test", mb_nick="other-nick")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_id", response.json()["errors"])

    def test_an_e_mail_that_differs_only_in_case_is_taken(self):
        self.make_member("mail_taken")
        response = self.register(mb_email="MAIL_TAKEN@EXAMPLE.TEST")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])

    def test_a_trailing_newline_does_not_sneak_past_the_id_rule(self):
        response = self.register(mb_id="reg_member\n")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.user_model.objects.get(email="reg-member@example.test").username, "reg_member")

    def test_a_registration_with_an_unknown_pair_of_fields_ignores_them(self):
        response = self.register(unexpected={"nested": [1, 2]}, mb_open=0)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Profile.objects.get(user__username="reg_member").open_profile)

    def test_a_body_that_is_not_an_object_is_a_validation_error(self):
        for body in ([], "text", None):
            response = APIClient().post(REGISTER_URL, body, format="json")
            self.assertEqual(response.status_code, 422, body)

    def test_a_registration_race_that_hits_the_unique_constraint_is_a_conflict(self):
        with mock.patch.object(self.user_model.objects, "create_user", side_effect=IntegrityError("dup")):
            response = self.register()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "member_conflict")

    def test_a_failed_registration_leaves_no_member_behind(self):
        with mock.patch.object(v1_auth.point_ledger, "insert_point", side_effect=IntegrityError("boom")):
            response = self.register()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_the_registration_point_is_granted_once(self):
        self.set_config("cf_register_point", "1000")
        self.register()
        user = self.user_model.objects.get(username="reg_member")
        self.assertEqual(User_Point.objects.filter(user=user, po_rel_table="@member").count(), 1)
        self.assertEqual(Profile.objects.get(user=user).user_point, 1000)

    def test_the_cookies_of_a_new_member_are_session_cookies(self):
        response = self.register()
        self.assertTrue(response.cookies["g5_token"]["httponly"])
        self.assertEqual(response.cookies["g5_refresh"]["max-age"], "")

    # A number or list in a text field (mb_id, mb_email, mb_name, mb_nick) is a 422, never a 500.
    def test_a_json_number_in_a_text_field_is_refused_not_a_server_error(self):
        for field in ("mb_id", "mb_email", "mb_name", "mb_nick"):
            cache.clear()
            response = self.register(**{field: 12345})
            self.assertEqual(response.status_code, 422, field)
        for field in ("mb_id", "mb_email"):
            cache.clear()
            response = self.register(**{field: ["a", "b"]})
            self.assertEqual(response.status_code, 422, field)

    # valid_mb_email (lib/register.lib.php) needs name@domain.tld; the port uses Django's validate_email.
    def test_an_e_mail_address_without_a_domain_is_refused(self):
        for bad in ("a@", "@b", "x@y", "two words@example.test", "a@@example.test"):
            response = self.register(mb_email=bad)
            self.assertEqual(response.status_code, 422, bad)
            self.assertIn("mb_email", response.json()["errors"], bad)

    # No header injection through the certify mail: an address with a line break is refused before the
    # member row is written.
    def test_an_e_mail_address_with_a_line_break_is_refused_before_the_member_is_created(self):
        self.set_config("cf_use_email_certify", "1")
        response = self.register(mb_email="victim@example.test\nBcc: attacker@example.test")
        self.assertEqual(response.status_code, 422, response.content[:200])
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())
        self.assertEqual(len(mail.outbox), 0)

    # The nickname rules of register_form_update.php are shared with the profile update
    # (auth_common.nickname_rule_error): no markup characters, no more than the column length.
    def test_a_nickname_with_markup_is_refused(self):
        response = self.register(mb_nick="<script>alert(1)</script>")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_nick", response.json()["errors"])

    def test_a_nickname_longer_than_the_column_is_refused(self):
        response = self.register(mb_nick="n" * 101)
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_nick", response.json()["errors"])

    # cf_prohibit_id (reserve_mb_id / reserve_mb_nick, lib/register.lib.php:44-91) bars ids and nicknames.
    def test_a_reserved_word_cannot_be_used_as_an_id(self):
        self.set_config("cf_prohibit_id", "admin,administrator,webmaster,root")
        for reserved in ("admin", "Administrator", "ROOT"):
            response = self.register(mb_id=reserved, mb_email=f"{reserved}@example.test", mb_nick=f"n-{reserved}")
            self.assertEqual(response.status_code, 422, reserved)
            self.assertIn("mb_id", response.json()["errors"], reserved)

    def test_a_reserved_word_cannot_be_used_as_a_nickname(self):
        self.set_config("cf_prohibit_id", "admin,administrator,webmaster,root")
        response = self.register(mb_nick="administrator")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_nick", response.json()["errors"])

    # cf_prohibit_email (prohibit_mb_email, lib/register.lib.php:113-126) bars e-mail domains.
    def test_an_e_mail_domain_on_the_prohibited_list_is_refused(self):
        self.set_config("cf_prohibit_email", "hotmail.com\nSpam.Example")
        for domain in ("hotmail.com", "SPAM.example"):
            response = self.register(mb_email=f"someone@{domain}")
            self.assertEqual(response.status_code, 422, domain)
            self.assertIn("mb_email", response.json()["errors"], domain)
        self.assertEqual(response.json()["errors"]["mb_email"], "SPAM.example 메일은 사용할 수 없습니다.")
        self.assertFalse(self.user_model.objects.filter(username="reg_member").exists())

    def test_reserved_words_match_whole_list_entries_only(self):
        self.set_config("cf_prohibit_id", "admin, root\nwebmaster")
        response = self.register(mb_id="min_user", mb_nick="adminfan")
        self.assertEqual(response.status_code, 201, response.content[:300])
        cache.clear()
        refused = self.register(mb_id="webmaster", mb_email="w@example.test", mb_nick="w-nick")
        self.assertEqual(refused.json()["errors"]["mb_id"], "이미 예약된 단어로 사용할 수 없는 회원아이디 입니다.")

    def test_a_list_or_object_as_the_nickname_or_name_is_refused(self):
        for field, value in (("mb_nick", ["a"]), ("mb_name", {"a": 1}), ("mb_password", 12345678), ("social_signup_ticket", ["t"])):
            cache.clear()
            response = self.register(**{field: value})
            self.assertEqual(response.status_code, 422, field)
            self.assertIn(field, response.json()["errors"], field)

    def test_markup_in_the_name_is_dropped_as_clean_xss_tags_does(self):
        response = self.register(mb_name="<b>Reg</b> Member")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Profile.objects.get(user__username="reg_member").realname, "Reg Member")

    def test_the_availability_checks_apply_the_reserved_and_prohibited_lists(self):
        self.set_config("cf_prohibit_id", "admin")
        self.set_config("cf_prohibit_email", "hotmail.com")
        check_id = APIClient().get("/api/v1/auth/check-id", {"mb_id": "Admin"}).json()["data"]
        self.assertFalse(check_id["available"])
        self.assertEqual(check_id["message"], "이미 예약된 단어로 사용할 수 없는 회원아이디 입니다.")
        check_mail = APIClient().get("/api/v1/auth/check-email", {"mb_email": "x@hotmail.com"}).json()["data"]
        self.assertFalse(check_mail["available"])
        self.assertEqual(check_mail["message"], "hotmail.com 메일은 사용할 수 없습니다.")
        bad_mail = APIClient().get("/api/v1/auth/check-email", {"mb_email": "x@y"}).json()["data"]
        self.assertFalse(bad_mail["available"])


class LoginAutoLoginFlagTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.make_member("flag_member")

    def test_only_a_truthy_auto_login_keeps_the_login(self):
        for value, expected in (("false", 0), ("", 0), (0, 0), (False, 0), ("1", 1), ("on", 1), (True, 1)):
            cache.clear()
            response = APIClient().post(
                LOGIN_URL, {"mb_id": "flag_member", "mb_password": PASSWORD, "auto_login": value}, format="json"
            )
            self.assertEqual(response.status_code, 200, value)
            self.assertEqual(response.json()["data"]["auto_login"], expected, value)


class TokenRefreshTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("refresh_member")

    def tokens(self):
        return self.login({"mb_id": "refresh_member", "mb_password": PASSWORD}).json()["data"]

    def refresh(self, payload=None, client=None):
        return (client or APIClient()).post(REFRESH_URL, payload or {}, format="json")

    def test_refreshing_burns_the_old_refresh_token_and_issues_a_working_new_one(self):
        old = self.tokens()["refresh_token"]
        old_jti = RefreshToken(old)["jti"]
        fresh = self.refresh({"refresh_token": old})
        self.assertEqual(fresh.status_code, 200, fresh.content[:200])
        self.assertNotEqual(fresh.json()["data"]["refresh_token"], old)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=old_jti).exists())
        self.assertEqual(self.refresh({"refresh_token": old}).status_code, 401)
        self.assertEqual(self.refresh({"refresh_token": fresh.json()["data"]["refresh_token"]}).status_code, 200)

    def test_a_replayed_refresh_token_is_refused_and_clears_the_cookies(self):
        old = self.tokens()["refresh_token"]
        self.refresh({"refresh_token": old})
        replay = self.refresh({"refresh_token": old})
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json()["code"], "invalid_refresh")
        for name in AUTH_COOKIES:
            self.assertEqual(int(replay.cookies[name]["max-age"]), 0, name)

    def test_refresh_rotation_revokes_the_old_access_token_with_its_refresh_session(self):
        data = self.tokens()
        fresh = self.refresh({"refresh_token": data["refresh_token"]}).json()["data"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh['token']}")
        self.assertEqual(client.get(ME_URL).status_code, 200)
        old_client = APIClient()
        old_client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['token']}")
        self.assertEqual(old_client.get(ME_URL).status_code, 401)

    def test_the_refresh_cookie_is_rotated_and_stays_http_only(self):
        data = self.tokens()
        client = APIClient()
        client.cookies["g5_refresh"] = data["refresh_token"]
        response = self.refresh(client=client)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.cookies["g5_refresh"].value, data["refresh_token"])
        self.assertTrue(response.cookies["g5_refresh"]["httponly"])
        self.assertTrue(response.cookies["g5_token"]["httponly"])

    def test_a_member_who_asked_to_stay_signed_in_keeps_the_thirty_day_cookies_when_refreshing(self):
        data = self.login({"mb_id": "refresh_member", "mb_password": PASSWORD, "auto_login": True}).json()["data"]
        client = APIClient()
        client.cookies["g5_refresh"] = data["refresh_token"]
        client.cookies["g5_auto_login"] = "1"
        response = self.refresh(client=client)
        self.assertEqual(int(response.cookies["g5_refresh"]["max-age"]), 30 * 24 * 60 * 60)

    def test_the_body_token_wins_over_the_cookie(self):
        body_token = self.tokens()["refresh_token"]
        client = APIClient()
        client.cookies["g5_refresh"] = "garbage"
        self.assertEqual(self.refresh({"refresh": body_token}, client=client).status_code, 200)

    def test_tokens_of_other_shapes_are_refused_not_a_server_error(self):
        for value in ({"a": 1}, 12345, ["x"], "a.b.c", "x" * 5000, "\u0000"):
            response = self.refresh({"refresh_token": value})
            self.assertEqual(response.status_code, 401, repr(value)[:40])

    def test_a_token_signed_with_another_key_is_refused(self):
        forged = RefreshToken.for_user(self.member)
        raw = str(forged)
        head, payload, _signature = raw.split(".")
        self.assertEqual(self.refresh({"refresh_token": f"{head}.{payload}.AAAA"}).status_code, 401)

    def test_an_unsigned_none_algorithm_token_is_refused(self):
        import base64

        def part(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

        token = RefreshToken.for_user(self.member)
        forged = f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(token.payload)}."
        self.assertEqual(self.refresh({"refresh_token": forged}).status_code, 401)

    def test_a_refresh_token_naming_a_member_who_is_gone_is_refused(self):
        token = str(RefreshToken.for_user(self.member))
        self.user_model.objects.filter(pk=self.member.pk).delete()
        self.assertEqual(self.refresh({"refresh_token": token}).status_code, 401)

    def test_a_member_whose_address_is_not_certified_cannot_refresh(self):
        data = self.tokens()
        self.set_config("cf_use_email_certify", "1")
        Profile.objects.filter(user=self.member).update(email_certify=None)
        response = self.refresh({"refresh_token": data["refresh_token"]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "email_not_certified")
        self.assertEqual(int(response.cookies["g5_token"]["max-age"]), 0)

    def test_the_access_token_of_a_member_whose_address_is_not_certified_stops_working(self):
        data = self.tokens()
        self.set_config("cf_use_email_certify", "1")
        Profile.objects.filter(user=self.member).update(email_certify=None)
        client = APIClient()
        client.cookies["g5_token"] = data["token"]
        self.assertEqual(client.get(ME_URL).status_code, 401)

    def test_without_rotation_the_same_refresh_token_keeps_working(self):
        config = {**settings.SIMPLE_JWT, "ROTATE_REFRESH_TOKENS": False}
        old = self.tokens()["refresh_token"]
        with override_settings(SIMPLE_JWT=config):
            first = self.refresh({"refresh_token": old})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["data"]["refresh_token"], old)

    def test_rotation_without_blacklisting_leaves_the_old_token_valid(self):
        config = {**settings.SIMPLE_JWT, "ROTATE_REFRESH_TOKENS": True, "BLACKLIST_AFTER_ROTATION": False}
        old = self.tokens()["refresh_token"]
        with override_settings(SIMPLE_JWT=config):
            first = self.refresh({"refresh_token": old})
            self.assertNotEqual(first.json()["data"]["refresh_token"], old)
            self.assertEqual(self.refresh({"refresh_token": old}).status_code, 200)

    def test_a_token_that_cannot_be_blacklisted_is_still_rotated(self):
        old = self.tokens()["refresh_token"]
        with mock.patch.object(RefreshToken, "blacklist", side_effect=AttributeError):
            response = self.refresh({"refresh_token": old})
        self.assertEqual(response.status_code, 200)

    def test_changing_the_password_burns_every_outstanding_refresh_token(self):
        first = self.tokens()["refresh_token"]
        second = self.tokens()["refresh_token"]
        v1_auth.revoke_refresh_tokens(self.member)
        for token in (first, second):
            self.assertEqual(self.refresh({"refresh_token": token}).status_code, 401)
        self.assertEqual(OutstandingToken.objects.filter(user=self.member, blacklistedtoken__isnull=True).count(), 0)

    def test_a_reissue_after_a_revocation_hands_the_client_a_working_pair(self):
        old = self.tokens()["refresh_token"]
        v1_auth.revoke_refresh_tokens(self.member)
        request = mock.Mock()
        request.is_secure.return_value = False
        request.build_absolute_uri.side_effect = lambda path: f"http://testserver{path}"
        response = mock.Mock()
        payload = v1_auth.reissue_auth(response, self.member, request)
        self.assertEqual(self.refresh({"refresh_token": payload["refresh_token"]}).status_code, 200)
        self.assertEqual(self.refresh({"refresh_token": old}).status_code, 401)
        self.assertTrue(response.set_cookie.called)


class LogoutTests(AuthTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("logout_member")
        self.data = self.login({"mb_id": "logout_member", "mb_password": PASSWORD}).json()["data"]

    def test_logging_out_burns_the_refresh_token_from_the_cookie(self):
        client = APIClient()
        client.cookies["g5_refresh"] = self.data["refresh_token"]
        self.assertEqual(client.post(LOGOUT_URL, {}, format="json").status_code, 200)
        self.assertEqual(APIClient().post(REFRESH_URL, {"refresh_token": self.data["refresh_token"]}, format="json").status_code, 401)

    def test_logging_out_burns_only_the_given_device(self):
        other = self.login({"mb_id": "logout_member", "mb_password": PASSWORD}).json()["data"]
        APIClient().post(LOGOUT_URL, {"refresh_token": self.data["refresh_token"]}, format="json")
        self.assertEqual(APIClient().post(REFRESH_URL, {"refresh_token": other["refresh_token"]}, format="json").status_code, 200)

    def test_logging_out_twice_is_harmless(self):
        for _ in range(2):
            response = APIClient().post(LOGOUT_URL, {"refresh_token": self.data["refresh_token"]}, format="json")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["data"]["logged_out"])

    def test_logging_out_with_an_access_token_in_the_refresh_field_burns_nothing(self):
        response = APIClient().post(LOGOUT_URL, {"refresh_token": self.data["token"]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BlacklistedToken.objects.count(), 0)
        self.assertEqual(APIClient().post(REFRESH_URL, {"refresh_token": self.data["refresh_token"]}, format="json").status_code, 200)

    def test_logging_out_ignores_a_body_that_is_not_an_object(self):
        self.assertEqual(APIClient().post(LOGOUT_URL, ["x"], format="json").status_code, 200)

    def test_logging_out_does_not_need_a_valid_session_and_never_answers_with_a_redirect(self):
        response = APIClient().post(LOGOUT_URL, {"next": "https://evil.example/", "url": "https://evil.example/"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        self.assertNotIn("evil.example", response.content.decode())

    def test_login_never_answers_with_a_redirect_to_a_caller_supplied_address(self):
        response = self.login({"mb_id": "logout_member", "mb_password": PASSWORD, "next": "https://evil.example/", "url": "//evil.example"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        self.assertNotIn("evil.example", response.content.decode())


class SessionEndpointTests(AuthTestBase):
    def test_the_session_list_names_and_can_revoke_the_current_browser(self):
        member = self.make_member("sess_member")
        client = APIClient()
        login = self.login(
            {"mb_id": "sess_member", "mb_password": PASSWORD},
            client=client,
            HTTP_USER_AGENT="UnitTest/1.0",
        )
        self.assertEqual(login.status_code, 200, login.content[:200])
        listing = client.get("/api/v1/auth/sessions").json()["data"]["sessions"]
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["user_agent"], "UnitTest/1.0")
        revoke = client.post(
            "/api/v1/auth/sessions/revoke", {"token_id": listing[0]["token_id"]}, format="json"
        )
        self.assertEqual(revoke.status_code, 200, revoke.content[:200])
        self.assertTrue(revoke.json()["data"]["revoked"])
        self.assertTrue(revoke.json()["data"]["current"])

    def test_the_session_endpoints_refuse_a_member_awaiting_certification(self):
        member = self.make_member("sess_pending")
        self.set_config("cf_use_email_certify", "1")
        Profile.objects.filter(user=member).update(email_certify=None)
        client = APIClient()
        client.force_authenticate(user=member)
        self.assertEqual(client.get("/api/v1/auth/sessions").status_code, 401)
        self.assertEqual(client.post("/api/v1/auth/sessions/revoke", {}, format="json").status_code, 401)
        self.assertEqual(client.get(ME_URL).status_code, 401)

    def test_the_session_revoke_needs_a_member(self):
        self.assertEqual(APIClient().post("/api/v1/auth/sessions/revoke", {}, format="json").status_code, 401)

    def test_me_grants_the_daily_login_point_once_however_often_it_is_called(self):
        member = self.make_member("me_points")
        self.set_config("cf_login_point", "5")
        client = APIClient()
        client.force_authenticate(user=member)
        for _ in range(3):
            self.assertEqual(client.get(ME_URL).status_code, 200)
        self.assertEqual(User_Point.objects.filter(user=member, po_rel_table="@login").count(), 1)

    def test_me_does_not_return_the_password_hash_or_staff_secrets(self):
        member = self.make_member("me_clean")
        client = APIClient()
        client.force_authenticate(user=member)
        body = client.get(ME_URL).content.decode()
        self.assertNotIn(member.password, body)
        self.assertNotIn("pbkdf2", body)

    def test_the_access_token_of_a_member_blocked_after_login_stops_working(self):
        member = self.make_member("me_blocked")
        token = str(RefreshToken.for_user(member).access_token)
        self.user_model.objects.filter(pk=member.pk).update(is_active=False)
        client = APIClient()
        client.cookies["g5_token"] = token
        self.assertEqual(client.get(ME_URL).status_code, 401)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get(ME_URL).status_code, 401)


class LoginThrottleTests(AuthTestBase):
    def test_link_existing_shares_the_login_rate_limit(self):
        client = APIClient()
        session = client.session
        ticket, _ = v1_auth._create_social_ticket(
            {"provider": "kakao", "provider_label": "Kakao", "provider_user_id": "k-throttle"}, kind="signup", session=session
        )
        session.save()
        codes = [
            client.post(LINK_URL, {"ticket": ticket, "mb_id": "nobody", "password": "x" * 10}, format="json").status_code
            for _ in range(11)
        ]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10], 429)

    def test_guessing_passwords_for_one_member_is_stopped_after_ten_tries(self):
        self.make_member("guess_target")
        codes = [self.login({"mb_id": "guess_target", "mb_password": f"guess-{i}"}).status_code for i in range(12)]
        self.assertEqual(codes[10:], [429, 429])
        self.assertEqual(self.login({"mb_id": "guess_target", "mb_password": PASSWORD}).status_code, 429)


def query_of(url):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query, keep_blank_values=True).items()}


class SocialFlowBase(AuthTestBase):
    PROFILE = {
        "provider": "kakao",
        "provider_label": "Kakao",
        "provider_user_id": "4242",
        "email": "k@example.test",
        "name": "Kim",
        "nickname": "KakaoNick",
    }

    def begin(self, client, provider="kakao", mode="login", redirect=None):
        params = {"provider": provider}
        if redirect is not None:
            params["redirect"] = redirect
        response = client.get(SIGNUP_START_URL if mode == "signup" else START_URL, params)
        self.assertEqual(response.status_code, 302, response.content[:200])
        return query_of(response["Location"]).get("state", ""), response

    def callback(self, client, state, **extra):
        params = {"state": state, "code": "auth-code"}
        params.update(extra)
        return client.get(CALLBACK_URL, params)

    def provider_http(self, provider="kakao", userinfo=None, token=None):
        spec = v1_auth.SOCIAL_PROVIDER_SPECS[provider]

        def fake(url, **kwargs):
            if url == spec["token_url"]:
                return token if token is not None else {"access_token": "at-123"}
            return userinfo if userinfo is not None else USERINFO[provider]

        return mock.patch(HTTP_PATCH, side_effect=fake)

    @property
    def social_client(self):
        """The browser the directly made tickets belong to (a ticket only works in the browser that
        started the social login)."""
        if not hasattr(self, "_social_client"):
            self._social_client = APIClient()
        return self._social_client

    def bound_request(self):
        return SimpleNamespace(session=self.social_client.session, method="GET", query_params={})

    def make_ticket(self, kind, user=None, **profile):
        base = dict(self.PROFILE)
        base.update(profile)
        session = self.social_client.session
        ticket, _ = v1_auth._create_social_ticket(base, kind=kind, user=user, session=session)
        session.save()
        return ticket

    def link(self, user, **profile):
        base = dict(self.PROFILE)
        base.update(profile)
        v1_auth._link_social_identity(user, base)


@override_settings(**SOCIAL_SETTINGS)
class SocialStartTests(SocialFlowBase):
    def test_start_sends_the_browser_to_the_provider_with_a_fresh_state(self):
        client = APIClient()
        state, response = self.begin(client)
        url = urlparse(response["Location"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", "https://kauth.kakao.com/oauth/authorize")
        params = query_of(response["Location"])
        self.assertEqual(params["client_id"], "kakao-key")
        self.assertEqual(params["response_type"], "code")
        self.assertEqual(params["redirect_uri"], "http://testserver/api/social/callback.php")
        self.assertGreaterEqual(len(state), 20)
        other_state, _ = self.begin(client)
        self.assertNotEqual(state, other_state)
        self.assertIn("no-store", response["Cache-Control"])

    def test_the_state_is_kept_in_the_session_of_the_browser_that_started(self):
        client = APIClient()
        state, _ = self.begin(client, redirect="/mypage")
        stored = client.session[f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"]
        self.assertEqual(stored["provider"], "kakao")
        self.assertEqual(stored["mode"], "login")
        self.assertEqual(stored["redirect"], "http://testserver/mypage")
        self.assertEqual(stored["redirect_uri"], "http://testserver/api/social/callback.php")

    def test_no_provider_secret_ever_reaches_the_browser(self):
        for provider in v1_auth.SOCIAL_PROVIDER_SPECS:
            _state, response = self.begin(APIClient(), provider=provider)
            self.assertNotIn("-secret", response["Location"], provider)

    def test_each_provider_gets_its_own_authorize_endpoint_and_parameters(self):
        expected_host = {
            "naver": "nid.naver.com",
            "kakao": "kauth.kakao.com",
            "google": "accounts.google.com",
            "facebook": "www.facebook.com",
            "twitter": "x.com",
            "payco": "id.payco.com",
        }
        for provider, host in expected_host.items():
            _state, response = self.begin(APIClient(), provider=provider)
            self.assertEqual(urlparse(response["Location"]).netloc, host, provider)
        google = query_of(self.begin(APIClient(), provider="google")[1]["Location"])
        self.assertEqual(google["prompt"], "select_account")
        self.assertIn("email", google["scope"])
        payco = query_of(self.begin(APIClient(), provider="payco")[1]["Location"])
        self.assertEqual(payco["serviceProviderCode"], "FRIENDS")
        self.assertEqual(payco["userLocale"], "ko_KR")

    def test_twitter_gets_a_pkce_challenge_that_matches_the_verifier_kept_server_side(self):
        client = APIClient()
        state, response = self.begin(client, provider="twitter")
        params = query_of(response["Location"])
        verifier = client.session[f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"]["code_verifier"]
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["code_challenge"], v1_auth._social_pkce_challenge(verifier))
        self.assertNotIn(verifier, response["Location"])
        self.assertGreaterEqual(len(verifier), 43)

    def test_only_twitter_keeps_a_pkce_verifier(self):
        client = APIClient()
        state, _ = self.begin(client, provider="google")
        self.assertNotIn("code_verifier", client.session[f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"])

    def test_the_signup_start_remembers_the_signup_mode_and_defaults_to_the_register_page(self):
        client = APIClient()
        state, _ = self.begin(client, mode="signup")
        stored = client.session[f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"]
        self.assertEqual(stored["mode"], "signup")
        self.assertEqual(stored["redirect"], "http://testserver/register")

    def test_an_unknown_or_missing_provider_goes_back_with_an_error(self):
        for params in ({}, {"provider": "myspace"}, {"provider": "../kakao"}, {"provider": "kakao\x00"}):
            response = APIClient().get(START_URL, params)
            self.assertEqual(response.status_code, 302, params)
            self.assertEqual(query_of(response["Location"])["error"], "social_disabled", params)

    def test_a_provider_missing_its_secret_or_service_code_cannot_start(self):
        with override_settings(SOCIAL_NAVER_CLIENT_SECRET="", SOCIAL_PAYCO_SERVICE_PROVIDER_CODE=""):
            for provider in ("naver", "payco"):
                response = APIClient().get(START_URL, {"provider": provider})
                self.assertEqual(query_of(response["Location"])["error"], "social_disabled", provider)

    def test_starting_stores_nothing_but_the_state_in_the_visitors_own_session(self):
        before = Config.objects.count()
        self.begin(APIClient())
        self.assertEqual(Config.objects.count(), before)


@override_settings(**SOCIAL_SETTINGS)
class SocialRedirectSafetyTests(SocialFlowBase):
    """Where the browser is sent back to. The disabled provider path answers at once, so the redirect
    target is visible without a provider round trip."""

    def back_to(self, value, **settings_kwargs):
        with override_settings(SOCIAL_KAKAO_REST_KEY="", **settings_kwargs):
            response = APIClient().get(START_URL, {"provider": "kakao", "redirect": value})
        self.assertEqual(response.status_code, 302)
        return response["Location"]

    def test_a_relative_path_stays_on_this_site(self):
        self.assertEqual(self.back_to("/mypage?tab=1"), "http://testserver/mypage?tab=1&error=social_disabled")

    def test_no_redirect_falls_back_to_the_social_callback_page(self):
        self.assertEqual(self.back_to(""), "http://testserver/login/social-callback?error=social_disabled")

    def test_addresses_on_other_hosts_or_with_odd_schemes_fall_back_to_this_site(self):
        for target in (
            "https://evil.example/x",
            "http://evil.example",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "ftp://testserver/x",
            "https:///evil.example",
            "https:evil.example",
            "http://testserver.evil.example/",
            "http://testserver@evil.example/",
            "http://[::1]/x",
            "http://127.evil.example/",
        ):
            location = self.back_to(target)
            self.assertEqual(urlparse(location).netloc, "testserver", target)
            self.assertNotIn("evil", location, target)

    def test_a_backslash_in_the_user_info_falls_back_because_a_browser_could_read_it_as_a_slash(self):
        # url_has_allowed_host_and_scheme reads "\" as "/", so the host would be evil.example: refused.
        location = self.back_to("http://evil.example\\@testserver/x")
        self.assertNotIn("\\", location)
        self.assertEqual(location, "http://testserver/login/social-callback?error=social_disabled")

    def test_a_malformed_address_falls_back_instead_of_failing(self):
        for target in ("http://[bad", "http://host:notaport/", "https://exa mple.com", "http://" + "a" * 5000):
            location = self.back_to(target)
            self.assertEqual(urlparse(location).netloc, "testserver", target[:30])

    def test_line_breaks_in_the_target_never_reach_the_location_header(self):
        location = self.back_to("/ok\r\nSet-Cookie: injected=1")
        self.assertNotIn("\r", location)
        self.assertNotIn("\n", location)

    def test_a_configured_front_end_origin_is_accepted(self):
        location = self.back_to("https://app.example/cb?x=1", SOCIAL_ALLOWED_REDIRECT_ORIGINS=["https://app.example"])
        self.assertEqual(location, "https://app.example/cb?x=1&error=social_disabled")

    def test_the_front_end_origin_from_the_app_base_url_is_accepted(self):
        location = self.back_to("https://front.example:8443/cb", SOCIAL_APP_BASE_URL="https://front.example:8443/app")
        self.assertTrue(location.startswith("https://front.example:8443/cb?"), location)

    def test_a_configured_origin_does_not_accept_its_lookalikes(self):
        for target in ("https://app.example.evil.example/", "https://app.example@evil.example/", "http://app.example/", "https://app.example:444/"):
            location = self.back_to(target, SOCIAL_ALLOWED_REDIRECT_ORIGINS=["https://app.example"])
            self.assertEqual(urlparse(location).netloc, "testserver", target)

    def test_loopback_front_ends_are_accepted_only_while_debugging(self):
        self.assertEqual(urlparse(self.back_to("http://localhost:3000/cb")).netloc, "testserver")
        self.assertEqual(urlparse(self.back_to("http://localhost:3000/cb", DEBUG=True)).netloc, "localhost:3000")
        self.assertEqual(urlparse(self.back_to("http://127.0.0.1:3000/cb", DEBUG=True)).netloc, "127.0.0.1:3000")
        self.assertEqual(urlparse(self.back_to("http://127.evil.example/cb", DEBUG=True)).netloc, "testserver")

    # A protocol-relative address ("//host/x", or "/\host/x" which browsers read the same way) is not a
    # path on this site, so start.php/signup.php are no open redirect.
    def test_a_protocol_relative_address_does_not_leave_the_site(self):
        for target in ("//evil.example/x", "///evil.example/x", "//evil.example\\@testserver", "/\\evil.example/x", "//testserver.evil.example/"):
            location = self.back_to(target)
            self.assertEqual(urlparse(location).netloc, "testserver", target)
            self.assertNotIn("evil", location, target)

    def test_control_characters_anywhere_in_the_target_fall_back(self):
        for target in ("/ok\x00/x", "/ok\tx", "\x7f/ok", "https://testserver/a\x0bb"):
            self.assertEqual(self.back_to(target), "http://testserver/login/social-callback?error=social_disabled", repr(target))

    def test_the_redirect_is_checked_again_at_the_callback_so_a_login_ticket_never_follows_it_off_site(self):
        member = self.make_member("redirect_victim")
        self.link(member)
        client = APIClient()
        state, _ = self.begin(client, redirect="//evil.example/steal")
        with self.provider_http():
            response = self.callback(client, state)
        self.assertIn("ticket=", response["Location"])
        self.assertEqual(urlparse(response["Location"]).netloc, "testserver", response["Location"])

    def test_the_query_helper_keeps_existing_parameters_and_skips_empty_values(self):
        url = v1_auth._append_query("https://x.example/p?a=1&b=2&a=3", {"b": "new", "c": "", "d": None, "e": 0})
        self.assertEqual(query_of(url), {"a": "3", "b": "new", "e": "0"})


@override_settings(**SOCIAL_SETTINGS)
class SocialCallbackTests(SocialFlowBase):
    def test_a_callback_without_a_known_state_is_refused(self):
        for params in ({}, {"code": "x"}, {"state": "forged", "code": "x"}, {"state": "é" * 300, "code": "x"}):
            response = APIClient().get(CALLBACK_URL, params)
            self.assertEqual(response.status_code, 302, params)
            self.assertEqual(query_of(response["Location"])["error"], "invalid_state", params)

    def test_a_state_started_in_another_browser_is_refused(self):
        attacker = APIClient()
        state, _ = self.begin(attacker)
        victim = APIClient()
        with self.provider_http() as http:
            response = self.callback(victim, state)
        self.assertEqual(query_of(response["Location"])["error"], "invalid_state")
        http.assert_not_called()
        self.assertFalse(Config.objects.filter(name__startswith=v1_auth.SOCIAL_TICKET_PREFIX).exists())

    def test_a_state_works_only_once(self):
        client = APIClient()
        state, _ = self.begin(client, mode="signup")
        with self.provider_http():
            first = self.callback(client, state)
            second = self.callback(client, state)
        self.assertIn("social_signup_ticket", first["Location"])
        self.assertEqual(query_of(second["Location"])["error"], "invalid_state")

    def test_a_failed_callback_also_uses_up_the_state(self):
        client = APIClient()
        state, _ = self.begin(client)
        first = client.get(CALLBACK_URL, {"state": state})
        self.assertEqual(query_of(first["Location"])["error"], "missing_code")
        with self.provider_http():
            second = self.callback(client, state)
        self.assertEqual(query_of(second["Location"])["error"], "invalid_state")

    def test_the_provider_may_report_a_refusal(self):
        client = APIClient()
        state, _ = self.begin(client, redirect="/back")
        response = client.get(CALLBACK_URL, {"state": state, "error": "access_denied"})
        self.assertTrue(response["Location"].startswith("http://testserver/back?"))
        self.assertEqual(query_of(response["Location"])["error"], "access_denied")

    def test_a_provider_error_text_cannot_inject_a_second_parameter_or_header(self):
        client = APIClient()
        state, _ = self.begin(client, redirect="/back")
        response = client.get(CALLBACK_URL, {"state": state, "error": "x&ticket=stolen\r\nSet-Cookie: a=b"})
        params = query_of(response["Location"])
        self.assertNotIn("ticket", params)
        self.assertNotIn("\n", response["Location"])

    def test_a_callback_without_a_code_goes_back_with_missing_code(self):
        client = APIClient()
        for code in ("", "   "):
            state, _ = self.begin(client)
            response = client.get(CALLBACK_URL, {"state": state, "code": code})
            self.assertEqual(query_of(response["Location"])["error"], "missing_code")

    def test_a_provider_switched_off_after_the_start_is_refused_at_the_callback(self):
        client = APIClient()
        state, _ = self.begin(client)
        with override_settings(SOCIAL_KAKAO_REST_KEY=""), self.provider_http() as http:
            response = self.callback(client, state)
        self.assertEqual(query_of(response["Location"])["error"], "social_disabled")
        http.assert_not_called()

    def test_a_state_naming_an_unknown_provider_is_refused(self):
        client = APIClient()
        state, _ = self.begin(client)
        session = client.session
        key = f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"
        session[key] = {**session[key], "provider": "myspace"}
        session.save()
        response = self.callback(client, state)
        self.assertEqual(query_of(response["Location"])["error"], "social_disabled")

    def test_the_finish_address_behaves_like_the_callback(self):
        client = APIClient()
        state, _ = self.begin(client)
        response = client.get("/api/social/finish.php", {"state": state})
        self.assertEqual(query_of(response["Location"])["error"], "missing_code")

    def test_a_linked_identity_comes_back_with_a_login_ticket_that_logs_in_once(self):
        member = self.make_member("callback_member")
        self.link(member)
        client = APIClient()
        state, _ = self.begin(client, redirect="/after")
        with self.provider_http():
            response = self.callback(client, state)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("http://testserver/after?"))
        ticket = query_of(response["Location"])["ticket"]
        exchange = client.post(EXCHANGE_URL, {"ticket": ticket}, format="json")
        self.assertEqual(exchange.status_code, 200, exchange.content[:200])
        self.assertEqual(exchange.json()["data"]["member"]["mb_id"], "callback_member")
        self.assertEqual(client.post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 404)

    def test_an_unlinked_identity_from_the_login_button_opens_the_signup_through_a_bridge_page(self):
        client = APIClient()
        state, _ = self.begin(client)
        with self.provider_http():
            response = self.callback(client, state)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("social_link_fn", body)
        self.assertIn('"kakao"', body)
        self.assertIn("social_signup_ticket=", body)
        self.assertNotIn("at-123", body)
        self.assertNotIn("auth-code", body)

    def test_an_unlinked_identity_from_the_signup_button_goes_to_the_register_page_with_a_ticket(self):
        client = APIClient()
        state, _ = self.begin(client, mode="signup")
        with self.provider_http():
            response = self.callback(client, state)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("http://testserver/register?"))
        ticket = query_of(response["Location"])["social_signup_ticket"]
        profile = client.get("/api/v1/auth/social/signup-profile", {"ticket": ticket}).json()["data"]
        self.assertEqual(profile["email"], "k@example.test")
        self.assertEqual(profile["suggested_mb_id"], "k_user")

    def test_the_login_ticket_goes_to_a_configured_front_end(self):
        member = self.make_member("front_member")
        self.link(member)
        client = APIClient()
        with override_settings(SOCIAL_ALLOWED_REDIRECT_ORIGINS=["https://app.example"]):
            state, _ = self.begin(client, redirect="https://app.example/login/done")
            with self.provider_http():
                response = self.callback(client, state)
        self.assertTrue(response["Location"].startswith("https://app.example/login/done?ticket="))

    def test_every_provider_exchanges_the_code_and_reads_the_profile(self):
        expected = {
            "naver": ("n-1", "n@example.test"),
            "kakao": ("4242", "k@example.test"),
            "google": ("g-1", "g@example.test"),
            "facebook": ("f-1", "f@example.test"),
            "twitter": ("t-1", "t@example.test"),
            "payco": ("p-1", "p@example.test"),
        }
        for provider, (user_id, email) in expected.items():
            client = APIClient()
            state, _ = self.begin(client, provider=provider, mode="signup")
            with self.provider_http(provider) as http:
                response = self.callback(client, state)
            ticket = query_of(response["Location"]).get("social_signup_ticket")
            self.assertTrue(ticket, f"{provider}: {response['Location']}")
            payload = v1_auth._load_social_ticket(ticket, expected_kind="signup")
            self.assertEqual(payload["provider"], provider)
            self.assertEqual(payload["provider_user_id"], user_id, provider)
            self.assertEqual(payload["email"], email, provider)
            token_call = http.call_args_list[0]
            self.assertEqual(token_call.args[0], v1_auth.SOCIAL_PROVIDER_SPECS[provider]["token_url"])
            self.assertEqual(token_call.kwargs["method"], "POST")
            self.assertEqual(token_call.kwargs["data"]["code"], "auth-code")
            info_call = http.call_args_list[1]
            if provider == "payco":
                self.assertEqual(info_call.kwargs["headers"]["access_token"], "at-123")
            else:
                self.assertEqual(info_call.kwargs["headers"]["Authorization"], "Bearer at-123")

    def test_the_token_request_carries_what_each_provider_asks_for(self):
        client = APIClient()
        state, _ = self.begin(client, provider="naver", mode="signup")
        with self.provider_http("naver") as http:
            self.callback(client, state)
        data = http.call_args_list[0].kwargs["data"]
        self.assertEqual((data["grant_type"], data["client_secret"], data["state"]), ("authorization_code", "naver-secret", state))

        client = APIClient()
        state, _ = self.begin(client, provider="kakao", mode="signup")
        with self.provider_http("kakao") as http:
            self.callback(client, state)
        data = http.call_args_list[0].kwargs["data"]
        self.assertEqual(data["redirect_uri"], "http://testserver/api/social/callback.php")
        self.assertNotIn("client_secret", data)

        client = APIClient()
        state, _ = self.begin(client, provider="facebook", mode="signup")
        with self.provider_http("facebook") as http:
            self.callback(client, state)
        data = http.call_args_list[0].kwargs["data"]
        self.assertEqual(data["client_secret"], "facebook-secret")
        self.assertNotIn("grant_type", data)
        self.assertIn("fields=", http.call_args_list[1].args[0])

    def test_kakao_sends_its_client_secret_when_one_is_configured(self):
        client = APIClient()
        state, _ = self.begin(client, provider="kakao", mode="signup")
        with override_settings(SOCIAL_KAKAO_CLIENT_SECRET="kakao-secret"), self.provider_http("kakao") as http:
            self.callback(client, state)
        self.assertEqual(http.call_args_list[0].kwargs["data"]["client_secret"], "kakao-secret")

    def test_twitter_proves_the_pkce_verifier_and_signs_with_basic_authorization(self):
        client = APIClient()
        state, _ = self.begin(client, provider="twitter", mode="signup")
        verifier = client.session[f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"]["code_verifier"]
        with self.provider_http("twitter") as http:
            self.callback(client, state)
        call = http.call_args_list[0]
        self.assertEqual(call.kwargs["data"]["code_verifier"], verifier)
        self.assertNotIn("client_id", call.kwargs["data"])
        self.assertTrue(call.kwargs["headers"]["Authorization"].startswith("Basic "))

    def test_twitter_without_a_stored_verifier_is_refused(self):
        client = APIClient()
        state, _ = self.begin(client, provider="twitter", mode="signup")
        session = client.session
        key = f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"
        session[key] = {name: value for name, value in session[key].items() if name != "code_verifier"}
        session.save()
        with self.provider_http("twitter"):
            response = self.callback(client, state)
        self.assertEqual(query_of(response["Location"])["error"], "invalid_state")

    def test_twitter_without_a_secret_uses_the_client_id_in_the_body(self):
        client = APIClient()
        with override_settings(SOCIAL_TWITTER_CLIENT_SECRET=""):
            state, _ = self.begin(client, provider="twitter", mode="signup")
            with self.provider_http("twitter") as http:
                self.callback(client, state)
        call = http.call_args_list[0]
        self.assertEqual(call.kwargs["data"]["client_id"], "twitter-id")
        self.assertNotIn("Authorization", call.kwargs["headers"])

    def test_provider_failures_come_back_as_an_error_and_create_nothing(self):
        failures = {
            "token request refused": {"side_effect": v1_auth.SocialOAuthError("no", status_code=400)},
            "no access token": {"return_value": {"error": "bad_code"}},
        }
        for name, kwargs in failures.items():
            client = APIClient()
            state, _ = self.begin(client, redirect="/back")
            with mock.patch(HTTP_PATCH, **kwargs):
                response = self.callback(client, state)
            self.assertEqual(query_of(response["Location"])["error"], "social_oauth_failed", name)
            self.assertNotIn("ticket", query_of(response["Location"]), name)
        self.assertFalse(Config.objects.filter(name__startswith=v1_auth.SOCIAL_TICKET_PREFIX).exists())

    def test_a_profile_without_a_user_id_is_refused(self):
        client = APIClient()
        state, _ = self.begin(client, redirect="/back")
        with self.provider_http("kakao", userinfo={"kakao_account": {"email": "k@example.test"}}):
            response = self.callback(client, state)
        self.assertEqual(query_of(response["Location"])["error"], "social_oauth_failed")

    def test_an_unexpected_shape_of_profile_is_refused_not_a_server_error(self):
        for provider in ("naver", "kakao", "google", "facebook", "twitter", "payco"):
            client = APIClient()
            state, _ = self.begin(client, provider=provider, redirect="/back")
            with self.provider_http(provider, userinfo={"data": "text", "response": None, "kakao_account": None, "picture": "x"}):
                response = self.callback(client, state)
            self.assertEqual(query_of(response["Location"])["error"], "social_oauth_failed", provider)

    def test_the_profile_values_are_trimmed_to_the_column_sizes(self):
        client = APIClient()
        state, _ = self.begin(client, provider="google", mode="signup")
        huge = {"sub": "s" * 400, "email": "e" * 400 + "@x.test", "name": "n" * 400, "picture": "p" * 900}
        with self.provider_http("google", userinfo=huge):
            response = self.callback(client, state)
        payload = v1_auth._load_social_ticket(query_of(response["Location"])["social_signup_ticket"], expected_kind="signup")
        self.assertEqual(len(payload["provider_user_id"]), 255)
        self.assertEqual(len(payload["email"]), 255)
        self.assertEqual(len(payload["name"]), 100)
        self.assertEqual(len(payload["photo_url"]), 500)

    # login_check.php:44 refuses a blocked member (mb_intercept_date). The identity of a member the site
    # blocked (is_active off) stays theirs: no login, no signup offer, and no other account takes it over.
    def test_a_blocked_members_social_identity_cannot_be_used_to_sign_up_again(self):
        blocked = self.make_member("blocked_social")
        self.link(blocked)
        self.user_model.objects.filter(pk=blocked.pk).update(is_active=False)
        client = APIClient()
        state, _ = self.begin(client)
        with self.provider_http():
            response = self.callback(client, state)
        text = response["Location"] if response.status_code == 302 else response.content.decode()
        self.assertNotIn("social_signup_ticket", text)

    def test_a_blocked_members_social_identity_is_refused_at_the_callback_without_a_ticket(self):
        blocked = self.make_member("blocked_cb")
        self.link(blocked)
        self.user_model.objects.filter(pk=blocked.pk).update(is_active=False)
        for mode in ("login", "signup"):
            client = APIClient()
            state, _ = self.begin(client, mode=mode, redirect="/back")
            with self.provider_http():
                response = self.callback(client, state)
            self.assertEqual(response.status_code, 302, mode)
            query = query_of(response["Location"])
            self.assertEqual(query["error"], "member_blocked", mode)
            self.assertNotIn("ticket", query, mode)
        self.assertFalse(Config.objects.filter(name__startswith=v1_auth.SOCIAL_TICKET_PREFIX).exists())

    def test_a_signup_ticket_cannot_take_over_the_identity_of_a_member_blocked_after_it_was_issued(self):
        ticket = self.make_ticket("signup")
        blocked = self.make_member("blocked_later")
        self.link(blocked)
        self.user_model.objects.filter(pk=blocked.pk).update(is_active=False)
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_id": "second_acct"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "already_linked")
        self.assertFalse(self.user_model.objects.filter(username="second_acct").exists())
        self.assertEqual(v1_auth._social_identity_owner("kakao", "4242"), blocked)

    def test_another_member_cannot_link_the_identity_of_a_blocked_member(self):
        blocked = self.make_member("blocked_link")
        self.link(blocked)
        self.user_model.objects.filter(pk=blocked.pk).update(is_active=False)
        self.make_member("link_taker")
        response = self.social_client.post(
            LINK_URL, {"ticket": self.make_ticket("signup"), "mb_id": "link_taker", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(v1_auth._social_identity_owner("kakao", "4242"), blocked)

    def test_a_state_older_than_the_ticket_lifetime_is_refused_before_the_provider_is_asked(self):
        client = APIClient()
        state, _ = self.begin(client)
        session = client.session
        key = f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"
        stored = session[key]
        stored["created_at"] = int(timezone.now().timestamp()) - v1_auth.SOCIAL_TICKET_TTL_SECONDS - 1
        session[key] = stored
        session.save()
        with self.provider_http() as http:
            response = self.callback(client, state)
        self.assertEqual(query_of(response["Location"])["error"], "invalid_state")
        http.assert_not_called()

    def test_a_state_just_inside_the_ticket_lifetime_still_works(self):
        client = APIClient()
        state, _ = self.begin(client, mode="signup")
        session = client.session
        key = f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"
        stored = session[key]
        stored["created_at"] = int(timezone.now().timestamp()) - v1_auth.SOCIAL_TICKET_TTL_SECONDS + 30
        session[key] = stored
        session.save()
        with self.provider_http():
            response = self.callback(client, state)
        self.assertIn("social_signup_ticket", response["Location"])

    def test_a_state_without_a_usable_start_time_is_refused(self):
        for created_at in (None, "soon", int(timezone.now().timestamp()) + 3600):
            client = APIClient()
            state, _ = self.begin(client)
            session = client.session
            key = f"{v1_auth.SOCIAL_STATE_SESSION_PREFIX}{state}"
            stored = session[key]
            stored["created_at"] = created_at
            session[key] = stored
            session.save()
            with self.provider_http() as http:
                response = self.callback(client, state)
            self.assertEqual(query_of(response["Location"])["error"], "invalid_state", created_at)
            http.assert_not_called()

    def test_registering_through_social_never_logs_into_the_member_who_owns_the_provider_e_mail(self):
        owner = self.user_model.objects.create_user(username="mail_owner", email="k@example.test", password=PASSWORD)
        ticket = self.make_ticket("signup")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])
        self.assertIsNone(v1_auth._social_identity_user("kakao", "4242"))
        self.assertTrue(self.user_model.objects.filter(pk=owner.pk).exists())


@override_settings(**SOCIAL_SETTINGS)
class SocialTicketAndSignupTests(SocialFlowBase):
    def test_tickets_of_odd_shapes_never_match(self):
        for ticket in ("", None, "a b", "../x", "a" * 81, "tick%et", "t\n", 12345, ["x"], {"a": 1}):
            self.assertIsNone(v1_auth._read_social_ticket(ticket, request=self.bound_request()), repr(ticket))

    def test_a_ticket_cannot_be_read_as_the_other_kind(self):
        ticket = self.make_ticket("signup")
        self.assertIsNone(v1_auth._read_social_ticket(ticket, request=self.bound_request(), expected_kind="login"))
        self.assertIsNotNone(v1_auth._read_social_ticket(ticket, request=self.bound_request(), expected_kind="signup"))

    def test_reading_with_consume_removes_the_ticket(self):
        ticket = self.make_ticket("signup")
        self.assertIsNotNone(v1_auth._read_social_ticket(ticket, request=self.bound_request(), consume=True))
        self.assertIsNone(v1_auth._read_social_ticket(ticket, request=self.bound_request()))

    def test_a_ticket_that_is_not_json_is_ignored(self):
        Config.objects.create(name=v1_auth._social_ticket_config_name("brokenticket"), value="{not json")
        self.assertIsNone(v1_auth._read_social_ticket("brokenticket", request=self.bound_request()))

    def test_the_signup_profile_of_an_expired_ticket_is_gone(self):
        ticket = self.make_ticket("signup")
        name = v1_auth._social_ticket_config_name(ticket)
        payload = json.loads(Config.objects.get(name=name).value)
        payload["expires_at"] = int(timezone.now().timestamp()) - 5
        Config.objects.filter(name=name).update(value=json.dumps(payload))
        self.assertEqual(self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": ticket}).status_code, 404)

    def test_the_signup_profile_never_shows_the_provider_user_id_or_the_ticket_internals(self):
        ticket = self.make_ticket("signup")
        body = self.social_client.get("/api/v1/auth/social/signup-profile", {"ticket": ticket}).content.decode()
        self.assertNotIn("4242", body)
        self.assertNotIn("expires_at", body)

    def test_a_social_signup_with_the_provider_e_mail_skips_the_certify_mail(self):
        self.set_config("cf_use_email_certify", "1")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": self.make_ticket("signup")}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:200])
        self.assertIn("token", response.json()["data"])
        self.assertIsNotNone(Profile.objects.get(user__username="k_user").email_certify)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_social_signup_with_an_e_mail_the_provider_did_not_vouch_for_must_be_certified(self):
        self.set_config("cf_use_email_certify", "1")
        response = self.social_client.post(
            REGISTER_URL,
            {"social_signup_ticket": self.make_ticket("signup"), "mb_email": "typed@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content[:200])
        self.assertTrue(response.json()["data"]["requires_email_verification"])
        self.assertNotIn("g5_token", response.cookies)
        self.assertIsNone(Profile.objects.get(user__email="typed@example.test").email_certify)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(SOCIAL_CERTIFY_MAIL=True)
    def test_a_social_signup_is_certified_by_mail_when_the_site_asks_for_it(self):
        self.set_config("cf_use_email_certify", "1")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": self.make_ticket("signup")}, format="json")
        self.assertTrue(response.json()["data"]["requires_email_verification"])

    def test_a_signup_ticket_works_for_one_registration_only(self):
        ticket = self.make_ticket("signup")
        self.assertEqual(self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket}, format="json").status_code, 201)
        again = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_id": "second_try"}, format="json")
        self.assertEqual(again.status_code, 404)

    def test_a_rejected_social_registration_keeps_the_ticket_for_another_try(self):
        self.make_member("taken_id")
        ticket = self.make_ticket("signup")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_id": "taken_id"}, format="json")
        self.assertEqual(response.status_code, 422)
        self.assertIsNotNone(v1_auth._load_social_ticket(ticket, expected_kind="signup"))
        retry = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_id": "fresh_id"}, format="json")
        self.assertEqual(retry.status_code, 201)

    def test_a_login_ticket_cannot_be_used_to_register(self):
        member = self.make_member("login_ticket_owner")
        ticket = self.make_ticket("login", user=member)
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_a_social_signup_with_a_typed_password_must_match_its_confirmation(self):
        response = self.social_client.post(
            REGISTER_URL,
            {"social_signup_ticket": self.make_ticket("signup"), "mb_password": PASSWORD, "mb_password_re": "other"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_password_re", response.json()["errors"])

    def test_a_social_member_without_a_typed_password_cannot_log_in_with_a_guessable_one(self):
        self.social_client.post(REGISTER_URL, {"social_signup_ticket": self.make_ticket("signup")}, format="json")
        for guess in ("", "password", "k", "kakao", "4242"):
            self.assertIn(self.login({"mb_id": "k_user", "mb_password": guess}).status_code, (401, 422), guess)
            cache.clear()

    def test_a_social_login_ticket_for_a_member_awaiting_certification_follows_the_social_exemption(self):
        member = self.make_member("pending_social")
        self.set_config("cf_use_email_certify", "1")
        Profile.objects.filter(user=member).update(email_certify=None)
        ticket = self.make_ticket("login", user=member)
        self.assertEqual(self.social_client.post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 200)
        with override_settings(SOCIAL_CERTIFY_MAIL=True):
            ticket = self.make_ticket("login", user=member)
            refused = self.social_client.post(EXCHANGE_URL, {"ticket": ticket}, format="json")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["code"], "email_not_certified")

    def test_an_exchange_ticket_naming_a_deleted_member_is_refused(self):
        member = self.make_member("vanished")
        ticket = self.make_ticket("login", user=member)
        self.user_model.objects.filter(pk=member.pk).delete()
        self.assertEqual(self.social_client.post(EXCHANGE_URL, {"ticket": ticket}, format="json").status_code, 404)

    def test_the_exchange_accepts_the_ticket_under_either_name_and_ignores_other_bodies(self):
        member = self.make_member("either_name")
        ticket = self.make_ticket("login", user=member)
        self.assertEqual(self.social_client.post(EXCHANGE_URL, {"social_ticket": ticket}, format="json").status_code, 200)
        self.assertEqual(self.social_client.post(EXCHANGE_URL, ["x"], format="json").status_code, 404)

    def test_linking_needs_a_member_who_may_log_in(self):
        member = self.make_member("link_pending")
        self.set_config("cf_use_email_certify", "1")
        Profile.objects.filter(user=member).update(email_certify=None)
        ticket = self.make_ticket("signup")
        response = self.social_client.post(LINK_URL, {"ticket": ticket, "mb_id": "link_pending", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(v1_auth._social_identity_user("kakao", "4242"))
        self.assertIsNotNone(v1_auth._load_social_ticket(ticket))

    def test_linking_an_inactive_member_that_slips_past_the_backend_is_refused(self):
        inactive = self.make_member("link_slip", active=False)
        with mock.patch("gnu_jango.api.v1_auth.authenticate", return_value=inactive):
            response = self.social_client.post(
                LINK_URL, {"ticket": self.make_ticket("signup"), "mb_id": "link_slip", "password": PASSWORD}, format="json"
            )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(v1_auth._social_identity_user("kakao", "4242"))

    def test_linking_the_same_identity_to_its_own_member_again_is_allowed(self):
        member = self.make_member("link_again")
        self.link(member)
        response = self.social_client.post(
            LINK_URL, {"ticket": self.make_ticket("signup"), "mb_id": "link_again", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_linking_with_a_wrong_password_does_not_say_whether_the_member_exists(self):
        self.make_member("link_exists")
        ticket = self.make_ticket("signup")
        wrong = self.social_client.post(LINK_URL, {"ticket": ticket, "mb_id": "link_exists", "password": "wrong-pass-1"}, format="json")
        unknown = self.social_client.post(LINK_URL, {"ticket": ticket, "mb_id": "link_nobody", "password": "wrong-pass-1"}, format="json")
        self.assertEqual(wrong.status_code, unknown.status_code)
        self.assertEqual(wrong.json()["message"], unknown.json()["message"])

    def test_a_link_for_a_member_who_logs_in_with_the_e_mail_address(self):
        member = self.make_member("link_by_mail")
        response = self.social_client.post(
            LINK_URL, {"ticket": self.make_ticket("signup"), "mb_id": member.email, "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(v1_auth._social_identity_user("kakao", "4242"), member)

    def test_a_link_with_a_body_that_is_not_an_object_is_refused(self):
        self.assertEqual(self.social_client.post(LINK_URL, ["x"], format="json").status_code, 404)

    def test_the_identity_of_a_member_who_became_inactive_is_not_used_to_log_in(self):
        member = self.make_member("identity_off")
        self.link(member)
        self.user_model.objects.filter(pk=member.pk).update(is_active=False)
        self.assertIsNone(v1_auth._social_identity_user("kakao", "4242"))
        self.assertIsNone(v1_auth._social_identity_user("kakao", "unknown"))

    def test_a_stored_identity_without_a_member_is_ignored(self):
        Config.objects.create(name=v1_auth._social_identity_config_name("kakao", "9"), value=json.dumps({"provider": "kakao"}))
        self.assertIsNone(v1_auth._social_identity_user("kakao", "9"))

    def test_linking_an_identity_without_a_provider_or_id_stores_nothing(self):
        member = self.make_member("link_empty")
        before = Config.objects.count()
        v1_auth._link_social_identity(member, {"provider": "", "provider_user_id": "1"})
        v1_auth._link_social_identity(member, {"provider": "kakao", "provider_user_id": ""})
        self.assertEqual(Config.objects.count(), before)


class SocialSuggestionTests(AuthTestBase):
    def test_suggested_ids_are_always_valid_and_unused(self):
        self.make_member("taken")
        self.make_member("taken_1")
        cases = {"Taken": "taken_2", "9lives": "u_9lives", "a": "a_user", "": "social_user", "한글": "social_user", "x" * 40: "x" * 20}
        for base, expected in cases.items():
            suggested = v1_auth._unique_member_id(base)
            self.assertTrue(v1_auth.MEMBER_ID_RE.match(suggested), (base, suggested))
            self.assertEqual(suggested, expected, base)

    def test_a_suggested_id_falls_back_to_a_random_one_when_all_numbered_ids_are_taken(self):
        with mock.patch.object(v1_auth.User.objects, "filter") as filtered:
            filtered.return_value.exists.return_value = True
            suggested = v1_auth._unique_member_id("busy")
        self.assertTrue(suggested.startswith("social_"))
        self.assertTrue(v1_auth.MEMBER_ID_RE.match(suggested))

    def test_suggested_nicknames_get_a_number_until_free(self):
        for index, nickname in enumerate(("Nick", "Nick1", "nick2")):
            user = self.make_member(f"nick_owner_{index}")
            Profile.objects.filter(user=user).update(nickname=nickname)
        self.assertEqual(v1_auth._unique_nickname("NICK"), "NICK3")
        self.assertEqual(v1_auth._unique_nickname(""), "social_user")
        self.assertEqual(len(v1_auth._unique_nickname("n" * 300)), 80)

    def test_a_suggested_nickname_falls_back_to_a_random_suffix_when_all_numbers_are_taken(self):
        with mock.patch.object(v1_auth.Profile.objects, "filter") as filtered:
            filtered.return_value.exists.return_value = True
            suggested = v1_auth._unique_nickname("busy")
        self.assertTrue(suggested.startswith("busy"))
        self.assertGreater(len(suggested), 4)

    def test_without_an_e_mail_the_id_comes_from_the_provider_and_its_user_id(self):
        profile = {"provider": "naver", "provider_user_id": "Ab-12", "email": ""}
        self.assertEqual(v1_auth._suggest_social_member_id(profile), "naver_ab_12")
        self.assertEqual(v1_auth._suggest_social_nickname(profile), "Ab-12")

    def test_the_nickname_falls_back_to_the_name_and_then_the_e_mail_name(self):
        self.assertEqual(v1_auth._suggest_social_nickname({"name": "Real Name", "email": "x@y.z"}), "Real Name")
        self.assertEqual(v1_auth._suggest_social_nickname({"email": "mailname@y.z", "provider_user_id": "1"}), "mailname")


class SocialHttpTests(AuthTestBase):
    URL = "https://provider.example/token"

    def response(self, body):
        handle = mock.MagicMock()
        handle.__enter__.return_value.read.return_value = body
        return handle

    def test_a_json_answer_is_returned_and_a_post_form_encodes_its_data(self):
        with mock.patch.object(v1_auth.urllib_request, "urlopen", return_value=self.response(b'{"ok": 1}')) as opened:
            result = v1_auth._http_json_request(self.URL, method="POST", data={"a": "b c"}, headers={"X-Test": "1"})
        self.assertEqual(result, {"ok": 1})
        request = opened.call_args.args[0]
        self.assertEqual(request.data, b"a=b+c")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-test"), "1")
        self.assertIn("urlencoded", request.get_header("Content-type"))
        self.assertEqual(opened.call_args.kwargs["timeout"], v1_auth.SOCIAL_TOKEN_TIMEOUT_SECONDS)

    def test_a_get_sends_no_body(self):
        with mock.patch.object(v1_auth.urllib_request, "urlopen", return_value=self.response(b"{}")) as opened:
            v1_auth._http_json_request(self.URL)
        self.assertIsNone(opened.call_args.args[0].data)

    def test_a_refusal_by_the_provider_becomes_an_oauth_error_with_its_status(self):
        error = urllib.error.HTTPError(self.URL, 401, "no", {}, BytesIO(b'{"error": "invalid_client"}'))
        with mock.patch.object(v1_auth.urllib_request, "urlopen", side_effect=error):
            with self.assertRaises(v1_auth.SocialOAuthError) as caught:
                v1_auth._http_json_request(self.URL)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertIn("invalid_client", str(caught.exception))

    def test_a_network_failure_or_timeout_becomes_a_bad_gateway_error(self):
        import socket

        for failure in (urllib.error.URLError("down"), socket.timeout("slow")):
            with mock.patch.object(v1_auth.urllib_request, "urlopen", side_effect=failure):
                with self.assertRaises(v1_auth.SocialOAuthError) as caught:
                    v1_auth._http_json_request(self.URL)
            self.assertEqual(caught.exception.status_code, 502)

    def test_an_answer_that_is_not_json_becomes_a_bad_gateway_error(self):
        with mock.patch.object(v1_auth.urllib_request, "urlopen", return_value=self.response(b"<html>oops</html>")):
            with self.assertRaises(v1_auth.SocialOAuthError) as caught:
                v1_auth._http_json_request(self.URL)
        self.assertEqual(caught.exception.status_code, 502)

    @override_settings(SOCIAL_KAKAO_REST_KEY="kakao-key")
    def test_the_provider_error_text_stays_out_of_the_redirect_the_visitor_sees(self):
        error = urllib.error.HTTPError(self.URL, 400, "no", {}, BytesIO(b"secret-detail-from-provider"))
        client = APIClient()
        response = client.get(START_URL, {"provider": "kakao", "redirect": "/back"})
        state = query_of(response["Location"])["state"]
        with mock.patch.object(v1_auth.urllib_request, "urlopen", side_effect=error):
            result = client.get(CALLBACK_URL, {"state": state, "code": "c"})
        self.assertNotIn("secret-detail", result["Location"])
        self.assertEqual(query_of(result["Location"])["error"], "social_oauth_failed")

    def test_unsupported_providers_are_rejected_by_the_token_and_profile_steps(self):
        config = {"name": "myspace", "client_id": "i", "client_secret": "s", "token_url": self.URL, "label": "M"}
        with self.assertRaises(v1_auth.SocialOAuthError) as caught:
            v1_auth._social_token(config, "c", "s", "http://testserver/cb")
        self.assertEqual(caught.exception.code, "unsupported_provider")
        with mock.patch(HTTP_PATCH, return_value={}):
            with self.assertRaises(v1_auth.SocialOAuthError) as caught:
                v1_auth._social_userinfo({**config, "userinfo_url": self.URL}, "token")
        self.assertEqual(caught.exception.code, "unsupported_provider")

    def test_the_pkce_challenge_is_the_url_safe_sha256_of_the_verifier(self):
        # RFC 7636 appendix B test vector.
        self.assertEqual(
            v1_auth._social_pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )
        self.assertNotEqual(v1_auth._social_pkce_verifier(), v1_auth._social_pkce_verifier())


@override_settings(**SOCIAL_SETTINGS)
class MemberRuleBypassTests(SocialFlowBase):
    """The signup rules hold for the social signup and for later profile and certify-address changes."""

    def test_a_social_signup_follows_the_reserved_and_prohibited_lists(self):
        self.set_config("cf_prohibit_id", "admin")
        self.set_config("cf_prohibit_email", "example.test")
        ticket = self.make_ticket("signup")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket, "mb_nick": "admin"}, format="json")
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])
        self.assertIn("mb_nick", response.json()["errors"])
        self.assertIsNone(v1_auth._social_identity_owner("kakao", "4242"))

    def test_a_social_signup_refuses_a_malformed_typed_address(self):
        response = self.social_client.post(
            REGISTER_URL, {"social_signup_ticket": self.make_ticket("signup"), "mb_email": "typed@"}, format="json"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])

    def test_markup_in_the_provider_nickname_is_left_out_of_the_suggestion(self):
        ticket = self.make_ticket("signup", nickname="<b>Kim</b>")
        response = self.social_client.post(REGISTER_URL, {"social_signup_ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Profile.objects.get(user__username="k_user").nickname, "Kim")

    def signed_in_client(self, username):
        member = self.make_member(username)
        token = self.login({"mb_id": username, "mb_password": PASSWORD}).json()["data"]["token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return member, client

    def test_a_profile_change_cannot_take_a_reserved_nickname(self):
        self.set_config("cf_prohibit_id", "administrator")
        member, client = self.signed_in_client("rule_nick")
        response = client.patch("/api/v1/members/me", {"mb_nick": "Administrator"}, format="json")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"]["mb_nick"], "이미 예약된 단어로 사용할 수 없는 닉네임 입니다.")
        self.assertEqual(Profile.objects.get(user=member).nickname, "nick-rule_nick")

    def test_a_profile_change_cannot_move_to_a_prohibited_domain(self):
        self.set_config("cf_prohibit_email", "hotmail.com")
        member, client = self.signed_in_client("rule_mail")
        response = client.patch(
            "/api/v1/members/me", {"mb_email": "me@hotmail.com", "mb_password_current": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])
        self.assertEqual(self.user_model.objects.get(pk=member.pk).email, "rule_mail@example.test")

    def test_a_member_whose_domain_was_barred_later_can_still_save_the_profile(self):
        member, client = self.signed_in_client("rule_keep")
        self.set_config("cf_prohibit_email", "example.test")
        response = client.patch("/api/v1/members/me", {"mb_email": member.email, "mb_name": "Kept"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])

    def test_the_certify_resend_cannot_switch_to_a_prohibited_domain(self):
        self.set_config("cf_use_email_certify", "1")
        self.set_config("cf_prohibit_email", "hotmail.com")
        member = self.make_member("rule_resend")
        Profile.objects.filter(user=member).update(email_certify=None)
        response = APIClient().post(
            "/api/v1/auth/email-certify/resend",
            {"mb_id": "rule_resend", "mb_password": PASSWORD, "mb_email": "me@hotmail.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])
        self.assertEqual(len(mail.outbox), 0)
