import hashlib
import tempfile
import warnings
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.template import Context, Template
from django.core.management import call_command

from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file
from gnu_jango.api.community_common import _safe_int as community_safe_int
from gnu_jango.api.shop_common import safe_int as shop_safe_int
from gnu_jango.api.v1_board import _safe_int as board_safe_int
from gnu_jango.bbs import utils as bbs_utils
from gnu_jango.bbs.utils import get_next_num
from gnu_jango.config import Config
from gnu_jango.config.models import Config as ConfigModel
from gnu_jango.core.management.commands import migrate_gnuboard5
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as ImportCommand
from gnu_jango.core.privacy import (
    anonymize_ip_address,
    ip_address_for_storage,
    is_bot_user_agent,
    normalize_ip_address,
    should_skip_user_agent,
)
from gnu_jango.shop.sms import icode
from gnu_jango.templatetags import widgets
from gnu_jango.users.models import Profile
from gnu_jango.utils import lib, users


class BoardNumberHelpersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(gr_id="helper-tests", gr_subject="Helper tests")
        cls.board_one = Board.objects.create(
            group=cls.group, bo_subject="Board one", bo_table="helper_one", bo_skin="basic"
        )
        cls.board_two = Board.objects.create(
            group=cls.group, bo_subject="Board two", bo_table="helper_two", bo_skin="basic"
        )

    def make_post(self, board, number):
        now = timezone.now()
        return Post.objects.create(
            board=board,
            wr_num=number,
            wr_subject=f"Post {number}",
            wr_datetime=now,
            wr_last=now,
        )

    def test_next_post_number_is_scoped_to_the_requested_board(self):
        self.make_post(self.board_one, -12)
        self.make_post(self.board_two, -100)

        self.assertEqual(get_next_num(board_id=self.board_one.pk), -13)
        self.assertEqual(get_next_num(bo_table=self.board_one.bo_table), -13)

    def test_next_comment_number_is_scoped_to_the_requested_board(self):
        post_one = self.make_post(self.board_one, -1)
        post_two = self.make_post(self.board_two, -1)
        Comment.objects.create(board=self.board_one, post=post_one, order_num=-7)
        Comment.objects.create(board=self.board_two, post=post_two, order_num=-40)

        self.assertEqual(get_next_num(is_comment=True, board_id=self.board_one.pk), -8)

    def test_legacy_display_helpers_keep_urls_and_image_types_compatible(self):
        self.assertEqual(bbs_utils.get_board_skin_path(self.board_one), "skin/board/basic/")
        self.assertEqual(
            bbs_utils.get_board_skin_path(self.board_one, is_register_statics=True),
            "board/basic/",
        )
        self.assertEqual(bbs_utils.get_pretty_url("board name"), "/bbs/board%20name")
        self.assertEqual(bbs_utils.get_pretty_url("board", "17"), "/bbs/board/17")
        self.assertEqual(bbs_utils.get_image_type_number("image/webp"), 18)
        self.assertEqual(bbs_utils.get_image_type_number("image/unknown"), 0)
        self.assertEqual(bbs_utils.generate_wr_slug("한글 제목", board_id=self.board_one.pk), "한글-제목")

    def test_image_preview_respects_board_width_and_post_display_name(self):
        self.board_one.bo_image_width = 100
        file_row = SimpleNamespace(bf_type=1, url="/media/photo.jpg")

        preview = bbs_utils.view_file_link(
            file_row,
            width=200,
            height=80,
            content="photo",
            board=self.board_one,
        )

        self.assertIn("width='100' height='40'", preview)
        self.assertIn('src="/media/photo.jpg"', preview)
        self.assertEqual(
            bbs_utils.board_display_name(self.board_one, SimpleNamespace(wr_name="Writer")),
            "Writer",
        )


