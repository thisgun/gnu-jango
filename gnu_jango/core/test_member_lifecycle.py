"""Member leave, e-mail certification and the open profile, as in Gnuboard5.

bbs/member_leave.php and lib/common.lib.php g5_leave_member (a member leaves with their password),
register_form_update.php, login_check.php, email_certify.php and register_email_update.php (with
cf_use_email_certify on a member must click the mailed link before logging in) and profile.php with
mb_open / cf_open_modify (a member who keeps their profile closed is not shown to other members).
"""

import re
import tempfile
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api import v1_auth
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile

PASSWORD = "Str0ng-pass-99"
CAPTCHA_PATCH = "gnu_jango.api.v1_auth._captcha_matches"
AUTH_COOKIES = ("g5_token", "g5_refresh", "g5_auth_hint", "g5_auto_login")
LEAVE_URL = "/api/v1/members/me/leave"
CERTIFY_URL = "/api/v1/auth/email-certify"
RESEND_URL = "/api/v1/auth/email-certify/resend"


class LifecycleTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user_model = get_user_model()

    def make_member(self, username, *, nickname=None, active=True, **extra):
        user = self.user_model.objects.create_user(
            username=username, email=f"{username}@example.test", password=PASSWORD, is_active=active, **extra
        )
        profile = Profile.objects.get(user=user)
        profile.nickname = nickname or f"nick-{username}"
        profile.user_level = 2
        profile.save()
        return self.user_model.objects.get(pk=user.pk)

    def profile(self, user):
        return Profile.objects.get(user=user)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def set_config(self, name, value):
        Config.objects.update_or_create(name=name, defaults={"value": str(value)})
        site_config.clear()
        self.addCleanup(site_config.clear)

    def login(self, mb_id, password=PASSWORD):
        return APIClient().post("/api/v1/auth/login", {"mb_id": mb_id, "mb_password": password}, format="json")

    def register(self, client=None, **overrides):
        payload = {
            "mb_id": "life_member",
            "mb_password": PASSWORD,
            "mb_password_re": PASSWORD,
            "mb_email": "life-member@example.test",
            "mb_name": "Life Member",
            "mb_nick": "life-nick",
            "captcha_key": "123456",
        }
        payload.update(overrides)
        payload = {key: value for key, value in payload.items() if value is not None}
        with mock.patch(CAPTCHA_PATCH, return_value=True):
            return (client or APIClient()).post("/api/v1/auth/register", payload, format="json")

    def certify(self, params):
        return APIClient().post(CERTIFY_URL, params, format="json")

    def uncertify(self, user, token=""):
        Profile.objects.filter(user=user).update(email_certify=None, email_certify_token=token)

    def certify_link(self, message):
        match = re.search(r"https?://\S+/email-certify\?\S+", message.body)
        self.assertIsNotNone(match, message.body)
        query = parse_qs(urlparse(match.group(0)).query)
        return query["mb_id"][0], query["token"][0]

    def assert_auth_cookies_cleared(self, response):
        for name in AUTH_COOKIES:
            self.assertIn(name, response.cookies, name)
            self.assertEqual(response.cookies[name].value, "", name)


class MemberLeaveTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("leaver", nickname="떠나는회원")

    def test_only_members_can_leave(self):
        response = APIClient().post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_a_wrong_or_missing_password_is_refused(self):
        for payload in ({"mb_password": "wrong-password"}, {}, {"mb_password": "   "}):
            with self.subTest(payload=payload):
                response = self.client_for(self.member).post(LEAVE_URL, payload, format="json")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["message"], "비밀번호가 틀립니다.")
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertIsNone(self.profile(self.member).leave_date)

    def test_the_super_admin_cannot_leave(self):
        admin = self.make_member("top_admin", is_superuser=True, is_staff=True)
        response = self.client_for(admin).post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["message"], "최고 관리자는 탈퇴할 수 없습니다")
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)

    def test_the_configured_site_admin_cannot_leave(self):
        self.set_config("cf_admin", "leaver")
        response = self.client_for(self.member).post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 403)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_leaving_deactivates_the_member_and_logs_out_everywhere(self):
        Profile.objects.filter(user=self.member).update(email_certify_token="pending.1700000000")
        refresh = RefreshToken.for_user(self.member)
        response = self.client_for(self.member).post(LEAVE_URL, {"password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        today = timezone.localdate()
        self.assertEqual(
            response.json()["data"]["message"],
            f"떠나는회원님께서는 {today:%Y}년 {today:%m}월 {today:%d}일에 회원에서 탈퇴 하셨습니다.",
        )
        self.assertEqual(response.json()["data"]["mb_leave_date"], today.strftime("%Y%m%d"))
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        profile = self.profile(self.member)
        self.assertEqual(profile.leave_date, today)
        self.assertEqual(profile.email_certify_token, "")
        outstanding = OutstandingToken.objects.get(jti=refresh["jti"])
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())
        self.assert_auth_cookies_cleared(response)

    def test_a_member_who_left_is_told_so_at_login(self):
        self.client_for(self.member).post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        response = self.login("leaver")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "member_left")
        today = timezone.localdate()
        self.assertIn(f"탈퇴일 : {today:%Y}년 {today:%m}월 {today:%d}일", response.json()["message"])
        self.assertNotIn("g5_token", response.cookies)

    def test_a_wrong_password_for_a_member_who_left_reveals_nothing(self):
        self.client_for(self.member).post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        response = self.login("leaver", "not-the-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_login")

    def test_leaving_removes_the_social_links(self):
        v1_auth._link_social_identity(self.member, {"provider": "naver", "provider_user_id": "n-1"})
        other = self.make_member("stayer")
        v1_auth._link_social_identity(other, {"provider": "naver", "provider_user_id": "n-2"})
        self.client_for(self.member).post(LEAVE_URL, {"mb_password": PASSWORD}, format="json")
        name = v1_auth._social_identity_config_name
        self.assertFalse(Config.objects.filter(name=name("naver", "n-1")).exists())
        self.assertTrue(Config.objects.filter(name=name("naver", "n-2")).exists())

    def admin_client(self):
        admin_user = self.user_model.objects.create_superuser(
            username="life_admin", email="life_admin@example.test", password=PASSWORD
        )
        client = Client()
        client.force_login(admin_user)
        return client

    def test_the_admin_sees_the_stored_leave_date(self):
        left_on = timezone.localdate() - timedelta(days=3)
        Profile.objects.filter(user=self.member).update(leave_date=left_on)
        self.user_model.objects.filter(pk=self.member.pk).update(is_active=False)
        response = self.admin_client().get(reverse("admin:auth_user_change", args=[self.member.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(left_on.isoformat(), response.content.decode())

    def test_the_admin_leave_action_stores_the_leave_date(self):
        response = self.admin_client().post(
            reverse("admin:auth_user_changelist"),
            {"action": "leave_selected_members", "_selected_action": [self.member.pk]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.profile(self.member).leave_date, timezone.localdate())


class RegistrationCertifyTests(LifecycleTestBase):
    def test_without_email_certification_a_new_member_is_certified_and_signed_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["token"])
        self.assertIsNotNone(self.profile(self.user_model.objects.get(username="life_member")).email_certify)
        self.assertEqual(len(mail.outbox), 0)

    def test_with_email_certification_the_new_member_gets_a_link_and_no_login(self):
        self.set_config("cf_use_email_certify", 1)
        response = self.register()
        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["requires_email_verification"])
        self.assertNotIn("token", data)
        self.assertNotIn("g5_token", response.cookies)
        user = self.user_model.objects.get(username="life_member")
        profile = self.profile(user)
        self.assertIsNone(profile.email_certify)
        self.assertRegex(profile.email_certify_token, r"^[0-9a-f]{32}\.[0-9]{10}$")
        self.assertEqual([message.to for message in mail.outbox], [["life-member@example.test"]])
        self.assertIn("인증확인 메일입니다", mail.outbox[0].subject)
        mb_id, token = self.certify_link(mail.outbox[0])
        self.assertEqual((mb_id, token), ("life_member", profile.email_certify_token))

    def test_the_registration_result_says_certification_is_pending(self):
        self.set_config("cf_use_email_certify", 1)
        client = APIClient()
        self.register(client)
        response = client.get("/api/v1/auth/register-result")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["requires_email_verification"])


class LoginCertifyTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("pending_member")
        self.uncertify(self.member, "a" * 32 + f".{int(timezone.now().timestamp())}")

    def test_an_uncertified_member_cannot_log_in_while_certification_is_on(self):
        self.set_config("cf_use_email_certify", 1)
        response = self.login("pending_member")
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], "email_not_certified")
        self.assertEqual(
            body["message"], "pending_member@example.test 메일로 메일인증을 받으셔야 로그인 가능합니다."
        )
        self.assertEqual(body["errors"]["mb_id"], "pending_member")
        self.assertNotIn("g5_token", response.cookies)

    def test_the_wrong_password_is_reported_before_the_certification(self):
        self.set_config("cf_use_email_certify", 1)
        response = self.login("pending_member", "wrong-password")
        self.assertEqual(response.status_code, 401)

    def test_with_certification_off_the_member_logs_in(self):
        self.assertEqual(self.login("pending_member").status_code, 200)

    def test_members_created_outside_registration_are_certified(self):
        self.set_config("cf_use_email_certify", 1)
        self.make_member("admin_made")
        self.assertEqual(self.login("admin_made").status_code, 200)


class EmailCertifyEndpointTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.set_config("cf_use_email_certify", 1)
        self.member = self.make_member("cert_member")
        self.token = "b" * 32 + f".{int(timezone.now().timestamp())}"
        self.uncertify(self.member, self.token)

    def test_the_link_certifies_once(self):
        response = self.certify({"mb_id": "cert_member", "token": self.token})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(
            response.json()["data"]["message"],
            "메일인증 처리를 완료 하였습니다.\n\n지금부터 cert_member 아이디로 로그인 가능합니다.",
        )
        profile = self.profile(self.member)
        self.assertIsNotNone(profile.email_certify)
        self.assertEqual(profile.email_certify_token, "")
        self.assertEqual(self.login("cert_member").status_code, 200)

        replay = self.certify({"mb_id": "cert_member", "token": self.token})
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()["message"], "메일인증 요청 정보가 올바르지 않습니다.")

    def test_the_link_can_be_posted_and_accepts_the_php_parameter_name(self):
        response = APIClient().post(CERTIFY_URL, {"mb_id": "cert_member", "mb_md5": self.token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.profile(self.member).email_certify)

    def test_a_wrong_token_changes_nothing(self):
        response = self.certify({"mb_id": "cert_member", "token": "c" * 32 + ".1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "email_certify_invalid")
        profile = self.profile(self.member)
        self.assertIsNone(profile.email_certify)
        self.assertEqual(profile.email_certify_token, self.token)

    def test_an_expired_link_is_burnt(self):
        old = "d" * 32 + f".{int((timezone.now() - timedelta(minutes=61)).timestamp())}"
        self.uncertify(self.member, old)
        response = self.certify({"mb_id": "cert_member", "token": old})
        self.assertEqual(response.status_code, 410)
        self.assertEqual(
            response.json()["message"], "메일인증 유효시간이 만료되었습니다. 인증메일을 다시 요청해 주십시오."
        )
        profile = self.profile(self.member)
        self.assertIsNone(profile.email_certify)
        self.assertEqual(profile.email_certify_token, "")

    def test_the_validity_follows_the_configured_minutes(self):
        old = "e" * 32 + f".{int((timezone.now() - timedelta(minutes=61)).timestamp())}"
        self.uncertify(self.member, old)
        self.set_config("cf_email_certify_minutes", 120)
        response = self.certify({"mb_id": "cert_member", "token": old})
        self.assertEqual(response.status_code, 200)

    def test_zero_minutes_means_the_link_never_expires(self):
        old = "f" * 32 + ".1000000000"
        self.uncertify(self.member, old)
        self.set_config("cf_email_certify_minutes", 0)
        self.assertEqual(self.certify({"mb_id": "cert_member", "token": old}).status_code, 200)

    def test_a_token_without_issue_time_counts_from_the_join_date(self):
        self.uncertify(self.member, "legacytoken")
        self.user_model.objects.filter(pk=self.member.pk).update(date_joined=timezone.now() - timedelta(hours=2))
        response = self.certify({"mb_id": "cert_member", "token": "legacytoken"})
        self.assertEqual(response.status_code, 410)
        self.uncertify(self.member, "legacytoken")
        self.user_model.objects.filter(pk=self.member.pk).update(date_joined=timezone.now() - timedelta(minutes=5))
        response = self.certify({"mb_id": "cert_member", "token": "legacytoken"})
        self.assertEqual(response.status_code, 200)

    def test_a_blocked_or_departed_member_is_not_certified(self):
        self.user_model.objects.filter(pk=self.member.pk).update(is_active=False)
        response = self.certify({"mb_id": "cert_member", "token": self.token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["message"], "탈퇴 또는 차단된 회원입니다.")
        self.assertIsNone(self.profile(self.member).email_certify)

    def test_the_php_certify_link_opens_the_certify_page(self):
        response = self.client.get("/bbs/email_certify.php", {"mb_id": "cert_member", "mb_md5": self.token})
        self.assertIn(response.status_code, (301, 302, 307, 308))
        target = urlparse(response["Location"])
        self.assertEqual(target.path, "/email-certify")
        self.assertEqual(parse_qs(target.query), {"mb_id": ["cert_member"], "token": [self.token]})

    def test_missing_values_and_unknown_members(self):
        response = self.certify({"mb_id": "cert_member"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "제대로 된 값이 넘어오지 않았습니다.")
        # An unknown id answers exactly like a wrong token, so ids cannot be probed.
        unknown = self.certify({"mb_id": "ghost", "token": self.token})
        wrong = self.certify({"mb_id": "cert_member", "token": "0" * 32 + ".1"})
        self.assertEqual((unknown.status_code, unknown.json()), (wrong.status_code, wrong.json()))
        self.assertEqual(unknown.json()["message"], "메일인증 요청 정보가 올바르지 않습니다.")


class ResendCertifyTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.set_config("cf_use_email_certify", 1)
        self.member = self.make_member("resend_member")
        self.old_token = "1" * 32 + f".{int(timezone.now().timestamp())}"
        self.uncertify(self.member, self.old_token)

    def resend(self, **payload):
        body = {"mb_id": "resend_member", "mb_password": PASSWORD}
        body.update(payload)
        return APIClient().post(RESEND_URL, body, format="json")

    def test_a_new_link_replaces_the_old_one(self):
        response = self.resend()
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(
            response.json()["data"]["message"],
            "인증메일을 resend_member@example.test 메일로 다시 보내 드렸습니다.\n\n"
            "잠시후 resend_member@example.test 메일을 확인하여 주십시오.",
        )
        self.assertEqual([message.to for message in mail.outbox], [["resend_member@example.test"]])
        _, token = self.certify_link(mail.outbox[0])
        self.assertNotEqual(token, self.old_token)
        self.assertEqual(self.certify({"mb_id": "resend_member", "token": self.old_token}).status_code, 400)
        self.assertEqual(self.certify({"mb_id": "resend_member", "token": token}).status_code, 200)

    def test_the_password_must_match(self):
        response = self.resend(mb_password="wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.profile(self.member).email_certify_token, self.old_token)

    def test_a_certified_member_gets_no_mail(self):
        Profile.objects.filter(user=self.member).update(email_certify=timezone.now())
        response = self.resend()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "이미 메일인증 하신 회원입니다.")
        self.assertEqual(len(mail.outbox), 0)

    def test_nothing_is_sent_when_certification_is_off(self):
        self.set_config("cf_use_email_certify", 0)
        self.assertEqual(self.resend().status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_the_member_can_switch_to_another_address(self):
        response = self.resend(mb_email="new-box@example.test")
        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "new-box@example.test")
        self.assertEqual([message.to for message in mail.outbox], [["new-box@example.test"]])

    def test_an_address_of_another_member_is_refused(self):
        self.make_member("box_owner")
        response = self.resend(mb_email="box_owner@example.test")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["message"],
            "box_owner@example.test 메일은 이미 존재하는 메일주소 입니다.\n\n다른 메일주소를 입력해 주십시오.",
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_a_second_request_right_away_is_refused(self):
        self.assertEqual(self.resend().status_code, 200)
        self.assertEqual(self.resend().status_code, 429)
        self.assertEqual(len(mail.outbox), 1)


class ProfileEmailChangeTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.member = self.make_member("mover")
        self.client = self.client_for(self.member)

    def test_a_changed_email_must_be_certified_again(self):
        self.set_config("cf_use_email_certify", 1)
        refresh = RefreshToken.for_user(self.member)
        response = self.client.patch("/api/v1/members/me", {"mb_email": "moved@example.test", "mb_password_current": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["email_certify_required"])
        self.assertEqual(
            data["message"], "회원 정보가 수정 되었습니다.\n\nE-mail 주소가 변경되었으므로 다시 인증하셔야 합니다."
        )
        profile = self.profile(self.member)
        self.assertIsNone(profile.email_certify)
        self.assertTrue(profile.email_certify_token)
        self.assertEqual([message.to for message in mail.outbox], [["moved@example.test"]])
        self.assertIn("E-mail 주소가 변경되었습니다", mail.outbox[0].body)
        outstanding = OutstandingToken.objects.get(jti=refresh["jti"])
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())
        self.assert_auth_cookies_cleared(response)
        self.assertEqual(self.login("mover").json()["code"], "email_not_certified")

    def test_the_same_email_keeps_the_certification(self):
        self.set_config("cf_use_email_certify", 1)
        response = self.client.patch("/api/v1/members/me", {"mb_email": "mover@example.test"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("email_certify_required", response.json()["data"])
        self.assertIsNotNone(self.profile(self.member).email_certify)
        self.assertEqual(len(mail.outbox), 0)

    def test_without_certification_a_new_email_is_simply_saved(self):
        response = self.client.patch("/api/v1/members/me", {"mb_email": "moved@example.test", "mb_password_current": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.profile(self.member).email_certify)
        self.assertEqual(len(mail.outbox), 0)


def bound_social_ticket(profile, *, kind, user=None):
    """A social ticket and the browser it belongs to: a ticket only works where the social login started."""
    client = APIClient()
    session = client.session
    ticket, _ = v1_auth._create_social_ticket(profile, kind=kind, user=user, session=session)
    session.save()
    return ticket, client


class SocialCertifyTests(LifecycleTestBase):
    SOCIAL_PROFILE = {
        "provider": "naver",
        "provider_label": "Naver",
        "provider_user_id": "naver-77",
        "email": "social-77@example.test",
        "name": "Social Member",
        "nickname": "social77",
    }

    def setUp(self):
        super().setUp()
        self.set_config("cf_use_email_certify", 1)

    def test_a_social_login_is_not_held_back_by_the_certification(self):
        member = self.make_member("social_login")
        self.uncertify(member)
        ticket, browser = bound_social_ticket(self.SOCIAL_PROFILE, kind="login", user=member)
        response = browser.post("/api/v1/auth/social/exchange", {"ticket": ticket}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_a_social_signup_with_the_provider_email_is_certified(self):
        ticket, browser = bound_social_ticket(self.SOCIAL_PROFILE, kind="signup")
        response = self.register(
            browser,
            mb_id="social_new", mb_email="social-77@example.test", mb_password=None, mb_password_re=None,
            social_signup_ticket=ticket,
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["token"])
        self.assertIsNotNone(self.profile(self.user_model.objects.get(username="social_new")).email_certify)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_social_signup_with_another_email_must_certify_it(self):
        ticket, browser = bound_social_ticket(self.SOCIAL_PROFILE, kind="signup")
        response = self.register(
            browser,
            mb_id="social_other", mb_email="other-box@example.test", mb_password=None, mb_password_re=None,
            social_signup_ticket=ticket,
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["requires_email_verification"])
        self.assertIsNone(self.profile(self.user_model.objects.get(username="social_other")).email_certify)
        self.assertEqual([message.to for message in mail.outbox], [["other-box@example.test"]])


class OpenProfileTests(LifecycleTestBase):
    def setUp(self):
        super().setUp()
        self.viewer = self.make_member("open_viewer")
        self.target = self.make_member("open_target")

    def profile_url(self, mb_id):
        return f"/api/v1/members/{mb_id}/profile"

    def test_a_new_registration_is_open_by_default(self):
        self.register()
        profile = self.profile(self.user_model.objects.get(username="life_member"))
        self.assertTrue(profile.open_profile)
        self.assertIsNotNone(profile.open_profile_date)

    def test_a_registration_can_keep_the_profile_closed(self):
        self.register(mb_open=0)
        self.assertFalse(self.profile(self.user_model.objects.get(username="life_member")).open_profile)

    def test_information_mail_is_off_unless_the_new_member_ticks_it(self):
        self.register()
        self.assertFalse(self.profile(self.user_model.objects.get(username="life_member")).mailing)

    def test_a_registration_can_agree_to_information_mail(self):
        self.register(mb_mailling=1)
        profile = self.profile(self.user_model.objects.get(username="life_member"))
        self.assertTrue(profile.mailing)
        self.assertIsNotNone(profile.mailing_date)

    def test_the_member_can_change_the_information_mail_answer(self):
        response = self.client_for(self.target).patch("/api/v1/members/me", {"mb_mailling": 1}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_mailling"], 1)
        profile = self.profile(self.target)
        self.assertTrue(profile.mailing)
        agreed_at = profile.mailing_date
        self.assertIsNotNone(agreed_at)
        # Sending the unchanged answer keeps the date of the consent.
        self.client_for(self.target).patch("/api/v1/members/me", {"mb_mailling": True}, format="json")
        self.assertEqual(self.profile(self.target).mailing_date, agreed_at)
        self.client_for(self.target).patch("/api/v1/members/me", {"mb_mailling": 0}, format="json")
        self.assertFalse(self.profile(self.target).mailing)

    def test_the_member_can_close_the_profile(self):
        response = self.client_for(self.target).patch("/api/v1/members/me", {"mb_open": 0}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_open"], 0)
        profile = self.profile(self.target)
        self.assertFalse(profile.open_profile)
        self.assertIsNotNone(profile.open_profile_date)

    def test_the_open_setting_keeps_for_cf_open_modify_days(self):
        self.set_config("cf_open_modify", 30)
        Profile.objects.filter(user=self.target).update(open_profile_date=timezone.now() - timedelta(days=10))
        response = self.client_for(self.target).patch("/api/v1/members/me", {"mb_open": False}, format="json")
        self.assertEqual(response.status_code, 422)
        until = timezone.localdate() + timedelta(days=20)
        self.assertEqual(
            response.json()["message"],
            f"정보공개는 수정후 30일 이내, {until:%Y}년 {until:%m}월 {until.day}일 까지는 변경이 안됩니다.",
        )
        self.assertTrue(self.profile(self.target).open_profile)
        # Sending the unchanged value is not a change.
        self.assertEqual(
            self.client_for(self.target).patch("/api/v1/members/me", {"mb_open": 1}, format="json").status_code, 200
        )
        Profile.objects.filter(user=self.target).update(open_profile_date=timezone.now() - timedelta(days=31))
        response = self.client_for(self.target).patch("/api/v1/members/me", {"mb_open": "0"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.profile(self.target).open_profile)

    def test_a_closed_profile_is_hidden_from_other_members(self):
        Profile.objects.filter(user=self.target).update(open_profile=False)
        response = self.client_for(self.viewer).get(self.profile_url("open_target"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["message"], "정보공개를 하지 않았습니다.")

    def test_the_member_and_the_super_admin_still_see_a_closed_profile(self):
        Profile.objects.filter(user=self.target).update(open_profile=False)
        own = self.client_for(self.target).get(self.profile_url("open_target"))
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()["data"]["member"]["mb_open"], 0)
        admin = self.make_member("open_admin", is_superuser=True, is_staff=True)
        self.assertEqual(self.client_for(admin).get(self.profile_url("open_target")).status_code, 200)

    def test_a_member_with_a_closed_profile_cannot_look_at_others(self):
        Profile.objects.filter(user=self.viewer).update(open_profile=False)
        response = self.client_for(self.viewer).get(self.profile_url("open_target"))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["message"].startswith("자신의 정보를 공개하지 않으면"))

    def test_an_open_profile_says_so(self):
        response = self.client_for(self.viewer).get(self.profile_url("open_target"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["member"]["mb_open"], 1)


class ExistingDataTests(LifecycleTestBase):
    def test_the_migration_certifies_existing_active_members(self):
        migration = import_module("gnu_jango.users.migrations.0013_profile_member_lifecycle")
        active = self.make_member("old_active")
        inactive = self.make_member("old_inactive", active=False)
        self.uncertify(active)
        self.uncertify(inactive)
        migration.certify_existing_members(django_apps, None)
        self.assertEqual(self.profile(active).email_certify, active.date_joined)
        self.assertIsNone(self.profile(inactive).email_certify)

    def test_the_importer_copies_leave_certification_and_open_fields(self):
        from gnu_jango.core.management.commands.migrate_gnuboard5 import Command

        command = Command()
        command.source_root = Path(tempfile.mkdtemp())
        base = {"mb_password": "", "mb_name": "Imported", "mb_level": 2, "mb_datetime": "2020-01-02 03:04:05"}
        rows = [
            dict(base, mb_id="gone_member", mb_email="gone@example.test", mb_nick="gone", mb_leave_date="20250101",
                 mb_email_certify="2020-01-02 04:00:00", mb_email_certify2="", mb_open=1, mb_open_date="2024-05-06"),
            dict(base, mb_id="unverified", mb_email="unv@example.test", mb_nick="unv", mb_leave_date="",
                 mb_email_certify="0000-00-00 00:00:00", mb_email_certify2="abc.1700000000", mb_open=0,
                 mb_open_date="0000-00-00"),
        ]
        self.assertEqual(command.import_members(rows), 2)
        gone = self.profile(self.user_model.objects.get(username="gone_member"))
        self.assertEqual(gone.leave_date.isoformat(), "2025-01-01")
        self.assertEqual(timezone.localtime(gone.email_certify).strftime("%Y-%m-%d %H:%M"), "2020-01-02 04:00")
        self.assertTrue(gone.open_profile)
        self.assertEqual(timezone.localtime(gone.open_profile_date).date().isoformat(), "2024-05-06")
        unverified = self.profile(self.user_model.objects.get(username="unverified"))
        self.assertIsNone(unverified.leave_date)
        self.assertIsNone(unverified.email_certify)
        self.assertEqual(unverified.email_certify_token, "abc.1700000000")
        self.assertFalse(unverified.open_profile)
        self.assertIsNone(unverified.open_profile_date)


class SecurityHardeningTests(LifecycleTestBase):
    """Review findings: every token-issuing path checks the certification, password checks are
    throttled, a pending member's old tokens stop working and the certify endpoint leaks nothing."""

    def setUp(self):
        super().setUp()
        self.member = self.make_member("hard_member")

    def bearer(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def test_linking_a_social_account_checks_the_certification(self):
        self.set_config("cf_use_email_certify", 1)
        self.uncertify(self.member)
        ticket, browser = bound_social_ticket(SocialCertifyTests.SOCIAL_PROFILE, kind="signup")
        response = browser.post(
            "/api/v1/auth/social/link-existing",
            {"ticket": ticket, "mb_id": "hard_member", "mb_password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "email_not_certified")
        self.assertNotIn("g5_token", response.cookies)

    def test_linking_a_social_account_is_throttled_like_login(self):
        ticket, browser = bound_social_ticket(SocialCertifyTests.SOCIAL_PROFILE, kind="signup")
        codes = [
            browser.post(
                "/api/v1/auth/social/link-existing",
                {"ticket": ticket, "mb_id": "hard_member", "mb_password": "wrong-password"},
                format="json",
            ).status_code
            for _ in range(12)
        ]
        self.assertIn(429, codes)

    def test_a_refresh_token_does_not_bypass_the_certification(self):
        refresh = str(RefreshToken.for_user(self.member))
        self.set_config("cf_use_email_certify", 1)
        self.uncertify(self.member)
        response = APIClient().post("/api/v1/auth/refresh", {"refresh_token": refresh}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "email_not_certified")

    def test_a_missing_profile_does_not_lock_the_member_out(self):
        self.set_config("cf_use_email_certify", 1)
        Profile.objects.filter(user=self.member).delete()
        self.assertEqual(self.login("hard_member").status_code, 200)
        self.assertIsNotNone(self.profile(self.member).email_certify)

    def test_changing_the_email_needs_the_current_password(self):
        client = self.client_for(self.member)
        missing = client.patch("/api/v1/members/me", {"mb_email": "new@example.test"}, format="json")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["message"], "이메일을 변경하려면 현재 비밀번호를 입력해주세요.")
        wrong = client.patch(
            "/api/v1/members/me", {"mb_email": "new@example.test", "mb_password_current": "nope-nope"}, format="json"
        )
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(wrong.json()["message"], "현재 비밀번호가 올바르지 않습니다.")
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "hard_member@example.test")
        # Sending the unchanged address (as the profile form does) needs no password.
        same = client.patch("/api/v1/members/me", {"mb_email": "hard_member@example.test", "mb_nick": "n2"}, format="json")
        self.assertEqual(same.status_code, 200)

    def test_after_an_email_change_old_tokens_and_the_session_stop_working(self):
        self.set_config("cf_use_email_certify", 1)
        client = self.bearer(self.member)
        client.force_login(self.member)
        old_access = client._credentials["HTTP_AUTHORIZATION"]
        response = client.patch(
            "/api/v1/members/me", {"mb_email": "moved@example.test", "mb_password_current": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertNotIn("_auth_user_id", client.session)
        stale = APIClient()
        stale.credentials(HTTP_AUTHORIZATION=old_access)
        self.assertEqual(stale.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(stale.get("/api/v1/members/me").status_code, 401)
        # The e-mail change revoked the tokens for good: certifying the new address later does not
        # bring the old access token back (the member signs in again).
        Profile.objects.filter(user=self.member).update(email_certify=timezone.now())
        self.assertEqual(stale.get("/api/v1/auth/me").status_code, 401)

    def test_the_leave_password_check_is_throttled(self):
        client = self.client_for(self.member)
        codes = [client.post(LEAVE_URL, {"mb_password": "wrong-password"}, format="json").status_code for _ in range(8)]
        self.assertIn(429, codes)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_the_profile_password_check_is_throttled_but_plain_edits_are_not(self):
        client = self.client_for(self.member)
        for index in range(8):
            response = client.patch("/api/v1/members/me", {"mb_name": f"Name {index}"}, format="json")
            self.assertEqual(response.status_code, 200)
        codes = [
            client.patch(
                "/api/v1/members/me", {"mb_email": "x@example.test", "mb_password_current": "bad"}, format="json"
            ).status_code
            for _ in range(8)
        ]
        self.assertIn(429, codes)

    def test_the_certify_endpoint_only_accepts_post(self):
        self.set_config("cf_use_email_certify", 1)
        token = "9" * 32 + f".{int(timezone.now().timestamp())}"
        self.uncertify(self.member, token)
        response = APIClient().get(CERTIFY_URL, {"mb_id": "hard_member", "token": token})
        self.assertEqual(response.status_code, 405)
        self.assertIsNone(self.profile(self.member).email_certify)

    def test_a_non_ascii_token_is_a_bad_request_not_a_crash(self):
        self.set_config("cf_use_email_certify", 1)
        self.uncertify(self.member, "a" * 32 + ".1700000000")
        client = APIClient(raise_request_exception=False)
        response = client.post(CERTIFY_URL, {"mb_id": "hard_member", "token": "토큰값"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_the_certify_endpoint_is_throttled(self):
        codes = [self.certify({"mb_id": "hard_member", "token": f"{index:032d}.1"}).status_code for index in range(15)]
        self.assertIn(429, codes)

    def test_registration_never_certifies_a_member_who_must_certify(self):
        self.set_config("cf_use_email_certify", 1)
        seen = {}

        def check_state(request, user, token, changed=False):
            profile = Profile.objects.get(user=user)
            seen["certified"] = profile.email_certify
            seen["token"] = profile.email_certify_token
            return False

        with mock.patch("gnu_jango.api.v1_auth.send_email_certify_mail", side_effect=check_state):
            response = self.register()
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertIsNone(seen["certified"])
        self.assertTrue(seen["token"])
        self.assertIsNone(self.profile(self.user_model.objects.get(username="life_member")).email_certify)