class UtilityLibraryTests(SimpleTestCase):
    def test_mobile_detection_is_isolated_per_request(self):
        factory = RequestFactory()
        mobile = factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile")
        desktop = factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0")

        self.assertTrue(lib.is_mobile(mobile))
        self.assertFalse(lib.is_mobile(desktop))
        self.assertTrue(lib.is_mobile(mobile))

    def test_mobile_skin_path_uses_the_request_device(self):
        factory = RequestFactory()
        mobile = factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile")
        desktop = factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0")

        self.assertEqual(lib.get_skin_path("member", "basic", mobile), f"{lib.defaults.MOBILE_SKIN_DIR}/member/basic")
        self.assertEqual(lib.get_skin_path("member", "basic", desktop), f"{lib.defaults.SKIN_DIR}/member/basic")

    def test_search_font_escapes_regex_delimiters_and_keeps_markup_untouched(self):
        highlighted = lib.search_font("a/b|c", '<a href="a/b|c">a/b|c</a>')
        case_insensitive = lib.search_font("a/b|c", "A/B|C")

        self.assertEqual(
            highlighted,
            '<a href="a/b|c"><b class="sch_word">a/b|c</b></a>',
        )
        self.assertEqual(case_insensitive, '<b class="sch_word">A/B|C</b>')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_client_ip_ignores_forwarded_header_without_trusted_proxies(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="192.0.2.9", HTTP_X_FORWARDED_FOR="198.51.100.1"
        )

        self.assertEqual(lib.get_client_ip(request), "192.0.2.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_client_ip_uses_the_configured_proxy_hop(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="203.0.113.3", HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.2"
        )

        self.assertEqual(lib.get_client_ip(request), "198.51.100.1")

    def test_base_conversion_supports_zero_negative_values_and_validates_base(self):
        self.assertEqual(lib.to_base(0, 16), "0")
        self.assertEqual(lib.to_base(-31, 16), "-1f")
        with self.assertRaises(ValueError):
            lib.to_base(12, 1)

    def test_url_merge_preserves_old_values_without_mutating_or_overriding_new_values(self):
        params = {"page": "2", "tags": ["one", "two"]}
        merged = lib.get_params_merge_url(params, "https://example.test/posts?page=1&keep=yes")

        query = parse_qs(urlparse(merged).query)
        self.assertEqual(query, {"page": ["2"], "keep": ["yes"], "tags": ["one", "two"]})
        self.assertEqual(params, {"page": "2", "tags": ["one", "two"]})

    def test_text_levels_and_base_conversion_helpers_cover_boundaries(self):
        self.assertEqual(lib.get_text("<b>hello</b>"), "&lt;b&gt;hello&lt;/b&gt;")
        self.assertEqual(lib.get_levels_choices(2, 4), [(2, 2), (3, 3), (4, 4)])
        self.assertEqual(lib.cut_str("abcdef", 3), "abc…")
        self.assertEqual(lib.chng_frm_base("ff", 16, 10), "255")
        self.assertEqual(lib.chng_frm_base("bad", 10, 2), 0)
        with self.assertRaises(ValueError):
            lib.chng_frm_base("10", 1, 10)

    def test_module_skin_and_template_path_helpers_resolve_expected_paths(self):
        self.assertEqual(
            lib.import_module_attr("gnu_jango.defaults.SKIN_DIR"),
            lib.defaults.SKIN_DIR,
        )
        self.assertEqual(lib.get_template_replace_path("skin/member/basic/"), "member/basic/")
        with patch.object(lib, "config", SimpleNamespace(cf_theme="nextjs_default")):
            self.assertEqual(lib.get_template_theme_path(), "theme/nextjs_default")
            self.assertEqual(
                lib.get_template_theme_mobile_path(),
                "theme/nextjs_default/mobile",
            )
        with patch.object(lib, "config", SimpleNamespace(cf_theme="test-theme")):
            with patch.object(lib.os.path, "isdir", return_value=False):
                request = RequestFactory().get(
                    "/", HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile"
                )
                self.assertEqual(
                    lib.get_skin_path("member", "theme/basic", request),
                    "theme/test-theme/mobile/member/basic",
                )

    def test_password_helpers_round_trip_hashes(self):
        encoded = lib.get_encrypt_string("example-password")

        self.assertTrue(lib.check_password("example-password", encoded))
        self.assertFalse(lib.check_password("wrong-password", encoded))


class RequestIntegerParsingTests(SimpleTestCase):
    def test_safe_integer_helpers_use_the_default_for_infinite_numbers(self):
        for safe_int in (board_safe_int, community_safe_int, shop_safe_int):
            with self.subTest(helper=safe_int.__module__):
                self.assertEqual(safe_int(float("inf"), 17), 17)

    def test_safe_integer_helpers_reject_values_outside_the_database_integer_range(self):
        oversized = "9" * 100
        for safe_int in (board_safe_int, community_safe_int, shop_safe_int):
            with self.subTest(helper=safe_int.__module__):
                self.assertEqual(safe_int(oversized, 17), 17)


class UserHelperTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="helper-user", email="helper@example.test", password="test-password"
        )
        self.profile = self.user.profile
        self.profile.nickname = "Long nickname"
        self.profile.realname = "Real Person"
        self.profile.user_point = 35
        self.profile.save()

    def test_profile_helpers_return_the_requested_name_and_slice(self):
        self.assertEqual(users.get_user_nickname(self.user, 4), "Long")
        self.assertEqual(users.get_user_realname(self.user, 5), "Real ")
        self.assertEqual(users.get_user_point(self.user), 35)
        self.assertEqual(users.username_text_name(self.user), "Long nickname")

    def test_missing_users_and_profiles_use_safe_defaults(self):
        self.assertIsNone(users.username_exists_info(pk=99999999))
        self.assertIsNone(users.username_exists_info(pk="not-an-id"))
        Profile.objects.filter(user=self.user).delete()
        user_without_profile = get_user_model().objects.get(pk=self.user.pk)

        self.assertEqual(users.get_user_point(user_without_profile), 0)
        self.assertEqual(users.get_user_nickname(user_without_profile), "")
        self.assertEqual(users.get_user_realname(user_without_profile), "")
        self.assertEqual(users.username_text_name(user_without_profile), "helper-user")
        self.assertFalse(users.get_sideview_data(99999999)["is_user"])

    def test_user_lookup_level_gravatar_and_sideview_do_not_expose_account_email(self):
        self.assertTrue(users.username_exists("helper-user"))
        self.assertFalse(users.username_exists("missing-user"))
        self.assertEqual(users.username_exists_info(username="helper-user"), self.user)
        self.assertEqual(users.get_user(self.user.pk), self.user)
        self.assertEqual(users.get_user_level(self.user), 1)
        self.assertEqual(users.get_user_level(SimpleNamespace(is_authenticated=False)), 1)

        with override_settings(GRAVATAR_PROVIDER_URL="https://avatar.example.test/"):
            avatar = users.get_gravatar_url("HELPER@example.test", size=24)
        self.assertEqual(
            avatar,
            "https://avatar.example.test/"
            + hashlib.md5(b"helper@example.test").hexdigest()
            + "?s=48&d=mm",
        )

        request = RequestFactory().get("/members/")
        with patch.object(users, "config", SimpleNamespace(cf_use_user_icon=0)):
            sideview = users.get_sideview_data(
                self.user,
                email="contact@example.test",
                homepage="https://example.test/",
                request=request,
            )

        self.assertEqual(sideview["name"], "Long nickname")
        self.assertEqual(sideview["email"], "")
        self.assertEqual(sideview["mail_url"], "#")
        self.assertEqual(sideview["homepage_url"], "#")
        self.assertEqual(sideview["absolute_user_icon_url"], "")

    def test_user_icon_uses_static_fallback_without_an_uploaded_icon(self):
        with patch.object(users, "static_url_version", return_value="/static/no-profile.gif") as version:
            result = users.user_icon_url(SimpleNamespace())

        self.assertEqual(result, "/static/no-profile.gif")
        version.assert_called_once_with("img/no_profile.gif")


class WidgetHelperTests(SimpleTestCase):
    def test_dictionary_and_list_filters_handle_missing_or_invalid_keys(self):
        self.assertEqual(widgets.dict_key({"present": 3}, "present"), 3)
        self.assertIsNone(widgets.dict_key({"present": 3}, "missing"))
        self.assertEqual(widgets.list_key(["zero", "one"], "1"), "one")
        self.assertIsNone(widgets.list_key(["zero"], "bad-index"))

    def test_sideview_template_tag_passes_the_current_request(self):
        request = HttpRequest()
        request.path = "/members/"
        template = Template("{% load widgets %}{% get_sideview writer as sideview %}{{ sideview }}")
        with patch.object(widgets, "get_user_sideview", return_value="side menu") as sideview:
            rendered = template.render(Context({"request": request, "writer": object()}))

        self.assertEqual(rendered, "side menu")
        self.assertIs(sideview.call_args.kwargs["request"], request)

    def test_profile_image_attributes_are_html_escaped(self):
        with patch.object(widgets, "avatar_url", return_value='avatar.jpg" onerror="alert(1)'):
            rendered = str(
                widgets.get_member_profile_img(
                    object(), width=32, height=32, alt='" onload="alert(1)', title="profile"
                )
            )

        self.assertIn("&quot;", rendered)
        self.assertNotIn(' onerror="', rendered)
        self.assertNotIn(' onload="', rendered)

    def test_small_filters_cookie_and_selection_tags_handle_values(self):
        request = RequestFactory().get("/")
        request.COOKIES["notice_4"] = "closed"
        context = {"request": request}

        self.assertEqual(widgets.list_key(["zero"], "0"), "zero")
        self.assertEqual(widgets.to_class_name(request), "WSGIRequest")
        self.assertEqual(widgets.conv_content("<p>x</p>", 1), "<p>x</p>")
        self.assertEqual(widgets.get_cookie(context, "notice_4"), "closed")
        self.assertEqual(widgets.pop_up_cookie(context, "notice_", 4), "closed")
        self.assertEqual(widgets.get_selected("same", "same"), ' selected="selected"')
        self.assertEqual(widgets.get_selected("one", "two"), "")
        self.assertEqual(len(widgets.get_uuid()), 32)

    def test_avatar_uses_gravatar_or_static_fallback(self):
        member = SimpleNamespace(email="member@example.test")
        with patch.object(widgets, "get_gravatar_url", return_value="https://avatar.test/member"):
            self.assertEqual(widgets.avatar_url(member, width=32), "https://avatar.test/member")

        with patch.object(widgets, "get_gravatar_url", return_value=None):
            with patch.object(widgets, "static_url_version", return_value="/static/no-profile.gif"):
                self.assertEqual(widgets.avatar_url(member), "/static/no-profile.gif")

    def test_latest_post_builder_redacts_secret_post_fields(self):
        row = SimpleNamespace(
            wr_password="secret-password",
            wr_email="member@example.test",
            wr_option="html1,secret",
            wr_content="secret body",
            wr_link1="https://private.example.test/",
            wr_link2="https://private2.example.test/",
            file=object(),
        )
        board = SimpleNamespace(id=4)
        with patch.object(widgets, "get_bbs_list", side_effect=lambda post, *_a, **_k: post):
            latest_posts = widgets.build_latest_posts(board, rows=3, queryset=[row])

        self.assertEqual(latest_posts, [row])
        self.assertEqual(row.wr_password, "")
        self.assertEqual(row.wr_email, "")
        self.assertEqual(row.wr_content, "")
        self.assertEqual(row.wr_link1, "")
        self.assertEqual(row.wr_link2, "")
        self.assertIsNone(row.file)


class SiteConfigDatabaseTests(TestCase):
    def test_database_values_override_defaults_and_unknown_names_are_ignored(self):
        ConfigModel.objects.create(name="cf_title", value="Imported site")
        ConfigModel.objects.create(name="cf_point_term", value="not-an-integer")
        ConfigModel.objects.create(name="unknown_legacy_setting", value="ignored")
        site_config = Config()

        values = site_config.get_all()
        metadata = site_config.get_conf_all()

        self.assertEqual(values["cf_title"], "Imported site")
        self.assertEqual(values["cf_point_term"], 0)
        self.assertNotIn("unknown_legacy_setting", values)
        self.assertEqual(metadata["cf_title"]["value"], "Imported site")
        self.assertEqual(metadata["cf_title"]["type"], "str")


class SiteConfigConversionTests(SimpleTestCase):
    def test_invalid_values_fall_back_for_tuple_and_dictionary_schemas(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            tuple_value = Config._to_python((12, "int", "Number"), "not-a-number")
            dict_value = Config._to_python(
                {"type": "int", "default": 7}, "sensitive-placeholder"
            )

        self.assertEqual(tuple_value, 12)
        self.assertEqual(dict_value, 7)
        self.assertTrue(captured)
        self.assertNotIn("sensitive-placeholder", str(captured[0].message))

    def test_boolean_settings_accept_common_false_spellings(self):
        for value in ("False", "false", "0", "no", "off", ""):
            self.assertFalse(Config._to_python((True, "bool"), value))
        self.assertTrue(Config._to_python((False, "bool"), "yes"))


class PrivacyHelperTests(SimpleTestCase):
    def test_ip_normalization_and_anonymization_cover_ipv4_and_ipv6(self):
        self.assertEqual(normalize_ip_address(" [2001:db8::1]:443 "), "2001:db8::1")
        self.assertEqual(normalize_ip_address("192.0.2.44:8080"), "192.0.2.44")
        self.assertIsNone(normalize_ip_address("not-an-address"))
        self.assertEqual(anonymize_ip_address("192.0.2.44"), "192.0.2.0")
        self.assertEqual(anonymize_ip_address("2001:db8:abcd:1234::9"), "2001:db8:abcd:1234::")

    @override_settings(ADMIN_VISIT_LOG_MASK_IP=True, ADMIN_VISIT_LOG_EXCLUDE_BOTS=True)
    def test_storage_mask_and_bot_filter_follow_settings(self):
        self.assertEqual(ip_address_for_storage("198.51.100.9"), "198.51.100.0")
        self.assertTrue(is_bot_user_agent("Googlebot/2.1"))
        self.assertTrue(should_skip_user_agent("Googlebot/2.1"))
        self.assertFalse(should_skip_user_agent("Mozilla/5.0"))

    @override_settings(ADMIN_VISIT_LOG_MASK_IP=False, ADMIN_VISIT_LOG_EXCLUDE_BOTS=False)
    def test_storage_can_keep_full_ip_and_include_bot_visits(self):
        self.assertEqual(ip_address_for_storage("198.51.100.9"), "198.51.100.9")
        self.assertFalse(should_skip_user_agent("Googlebot/2.1"))


class ICodeSmsTests(SimpleTestCase):
    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_packet_has_fixed_fields_and_safe_euc_kr_message_boundary(self):
        packet = icode._build_packet("testid", "testpw", "01012345678", "0212345678", "가" * 50)

        self.assertTrue(packet.startswith(b"01144 "))
        self.assertEqual(len(packet), 6 + 10 + 10 + 11 + 11 + 10 + 12 + 80)
        message = packet[-80:].rstrip(b" ")
        self.assertLessEqual(len(message), 80)
        self.assertEqual(message.decode("euc_kr"), "가" * 40)

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_invalid_recipient_is_rejected_without_opening_a_socket(self):
        with patch.object(icode.socket, "create_connection") as create_connection:
            result = icode.send_sms("12345", "0212345678", "hello")

        self.assertEqual((result.status, result.provider_code), ("rejected", "invalid_request"))
        create_connection.assert_not_called()

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_response_is_read_in_chunks_and_provider_acceptance_is_returned(self):
        response = b"0223  00" + b"01012345678" + b"accepted  "
        connection = _FakeConnection([response[:7], response[7:21], response[21:]])
        with patch.object(icode.socket, "create_connection", return_value=connection):
            result = icode.send_sms("010-1234-5678", "02-1234-5678", "hello")

        self.assertEqual((result.status, result.provider_code), ("accepted", "accepted"))
        self.assertEqual(len(connection.sent), 1)
        self.assertEqual(len(connection.sent[0]), 6 + 10 + 10 + 11 + 11 + 10 + 12 + 80)

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT="bad-port",
    )
    def test_invalid_port_is_reported_as_configuration_error(self):
        with self.assertRaises(icode.ICodeConfigurationError):
            icode._configuration()

    def test_phone_and_callback_validation_reject_invalid_numbers(self):
        self.assertEqual(icode._phone_digits("010-1234-5678"), "01012345678")
        self.assertEqual(icode._callback_digits("02-1234-5678"), "0212345678")
        with self.assertRaises(ValueError):
            icode._phone_digits("02-1234-5678")
        with self.assertRaises(ValueError):
            icode._callback_digits("123")

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_gateway_rejection_and_unknown_response_are_distinguished(self):
        for response, expected in ((b"0223  05rejected", "rejected"), (b"unexpected", "unknown")):
            connection = _FakeConnection([response])
            with patch.object(icode.socket, "create_connection", return_value=connection):
                result = icode.send_sms("01012345678", "0212345678", "hello")
            self.assertEqual(result.status, expected)

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_connect_timeout_is_rejected_before_submission(self):
        with patch.object(icode.socket, "create_connection", side_effect=TimeoutError):
            result = icode.send_sms("01012345678", "0212345678", "hello")

        self.assertEqual((result.status, result.provider_code), ("rejected", "connect_timeout"))

    @override_settings(
        G5_SMS_PROVIDER="icode", G5_ICODE_ID="testid", G5_ICODE_PASSWORD="testpw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_timeout_after_submission_has_unknown_delivery_status(self):
        connection = _FakeConnection([])
        connection.recv = Mock(side_effect=TimeoutError)
        with patch.object(icode.socket, "create_connection", return_value=connection):
            result = icode.send_sms("01012345678", "0212345678", "hello")

        self.assertEqual((result.status, result.provider_code), ("unknown", "timeout"))


class _FakeConnection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, packet):
        self.sent.append(packet)

    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b""


class ImporterHelperTests(SimpleTestCase):
    def test_php_configuration_resolves_prefixes_and_supplies_default_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "dbconfig.php"
            config_path.write_text(
                "define('G5_MYSQL_HOST', '127.0.0.1');\n"
                "define('G5_MYSQL_DB', 'demo');\n"
                "define('G5_TABLE_PREFIX', 'demo_');\n"
                "$g5['member_table'] = G5_TABLE_PREFIX.'member';\n"
                "$g5['write_prefix'] = G5_TABLE_PREFIX.'write_';\n",
                encoding="utf-8",
            )

            parsed = migrate_gnuboard5.parse_php_config(config_path)

        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(parsed["tables"]["member_table"], "demo_member")
        self.assertEqual(parsed["tables"]["write_prefix"], "demo_write_")
        self.assertEqual(parsed["tables"]["g5_shop_order_table"], "g5_shop_order")

    def test_importer_helpers_preserve_unicode_and_reject_unsafe_sql_identifiers(self):
        self.assertEqual(migrate_gnuboard5.text({"name": "가나다"}, "name", max_length=2), "가나")
        self.assertEqual(migrate_gnuboard5.integer({"count": "bad"}, "count", 4), 4)
        self.assertEqual(migrate_gnuboard5.bool_char({"enabled": "false"}, "enabled"), False)
        with self.assertRaises(ValueError):
            migrate_gnuboard5._safe_table("member; DROP TABLE member")

    def test_importer_scalar_date_and_reply_converters_handle_malformed_values(self):
        self.assertEqual(migrate_gnuboard5.scalar({"value": None}, "value", "fallback"), "fallback")
        self.assertEqual(migrate_gnuboard5.text({"value": None}, "value", "fallback"), "fallback")
        self.assertEqual(migrate_gnuboard5.integer({"value": "bad"}, "value", 9), 9)
        self.assertFalse(migrate_gnuboard5.bool_char({"value": " n "}, "value"))
        self.assertTrue(migrate_gnuboard5.bool_char({"value": ""}, "value", default=True))
        self.assertEqual(migrate_gnuboard5.post_reply_marker({"wr_reply": "0"}), "")
        self.assertEqual(migrate_gnuboard5.post_reply_marker({"wr_reply": "  A  "}), "A")
        with self.assertRaises(ValueError):
            migrate_gnuboard5.post_reply_marker({"wr_reply": "A" * 11})

        self.assertIsNone(migrate_gnuboard5.date_value("0000-00-00 00:00:00"))
        self.assertEqual(migrate_gnuboard5.date_value("2026-10-12" ).isoformat(), "2026-10-12")
        self.assertIsNone(migrate_gnuboard5.ymd_date_value("00000000"))
        self.assertEqual(
            migrate_gnuboard5.ymd_date_value("2026-10-12").isoformat(), "2026-10-12"
        )
        self.assertIsNone(migrate_gnuboard5.optional_datetime_value("0000-00-00 00:00:00"))
        self.assertIsNotNone(migrate_gnuboard5.datetime_value("not-a-date"))

    def test_importer_table_reader_and_count_helpers_use_validated_sql_names(self):
        cursor = Mock()
        cursor.fetchall.return_value = [{"mb_id": "member-1"}]
        cursor.fetchone.side_effect = [{"cnt": "2"}, {"table": "member"}, None]

        self.assertEqual(
            migrate_gnuboard5.fetch_rows(cursor, "member", limit="3"),
            [{"mb_id": "member-1"}],
        )
        self.assertEqual(migrate_gnuboard5.count_table(cursor, "member"), 2)
        self.assertTrue(migrate_gnuboard5.table_exists(cursor, "member"))
        self.assertFalse(migrate_gnuboard5.table_exists(cursor, "missing"))
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "SELECT * FROM `member` LIMIT 3")
        self.assertEqual(
            cursor.execute.call_args_list[1].args[0],
            "SELECT COUNT(*) AS cnt FROM `member`",
        )
        self.assertEqual(cursor.execute.call_args_list[2].args, ("SHOW TABLES LIKE %s", ("member",)))
        with self.assertRaises(ValueError):
            migrate_gnuboard5.fetch_rows(cursor, "member where 1=1")

    def test_php_table_expression_secret_mask_and_missing_file_are_explicit(self):
        self.assertEqual(
            migrate_gnuboard5.resolve_php_table_expression(
                "G5_TABLE_PREFIX.'write_'", "legacy_", "shop_"
            ),
            "legacy_write_",
        )
        self.assertEqual(migrate_gnuboard5.mask_secret("abcd"), "a**d")
        self.assertEqual(migrate_gnuboard5.mask_secret("x"), "*")
        self.assertEqual(migrate_gnuboard5.mask_secret(""), "")
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.php"
            with self.assertRaises(migrate_gnuboard5.CommandError):
                migrate_gnuboard5.parse_php_config(missing)

    def test_mysql_connection_uses_dictionary_rows_without_opening_a_real_connection(self):
        configuration = {
            "host": "mysql.invalid",
            "user": "readonly",
            "password": "hidden-test-value",
            "database": "legacy",
        }
        dictionary_cursor = object()
        connect = Mock(return_value="connection")
        driver = SimpleNamespace(
            connect=connect,
            cursors=SimpleNamespace(DictCursor=dictionary_cursor),
        )

        with patch.object(migrate_gnuboard5, "import_pymysql", return_value=driver):
            connection = migrate_gnuboard5.mysql_connection(configuration)

        self.assertEqual(connection, "connection")
        connect.assert_called_once_with(
            host="mysql.invalid",
            user="readonly",
            password="hidden-test-value",
            database="legacy",
            charset="utf8mb4",
            cursorclass=dictionary_cursor,
        )

    def test_importer_selection_and_counts_report_missing_source_tables(self):
        command = ImportCommand()
        configuration = {
            "table_prefix": "legacy_",
            "shop_prefix": "shop_",
            "tables": {
                "member_table": "legacy_member",
                "g5_shop_item_table": "shop_item",
                "config_table": "legacy_config",
                "g5_shop_default_table": "shop_default",
            },
        }
        command.source_root = Path("missing-source")
        selected = {"member", "member_avatars", "shop_product_metrics"}

        with patch.object(migrate_gnuboard5, "table_exists", return_value=False):
            counts = command.get_counts(Mock(), configuration, selected)
            imported = command.import_selected(Mock(), configuration, selected, limit=5)

        self.assertEqual(counts, {"member": None, "member_avatars": None, "shop_product_metrics": None})
        self.assertEqual(imported, {"member": 0, "member_avatars": 0, "shop_product_metrics": 0})

    def test_importer_prints_a_masked_password_and_selected_table_mapping(self):
        command = ImportCommand()
        command.stdout = StringIO()
        configuration = {
            "host": "mysql.invalid",
            "database": "legacy",
            "user": "readonly",
            "password": "very-secret-value",
            "table_prefix": "legacy_",
            "shop_prefix": "shop_",
            "tables": {
                "member_table": "legacy_member",
                "g5_shop_item_table": "shop_item",
                "config_table": "legacy_config",
                "g5_shop_default_table": "shop_default",
            },
        }

        command.print_config(Path("source/data/dbconfig.php"), configuration, {"member", "public_config"})
        rendered = command.stdout.getvalue()

        self.assertIn("legacy_member", rendered)
        self.assertIn("legacy_config + shop_default", rendered)
        self.assertIn(migrate_gnuboard5.mask_secret("very-secret-value"), rendered)
        self.assertNotIn("very-secret-value", rendered)

    def test_dry_run_can_skip_mysql_and_never_prints_the_configured_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = root / "data"
            data.mkdir()
            (data / "dbconfig.php").write_text(
                "define('G5_MYSQL_HOST', '127.0.0.1');\n"
                "define('G5_MYSQL_USER', 'readonly');\n"
                "define('G5_MYSQL_PASSWORD', 'placeholder-secret');\n"
                "define('G5_MYSQL_DB', 'demo');\n",
                encoding="utf-8",
            )
            from io import StringIO

            output = StringIO()
            call_command(
                "migrate_gnuboard5",
                source_root=str(root),
                only=["member"],
                skip_counts=True,
                stdout=output,
            )

        self.assertIn("Counts skipped", output.getvalue())
        self.assertNotIn("placeholder-secret", output.getvalue())
        self.assertIn("readonly", output.getvalue())


class ImporterPostMappingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        group = Group.objects.create(gr_id="import-helper", gr_subject="Importer tests")
        cls.board = Board.objects.create(
            group=group,
            bo_subject="Importer test board",
            bo_table="import_helper",
            bo_skin="basic",
        )

    def test_import_preserves_combined_options_unicode_and_truncates_bounded_fields(self):
        command = ImportCommand()
        row = {
            "wr_id": 9001,
            "wr_num": -4,
            "wr_reply": "0",
            "wr_parent": 9001,
            "wr_option": "html1,secret",
            "wr_subject": "한" * 270,
            "wr_content": "게시글 본문",
            "wr_name": "나" * 270,
            "wr_email": "",
            "wr_homepage": "",
            "wr_datetime": "2026-10-01 12:00:00",
            "wr_last": "",
            "wr_ip": "192.0.2.2",
        }

        post = command.upsert_post(self.board, row)
        reimported = command.upsert_post(self.board, {**row, "wr_subject": "다시 가져온 글"})

        self.assertEqual(post.pk, reimported.pk)
        self.assertEqual(Post.objects.filter(board=self.board, legacy_wr_id=9001).count(), 1)
        self.assertEqual(reimported.wr_subject, "다시 가져온 글")
        self.assertEqual(reimported.wr_option, "html1,secret")
        self.assertEqual(len(Post.objects.get(pk=post.pk).wr_name), 255)
        self.assertEqual(Post.objects.get(pk=post.pk).wr_content, "게시글 본문")


class ImporterMemberMappingTests(TestCase):
    def test_source_member_dates_duplicate_identity_fields_and_reimport_are_preserved(self):
        User = get_user_model()
        command = ImportCommand()
        source_rows = [
            {
                "mb_id": "legacy-a",
                "mb_password": "not-a-supported-hash",
                "mb_name": "Fixture Member A",
                "mb_nick": "Shared nickname",
                "mb_email": "shared@example.test",
                "mb_level": "2",
                "mb_leave_date": "",
                "mb_intercept_date": "",
                "mb_datetime": "2026-10-01 12:00:00",
                "mb_today_login": "",
                "mb_nick_date": "",
                "mb_homepage": "https://a.example.test/",
                "mb_hp": "01012345678",
                "mb_zip1": "062",
                "mb_zip2": "36",
                "mb_addr1": "Fixture address",
                "mb_addr2": "Fixture detail",
                "mb_addr_jibeon": "Fixture parcel address",
                "mb_point": "35",
                "mb_email_certify": "2026-09-01 10:00:00",
                "mb_email_certify2": "fixture-token",
                "mb_open": "1",
                "mb_open_date": "2026-09-02",
            },
            {
                "mb_id": "legacy-b",
                "mb_password": "",
                "mb_name": "Fixture Member B",
                "mb_nick": "Shared nickname",
                "mb_email": "shared@example.test",
                "mb_level": "3",
                "mb_leave_date": "20261011",
                "mb_intercept_date": "",
                "mb_datetime": "2026-10-02 12:00:00",
                "mb_today_login": "",
                "mb_nick_date": "",
                "mb_homepage": "",
                "mb_hp": "",
                "mb_zip1": "",
                "mb_zip2": "",
                "mb_addr1": "",
                "mb_addr2": "",
                "mb_addr_jibeon": "",
                "mb_point": "0",
                "mb_email_certify": "",
                "mb_email_certify2": "",
                "mb_open": "0",
                "mb_open_date": "",
            },
        ]

        with tempfile.TemporaryDirectory() as source_root:
            command.source_root = Path(source_root)
            self.assertEqual(command.import_members(source_rows), 2)
            self.assertEqual(command.import_members(source_rows), 2)

        first = User.objects.get(username="legacy-a")
        second = User.objects.get(username="legacy-b")
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(first.is_active)
        self.assertFalse(second.is_active)
        self.assertEqual(first.email, "shared@example.test")
        self.assertEqual(second.email, "shared+legacy-b@example.test")
        self.assertEqual(first.profile.nickname, "Shared nickname")
        self.assertEqual(second.profile.nickname, "Shared nickname-2")
        self.assertEqual(first.profile.user_zip, "06236")
        self.assertEqual(first.profile.user_point, 35)
        self.assertEqual(first.profile.email_certify_token, "fixture-token")
        self.assertEqual(second.profile.leave_date.isoformat(), "2026-10-11")


class ImporterShopOrderMappingTests(TestCase):
    def test_unsigned_legacy_order_id_and_composite_values_round_trip_idempotently(self):
        from gnu_jango.shop.models import ShopOrder

        command = ImportCommand()
        source_row = {
            "od_id": "18446744073709551615",
            "mb_id": "missing-member",
            "od_name": "Fixture Buyer",
            "od_email": "not-an-email",
            "od_zip1": "062",
            "od_zip2": "36",
            "od_addr3": "",
            "od_addr_jibeon": "Fixture parcel address",
            "od_b_zip1": "987",
            "od_b_zip2": "65",
            "od_b_addr3": "",
            "od_b_addr_jibeon": "Fixture recipient parcel address",
            "od_cart_price": "12000",
            "od_coupon": "500",
            "od_cart_coupon": "250",
            "od_receipt_point": "40",
            "od_status": "완료",
            "od_settle_case": "bank",
            "od_time": "2026-10-11 12:30:00",
            "od_ip": "198.51.100.12",
        }

        self.assertEqual(command.import_shop_orders([source_row]), 1)
        order = ShopOrder.objects.get(pk="18446744073709551615")
        original_uid = order.uid
        self.assertEqual(order.od_zip, "06236")
        self.assertEqual(order.od_b_zip, "98765")
        self.assertEqual(order.od_addr3, "Fixture parcel address")
        self.assertEqual(order.od_b_addr3, "Fixture recipient parcel address")
        self.assertEqual(order.od_email, "")
        self.assertEqual(order.od_coupon, 500)  # od_cart_coupon comes from the coupon logs
        self.assertEqual(order.od_ip, "198.51.100.12")
        self.assertIsNone(order.user)

        self.assertEqual(command.import_shop_orders([{**source_row, "od_cart_price": "11000"}]), 1)
        order.refresh_from_db()
        self.assertEqual(ShopOrder.objects.count(), 1)
        self.assertEqual(order.od_cart_price, 11000)
        self.assertEqual(order.uid, original_uid)


class ImporterPublicConfigTests(TestCase):
    def test_public_branding_import_excludes_payment_and_provider_secrets(self):
        command = ImportCommand()
        config = {
            "tables": {
                "config_table": "legacy_config",
                "g5_shop_default_table": "legacy_shop_default",
            }
        }
        config_row = {
            "cf_title": "Fixture storefront",
            "cf_pg_service_key": "private-payment-sentinel",
        }
        shop_row = {
            "de_admin_company_name": "Fixture Company",
            "de_admin_company_owner": "Fixture Owner",
            "de_admin_company_addr": "Fixture Address",
            "de_admin_company_saupja_no": "123-45-67890",
            "de_admin_company_tel": "02-1234-5678",
            "de_admin_tongsin_no": "2026-TEST",
            "de_admin_info_name": "Fixture Support",
            "de_admin_info_email": "support@example.test",
            "de_bank_use": "1",
            "de_bank_account": "Fixture Bank Account",
            "de_pg_service_key": "private-pg-sentinel",
            "de_sms_password": "private-sms-sentinel",
            "de_cart_keep_term": "30",
            "de_hope_date_use": "1",
            "de_point_days": "not-a-number",
        }

        with patch.object(migrate_gnuboard5, "table_exists", return_value=True):
            with patch.object(
                migrate_gnuboard5,
                "fetch_rows",
                side_effect=[[config_row], [shop_row]],
            ):
                imported = command.import_public_config(Mock(), config)

        stored = dict(ConfigModel.objects.values_list("name", "value"))
        self.assertEqual(imported, 14)
        self.assertEqual(stored["de_cart_keep_term"], "30")
        self.assertEqual(stored["de_hope_date_use"], "1")
        self.assertNotIn("de_point_days", stored)
        self.assertEqual(stored["cf_title"], "Fixture storefront")
        self.assertEqual(stored["cf_company_name"], "Fixture Company")
        self.assertEqual(stored["de_bank_account"], "Fixture Bank Account")
        self.assertNotIn("cf_pg_service_key", stored)
        self.assertNotIn("de_pg_service_key", stored)
        self.assertNotIn("de_sms_password", stored)
        self.assertNotIn("private-payment-sentinel", stored.values())
        self.assertNotIn("private-pg-sentinel", stored.values())
        self.assertNotIn("private-sms-sentinel", stored.values())


class ImporterBoardWorkflowTests(TestCase):
    def setUp(self):
        group = Group.objects.create(gr_id="import-workflow", gr_subject="Importer workflow")
        self.board = Board.objects.create(
            group=group,
            bo_subject="Importer workflow board",
            bo_table="import_workflow",
            bo_skin="basic",
        )
        self.command = ImportCommand()

    def test_board_post_import_maps_posts_before_comments_and_is_idempotent(self):
        rows = [
            {
                "wr_id": 101,
                "wr_num": -1,
                "wr_reply": "0",
                "wr_parent": 101,
                "wr_is_comment": 0,
                "wr_subject": "Fixture post",
                "wr_content": "Fixture body",
                "wr_name": "Fixture author",
                "wr_datetime": "2026-10-01 12:00:00",
            },
            {
                "wr_id": 102,
                "wr_num": -1,
                "wr_reply": "",
                "wr_parent": 101,
                "wr_is_comment": 1,
                "wr_comment_reply": "A",
                "wr_content": "Fixture comment",
                "wr_name": "Fixture commenter",
                "wr_datetime": "2026-10-01 12:30:00",
            },
        ]

        with patch.object(self.command, "write_table_for_board", return_value="g5_write_import_workflow"):
            with patch.object(migrate_gnuboard5, "fetch_rows", return_value=rows):
                self.assertEqual(self.command.import_board_posts(Mock(), {}, limit=5), 2)
                self.assertEqual(self.command.import_board_posts(Mock(), {}, limit=5), 2)

        post = Post.objects.get(board=self.board, legacy_wr_id=101)
        comment = Comment.objects.get(board=self.board, post=post, order_num=102)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 1)
        self.assertEqual(Comment.objects.filter(board=self.board).count(), 1)
        self.assertEqual(post.wr_subject, "Fixture post")
        self.assertEqual(comment.parent, 101)
        self.assertEqual(comment.wr_content, "Fixture comment")

    def test_missing_source_attachment_keeps_metadata_and_reimport_updates_one_row(self):
        from django.utils import timezone

        post = Post.objects.create(
            board=self.board,
            legacy_wr_id=201,
            wr_parent=201,
            wr_subject="Fixture attachment post",
            wr_datetime=timezone.now(),
        )
        row = {
            "bo_table": self.board.bo_table,
            "wr_id": 201,
            "bf_no": 0,
            "bf_file": r"nested\fixture.png",
            "bf_source": "fixture-original.png",
            "bf_content": "Fixture attachment description",
            "bf_download": 4,
            "bf_fileurl": "",
            "bf_thumburl": "",
            "bf_filesize": 128,
            "bf_width": 64,
            "bf_height": 48,
            "bf_type": 3,
            "bf_datetime": "2026-10-01 12:00:00",
        }

        with tempfile.TemporaryDirectory() as source_root:
            self.command.source_root = Path(source_root)
            self.assertEqual(self.command.import_board_files([row]), 1)
            self.assertEqual(self.command.import_board_files([row]), 1)

        attachment = Post_file.objects.get(board=self.board, post=post, bf_no=0)
        post.refresh_from_db()
        self.assertEqual(Post_file.objects.filter(post=post).count(), 1)
        self.assertEqual(attachment.bf_file.name, "")
        self.assertEqual(attachment.bf_storage, "legacy_missing")
        self.assertEqual(attachment.bf_source, "fixture-original.png")
        self.assertEqual(attachment.bf_fileurl, "data/file/import_workflow/fixture.png")
        self.assertEqual(attachment.bf_filesize, 128)
        self.assertEqual(post.wr_file, 1)

