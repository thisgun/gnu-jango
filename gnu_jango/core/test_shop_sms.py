"""iCode SMS: the token (JSON) packet, the shop SMS settings, the order / restock / signup texts and
the operator test send. No test opens a socket: the transport is always replaced."""

import io
import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from gnu_jango.config.models import Config
from gnu_jango.core.management.commands import migrate_gnuboard5
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as ImportCommand
from gnu_jango.shop.models import (
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopShippingPolicy,
    ShopStockNotification,
    ShopStockNotificationSendLog,
)
from gnu_jango.shop.order_flow import move_order_status
from gnu_jango.shop.sms import icode, notifications, service
from gnu_jango.shop.sms.icode import ICodeSendResult

TOKEN = "token-private-sentinel"
SOCKET = "gnu_jango.shop.sms.icode.socket.create_connection"
TRANSPORT = "gnu_jango.shop.sms.service.icode.send_message"
NO_LEGACY = {"G5_ICODE_ID": "", "G5_ICODE_PASSWORD": "", "G5_ICODE_SERVER": ""}


class FakeConnection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, packet):
        self.sent.append(packet)

    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b""


def token_reply(recipient, message_id=b"12345678901"):
    return b"0225  00" + recipient.ljust(12).encode() + message_id


def decode_packet(packet):
    length = int(packet[2:6])
    body = packet[6:]
    assert len(body) == length
    return json.loads(body)


@override_settings(G5_SMS_PROVIDER="", G5_ICODE_TOKEN_KEY=TOKEN, **NO_LEGACY)
class TokenProtocolTests(SimpleTestCase):
    def test_packet_is_an_06_frame_with_php_style_ascii_json(self):
        packet, message_type = icode.build_token_packet(TOKEN, "010-1234-5678", "02-123-4567", "안녕 a/b")

        self.assertEqual(message_type, "SMS")
        self.assertTrue(packet.startswith(b"06"))
        self.assertTrue(packet.isascii())
        self.assertIn(b"a\\/b", packet)  # json_encode escapes "/"
        data = decode_packet(packet)
        self.assertEqual(data["key"], TOKEN)
        self.assertEqual(data["tel"], "01012345678")
        self.assertEqual(data["cb"], "021234567  ")  # FillSpace($strCallBack, 11)
        self.assertEqual(data["msg"], "안녕 a/b")
        self.assertEqual((data["title"], data["date"]), ("", ""))

    def test_sms_type_cuts_at_90_bytes_and_lms_keeps_up_to_2000_with_a_title(self):
        long_text = "가" * 100  # 200 bytes
        packet, message_type = icode.build_token_packet(TOKEN, "01012345678", "0212345678", long_text)
        self.assertEqual(message_type, "SMS")
        self.assertEqual(decode_packet(packet)["msg"], "가" * 45)

        packet, message_type = icode.build_token_packet(
            TOKEN, "01012345678", "0212345678", long_text, subject="<공지>\n안내", allow_lms=True
        )
        data = decode_packet(packet)
        self.assertEqual(message_type, "LMS")
        self.assertEqual(data["msg"], long_text)
        self.assertEqual(data["title"], "[공지] 안내")

        short_packet, short_type = icode.build_token_packet(TOKEN, "01012345678", "0212345678", "짧은 문자", allow_lms=True)
        self.assertEqual(short_type, "SMS")
        self.assertEqual(decode_packet(short_packet)["title"], "")

        huge = "a" * 5000
        packet, _ = icode.build_token_packet(TOKEN, "01012345678", "0212345678", huge, allow_lms=True)
        self.assertEqual(len(decode_packet(packet)["msg"]), icode.LMS_MAX_BYTES)

    def test_byte_counting_matches_youngcart_byte_check(self):
        self.assertEqual(icode.message_bytes("ab가\n"), 5)
        self.assertEqual(icode.cut_to_bytes("a가나", 4), "a가")
        self.assertEqual(icode.cut_to_bytes("a가나", 5), "a가나")
        self.assertEqual(icode.normalize_newlines("a\r\nb\rc"), "a\nb\nc")

    def test_accepted_reply_returns_the_message_id(self):
        reply = token_reply("01012345678")
        connection = FakeConnection([reply[:10], reply[10:]])
        with patch(SOCKET, return_value=connection) as create_connection:
            result = icode.send_message("010-1234-5678", "0212345678", "hello")

        self.assertEqual((result.status, result.provider_code, result.message_type), ("accepted", "12345678901", "SMS"))
        create_connection.assert_called_once_with(("211.172.232.124", 9201), timeout=icode.CONNECT_TIMEOUT_SECONDS)
        self.assertEqual(len(connection.sent), 1)
        self.assertEqual(decode_packet(connection.sent[0])["tel"], "01012345678")

    def test_refusal_code_is_read_without_waiting_for_a_full_reply(self):
        connection = FakeConnection([b"0225  97", b"never-read"])
        with patch(SOCKET, return_value=connection):
            result = icode.send_message("01012345678", "0212345678", "hello")

        self.assertEqual((result.status, result.provider_code), ("rejected", "97"))
        self.assertEqual(connection.chunks, [b"never-read"])

    def test_invalid_numbers_are_refused_before_any_socket(self):
        with patch(SOCKET) as create_connection:
            bad_recipient = icode.send_message("02-123-4567", "0212345678", "hello")
            bad_callback = icode.send_message("01012345678", "12", "hello")

        self.assertEqual(bad_recipient.provider_code, "invalid_request")
        self.assertEqual(bad_callback.provider_code, "invalid_request")
        create_connection.assert_not_called()

    def test_network_failures_are_results_not_exceptions(self):
        with patch(SOCKET, side_effect=TimeoutError):
            self.assertEqual(icode.send_message("01012345678", "0212345678", "x").provider_code, "connect_timeout")
        with patch(SOCKET, side_effect=ConnectionRefusedError):
            self.assertEqual(icode.send_message("01012345678", "0212345678", "x").status, "rejected")
        connection = FakeConnection([])
        connection.recv = Mock(side_effect=TimeoutError)
        with patch(SOCKET, return_value=connection):
            self.assertEqual(icode.send_message("01012345678", "0212345678", "x").status, "unknown")
        with patch(SOCKET, return_value=FakeConnection([b"garbage"])):
            self.assertEqual(icode.send_message("01012345678", "0212345678", "x").provider_code, "invalid_response")

    @override_settings(G5_SMS_PROVIDER="disabled")
    def test_disabled_provider_never_connects(self):
        with patch(SOCKET) as create_connection, self.assertRaises(icode.ICodeConfigurationError):
            icode.send_message("01012345678", "0212345678", "hello")
        create_connection.assert_not_called()
        self.assertFalse(icode.credential_status()["ready"])

    @override_settings(
        G5_ICODE_TOKEN_KEY="", G5_ICODE_ID="legacyid", G5_ICODE_PASSWORD="legacypw",
        G5_ICODE_SERVER="sms.invalid", G5_ICODE_PORT=1234,
    )
    def test_legacy_id_password_is_the_fallback_without_a_token(self):
        connection = FakeConnection([b"0223  00" + b"01012345678" + b"accepted  "])
        with patch(SOCKET, return_value=connection):
            result = icode.send_message("01012345678", "0212345678", "hello", allow_lms=True)

        self.assertEqual(result.status, "accepted")
        self.assertTrue(connection.sent[0].startswith(b"01144 "))
        self.assertEqual(icode.credential_status()["mode"], "legacy")

    def test_credential_status_reports_presence_only(self):
        status = icode.credential_status()
        self.assertEqual(status, {"provider_enabled": True, "has_token": True, "has_legacy": False, "mode": "token", "ready": True})
        self.assertNotIn(TOKEN, json.dumps(status))


class ShopSmsFixture:
    def configure(self, **values):
        defaults = {"cf_sms_use": "icode", "de_sms_hp": "010-9999-0000"}
        for name, value in {**defaults, **values}.items():
            Config.objects.update_or_create(name=name, defaults={"value": value})

    def setUp(self):
        super().setUp()
        # the send limits and the breaker live in the cache
        cache.clear()
        self.addCleanup(cache.clear)
        ShopShippingPolicy.objects.update_or_create(
            pk=1, defaults={"de_admin_company_name": "데모샵", "de_admin_company_tel": "02-1234-5678"}
        )
        self.member = get_user_model().objects.create_user(username="buyer01", password="pw")

    def make_order(self, **fields):
        values = {
            "od_name": "홍길동",
            "od_b_name": "김수령",
            "od_hp": "010-1111-2222",
            "user": self.member,
            "od_status": "주문",
            "od_settle_case": "무통장",
            "od_cart_price": 20000,
            "od_send_cost": 3000,
            "od_misu": 23000,
            "od_bank_account": "데모은행 123-456 데모샵",
            **fields,
        }
        order = ShopOrder.objects.create(od_id="202610210001", **values)
        product, _ = ShopProduct.objects.get_or_create(it_id="SMS-P1", defaults={"it_name": "셔츠", "it_price": 20000})
        ShopOrderItem.objects.create(
            order=order, product=product, ct_id="1", it_id=product.it_id, it_name="셔츠",
            ct_price=20000, ct_qty=1, ct_status=order.od_status, stock_adjusted=True,
        )
        return order


def accepted(*args, **kwargs):
    return ICodeSendResult("accepted", "MSG00000001")


class OrderSmsTests(ShopSmsFixture, TestCase):
    def test_order_placed_texts_customer_admin_and_bank_account_with_youngcart_variables(self):
        self.configure(de_sms_use2="1", de_sms_use3="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                notifications.queue_order_placed_sms(order)

        calls = [(call.args[0], call.args[1], call.args[2]) for call in send.call_args_list]
        self.assertEqual(
            calls,
            [
                ("010-1111-2222", "02-1234-5678", "홍길동님 주문해주셔서 고맙습니다.\n202610210001\n23,000원\n데모샵"),
                ("010-9999-0000", "02-1234-5678", "홍길동님께서 주문하셨습니다.\n202610210001\n23,000원\n데모샵"),
                ("010-1111-2222", "02-1234-5678", "홍길동님의 입금계좌입니다.\n금액:23,000원\n계좌:데모은행 123-456 데모샵\n데모샵"),
            ],
        )
        memo = ShopOrder.objects.get(pk=order.pk).od_shop_memo
        self.assertIn("SMS 주문안내", memo)
        self.assertIn("고객 ••••2222 접수", memo)
        self.assertNotIn("010-1111-2222", memo)

    def test_custom_template_variables_and_lms_type(self):
        self.configure(de_sms_use2="1", cf_sms_type="LMS", de_sms_cont2="{받는분}/{보낸분}/{회원아이디}/{주문금액}")
        order = self.make_order(od_settle_case="신용카드", od_misu=0)
        with patch(TRANSPORT, side_effect=accepted) as send:
            notifications.send_order_placed_sms(order.pk)

        send.assert_called_once()
        self.assertEqual(send.call_args.args[2], "김수령/홍길동/buyer01/23,000")
        self.assertTrue(send.call_args.kwargs["allow_lms"])
        self.assertEqual(send.call_args.kwargs["subject"], "데모샵")

    def test_nothing_is_sent_while_sms_is_off_or_the_slot_is_off(self):
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            self.configure(cf_sms_use="", de_sms_use2="1", de_sms_use3="1")
            notifications.send_order_placed_sms(order.pk)
            self.configure(cf_sms_use="icode", de_sms_use2="0", de_sms_use3="0")
            notifications.send_order_placed_sms(order.pk)
            notifications.send_order_status_sms(order.pk, "입금")
        send.assert_not_called()

    def test_paid_and_shipped_status_moves_text_the_customer_after_commit(self):
        self.configure(de_sms_use4="1", de_sms_use5="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(move_order_status(order, "입금").ok)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(move_order_status(order, "준비").ok)
            ShopOrder.objects.filter(pk=order.pk).update(od_delivery_company="CJ대한통운", od_invoice="123456789012")
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(move_order_status(order, "배송").ok)

        texts = [call.args[2] for call in send.call_args_list]
        self.assertEqual(
            texts,
            [
                "홍길동님 입금 감사합니다.\n23,000원\n주문번호:\n202610210001\n데모샵",
                "홍길동님 배송합니다.\n택배:CJ대한통운\n운송장번호:\n123456789012\n데모샵",
            ],
        )

    def test_a_gateway_failure_never_breaks_the_status_move(self):
        self.configure(de_sms_use4="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=RuntimeError("boom")):
            with self.captureOnCommitCallbacks(execute=True):
                change = move_order_status(order, "입금")
        self.assertTrue(change.ok)
        order.refresh_from_db()
        self.assertEqual(order.od_status, "입금")
        self.assertIn("확인필요", order.od_shop_memo)

    def test_bank_order_api_queues_the_order_texts(self):
        self.configure(de_sms_use3="1")
        order = self.make_order()
        with patch("gnu_jango.api.v1_shop.create_order_from_request", return_value=order), patch(
            TRANSPORT, side_effect=accepted
        ) as send:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post("/api/v1/shop/orders", {}, content_type="application/json")
        self.assertIn(response.status_code, {200, 201})
        self.assertEqual(send.call_args.args[0], "010-9999-0000")


class MemberJoinSmsTests(ShopSmsFixture, TestCase):
    def test_signup_slot_texts_the_member_mobile_number(self):
        self.configure(de_sms_use1="1")
        profile = self.member.profile
        profile.user_hp = "010-3333-4444"
        profile.realname = "새회원"
        profile.save(update_fields=["user_hp", "realname"])
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                notifications.queue_member_join_sms(self.member)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "010-3333-4444")
        self.assertEqual(send.call_args.args[2], "새회원님의 회원가입을 축하드립니다.\nID:buyer01\n데모샵")

    def test_no_phone_or_switch_off_sends_nothing(self):
        with patch(TRANSPORT, side_effect=accepted) as send:
            self.configure(de_sms_use1="1")
            self.assertIsNone(notifications.send_member_join_sms(self.member.pk))
            self.configure(de_sms_use1="0")
            self.assertIsNone(notifications.send_member_join_sms(self.member.pk))
        send.assert_not_called()


class SmsServiceTests(ShopSmsFixture, TestCase):
    def test_configuration_errors_become_rejected_results(self):
        with patch(TRANSPORT, side_effect=icode.ICodeConfigurationError("missing")):
            result = service.send_message("01011112222", "hi")
        self.assertEqual((result.status, result.provider_code), ("rejected", "configuration"))

    def test_settings_fall_back_to_youngcart_defaults(self):
        Config.objects.filter(name__startswith="de_sms_").delete()
        current = service.sms_settings()
        self.assertEqual(current.slot(5), (False, "{이름}님 배송합니다.\n택배:{택배회사}\n운송장번호:\n{운송장번호}\n{회사명}"))
        self.assertEqual(current.callback, "02-1234-5678")
        self.assertEqual(service.render_template("{이름}/{없음}", {"이름": "A"}), "A/{없음}")


class SmsLimitTests(ShopSmsFixture, TestCase):
    @override_settings(G5_SMS_RECIPIENT_HOURLY_LIMIT=2)
    def test_one_number_gets_at_most_the_hourly_limit(self):
        with patch(TRANSPORT, side_effect=accepted) as send:
            results = [service.send_message("010-5555-6666", "hi") for _ in range(3)]
            other = service.send_message("010-5555-7777", "hi")
        self.assertEqual([result.status for result in results], ["accepted", "accepted", "rejected"])
        self.assertEqual(results[2].provider_code, "recipient_limit")
        self.assertEqual(other.status, "accepted")
        self.assertEqual(send.call_count, 3)

    @override_settings(G5_SMS_RECIPIENT_HOURLY_LIMIT=1)
    def test_the_admin_phone_is_not_capped_per_number(self):
        self.configure()
        with patch(TRANSPORT, side_effect=accepted) as send:
            results = [service.send_message("01099990000", "new order") for _ in range(3)]
        self.assertEqual({result.status for result in results}, {"accepted"})
        self.assertEqual(send.call_count, 3)

    @override_settings(G5_SMS_HOURLY_LIMIT=2)
    def test_the_site_wide_hourly_limit_stops_every_number(self):
        with patch(TRANSPORT, side_effect=accepted) as send:
            results = [service.send_message(f"0105555{n:04d}", "hi") for n in range(3)]
        self.assertEqual(results[2].provider_code, "hourly_limit")
        self.assertEqual(send.call_count, 2)

    def test_a_gateway_timeout_pauses_every_text_for_a_while(self):
        timeout = ICodeSendResult("rejected", "connect_timeout", "Could not connect to the iCode server.")
        with patch(TRANSPORT, return_value=timeout) as send, self.assertLogs(service.logger, "ERROR") as logs:
            first = service.send_message("01011112222", "hi")
            second = service.send_message("01033334444", "hi")
            third = service.send_message("01033334444", "hi")
        self.assertEqual(first.provider_code, "connect_timeout")
        self.assertEqual((second.status, second.provider_code), ("rejected", "circuit_open"))
        self.assertEqual(third.provider_code, "circuit_open")
        send.assert_called_once()
        # logged once, not on every skipped text
        self.assertEqual(sum("pausing every text" in line for line in logs.output), 1)
        cache.delete(service.BREAKER_CACHE_KEY)
        with patch(TRANSPORT, side_effect=accepted):
            self.assertEqual(service.send_message("01033334444", "hi").status, "accepted")

    def test_a_refusal_does_not_open_the_breaker(self):
        refused = ICodeSendResult("rejected", "99", "iCode rejected the message.")
        with patch(TRANSPORT, return_value=refused) as send:
            service.send_message("01011112222", "hi")
            service.send_message("01011112222", "hi")
        self.assertEqual(send.call_count, 2)

    def test_socket_timeouts_are_tight(self):
        self.assertLessEqual(icode.CONNECT_TIMEOUT_SECONDS, 2)
        self.assertLessEqual(icode.READ_TIMEOUT_SECONDS, 3)

    def test_a_status_move_without_send_sms_texts_nobody(self):
        self.configure(de_sms_use4="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(move_order_status(order, "입금", send_sms=False))
        send.assert_not_called()


class GuestOrderThrottleTests(ShopSmsFixture, TestCase):
    def test_guest_checkouts_are_limited_per_address(self):
        from rest_framework.throttling import SimpleRateThrottle

        from gnu_jango.api.v1_shop import GuestOrderThrottle

        order = self.make_order()
        statuses = []
        rates = {**SimpleRateThrottle.THROTTLE_RATES, "shop-guest-order": "3/hour"}
        with patch.object(GuestOrderThrottle, "THROTTLE_RATES", rates), patch(
            "gnu_jango.api.v1_shop.create_order_from_request", return_value=order
        ):
            for _ in range(4):
                statuses.append(self.client.post("/api/v1/shop/orders", {}, content_type="application/json").status_code)
            listing = self.client.get("/api/v1/shop/orders").status_code
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)
        self.assertEqual(listing, 200)

    def test_the_guest_order_rate_is_configured(self):
        from django.conf import settings

        self.assertEqual(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["shop-guest-order"], "20/hour")


@override_settings(G5_SMS_PROVIDER="", G5_ICODE_TOKEN_KEY=TOKEN, **NO_LEGACY)
class ShopSettingsSmsTests(ShopSmsFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("admin-shop-settings")
        self.admin = get_user_model().objects.create_superuser(
            username="sms-admin", email="sms-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)

    def form_data(self, **values):
        data = {
            "de_admin_company_name": "데모샵",
            "de_admin_company_tel": "02-1234-5678",
            "de_delivery_company": "CJ대한통운",
            "de_send_cost_case": "",
            "de_send_cost_limit": "",
            "de_send_cost_list": "",
            "de_baesong_content": "",
            "de_change_content": "",
            "de_item_use_write": "0",
            "de_item_use_use": "0",
            "de_settle_min_point": "0",
            "de_settle_max_point": "0",
            "de_settle_point_unit": "1",
        }
        data.update(values)
        return data

    def test_page_shows_credential_presence_and_youngcart_slots_but_never_the_token(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("SMS 연결 상태", page)
        self.assertIn("등록됨 · 토큰키 (JSON 방식)", page)
        self.assertIn("테스트 발송", page)
        self.assertIn("회원가입시 고객님께 발송", page)
        self.assertIn("상품배송시 고객님께 발송 내용", page)
        self.assertIn("{택배회사}", page)
        self.assertIn("data-sms-bytes", page)
        self.assertNotIn(TOKEN, page)

    @override_settings(G5_ICODE_TOKEN_KEY="")
    def test_missing_credentials_disable_the_test_button(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("<dd>미등록", page)
        self.assertRegex(page, r'value="test_sms">\s*<button class="btn" type="submit" disabled>')

    def test_saving_sms_settings_stores_config_rows_and_validates_the_admin_phone(self):
        response = self.client.post(self.url, self.form_data(
            cf_sms_use="icode", cf_sms_type="LMS", de_sms_hp="010-9999-0000",
            de_sms_use4="on", de_sms_cont4="{이름}님 입금 확인\r\n{입금액}원",
        ))
        self.assertEqual(response.status_code, 302)
        saved = dict(Config.objects.filter(name__in=["cf_sms_use", "cf_sms_type", "de_sms_use4", "de_sms_use5", "de_sms_cont4"]).values_list("name", "value"))
        self.assertEqual(saved["cf_sms_use"], "icode")
        self.assertEqual(saved["cf_sms_type"], "LMS")
        self.assertEqual(saved["de_sms_use4"], "1")
        self.assertEqual(saved["de_sms_use5"], "0")
        self.assertIn("{입금액}원", saved["de_sms_cont4"])
        self.assertFalse(Config.objects.filter(name__icontains="icode_").exists())

        response = self.client.post(self.url, self.form_data(de_sms_hp="02-123-4567", cf_sms_use="bogus"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("관리자 휴대폰번호는", response.content.decode())

    def test_test_send_goes_to_the_admin_phone_once_a_minute(self):
        self.configure(cf_sms_use="")  # the test works before SMS is switched on
        with patch(TRANSPORT, side_effect=accepted) as send:
            first = self.client.post(self.url, {"action": "test_sms"}, follow=True)
            second = self.client.post(self.url, {"action": "test_sms"}, follow=True)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[:2], ("010-9999-0000", "02-1234-5678"))
        self.assertEqual(send.call_args.args[2], "[데모샵] 아이코드 SMS 테스트 발송입니다.")
        self.assertIn("테스트 문자를 관리자 휴대폰번호로 보냈습니다", first.content.decode())
        self.assertIn("1분에 한 번만", second.content.decode())

    def test_test_send_requires_a_superuser(self):
        staff = get_user_model().objects.create_user(username="sms-staff", password="pw", is_staff=True)
        self.client.force_login(staff)
        with patch(TRANSPORT, side_effect=accepted) as send:
            response = self.client.post(self.url, {"action": "test_sms"})
        self.assertEqual(response.status_code, 403)
        send.assert_not_called()


class SendTestSmsCommandTests(ShopSmsFixture, TestCase):
    @override_settings(G5_SMS_PROVIDER="", G5_ICODE_TOKEN_KEY=TOKEN)
    def test_command_needs_confirm_before_sending(self):
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.assertRaisesMessage(CommandError, "--confirm"):
                call_command("send_test_sms", "010-5555-6666", stdout=io.StringIO())
            send.assert_not_called()
            out = io.StringIO()
            call_command("send_test_sms", "010-5555-6666", "--confirm", stdout=out)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "01055556666")
        self.assertIn("accepted", out.getvalue())
        self.assertNotIn(TOKEN, out.getvalue())

    @override_settings(G5_SMS_PROVIDER="", G5_ICODE_TOKEN_KEY="", **NO_LEGACY)
    def test_command_refuses_without_credentials(self):
        with self.assertRaisesMessage(CommandError, "G5_ICODE_TOKEN_KEY"):
            call_command("send_test_sms", "010-5555-6666", "--confirm", stdout=io.StringIO())


class RestockSmsAdminTests(ShopSmsFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="restock-admin", password="password")
        self.client.force_login(self.admin)
        self.product = ShopProduct.objects.create(it_id="RESTOCK1", it_name="재입고 셔츠", it_stock_qty=5)
        self.subscriptions = [
            ShopStockNotification.objects.create(product=self.product, it_id="RESTOCK1", ss_hp=phone)
            for phone in ("010-1000-0001", "010-1000-0002")
        ]
        self.url = reverse("admin:shop_shopstocknotification_changelist")

    def run_action(self):
        return self.client.post(
            self.url,
            {
                "action": "send_restock_sms",
                "_selected_action": [str(item.pk) for item in self.subscriptions],
                "confirm_send": "on",
            },
            follow=True,
        )

    def test_restock_texts_go_through_the_transport_with_one_log_per_recipient(self):
        self.configure()
        def gateway(recipient, *args, **kwargs):
            if recipient.endswith("0001"):
                return ICodeSendResult("accepted", "OK1")
            return ICodeSendResult("rejected", "97", "iCode rejected the message.")

        with patch(TRANSPORT, side_effect=gateway) as send:
            response = self.run_action()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[2], "[데모샵] 재입고 셔츠 상품이 재입고되었습니다.")
        logs = {log.recipient_last4: log for log in ShopStockNotificationSendLog.objects.all()}
        self.assertEqual((logs["0001"].status, logs["0001"].provider_code), ("accepted", "OK1"))
        self.assertEqual((logs["0002"].status, logs["0002"].provider_code), ("rejected", "97"))
        sent = dict(ShopStockNotification.objects.values_list("ss_hp", "ss_send"))
        self.assertEqual(sent, {"010-1000-0001": True, "010-1000-0002": False})

    def test_restock_action_refuses_while_sms_is_off(self):
        self.configure(cf_sms_use="")
        with patch(TRANSPORT, side_effect=accepted) as send:
            response = self.run_action()
        send.assert_not_called()
        self.assertIn("SMS 사용이 꺼져 있습니다", response.content.decode())
        self.assertFalse(ShopStockNotificationSendLog.objects.exists())


class ImporterSmsOptionTests(TestCase):
    def test_youngcart_sms_options_are_imported_but_never_icode_credentials(self):
        config_row = {
            "cf_title": "Fixture",
            "cf_sms_use": "icode",
            "cf_sms_type": "LMS",
            "cf_icode_id": "private-id-sentinel",
            "cf_icode_pw": "private-pw-sentinel",
            "cf_icode_token_key": "private-token-sentinel",
        }
        shop_row = {"de_sms_hp": "010-2222-3333", "de_sms_use2": "1", "de_sms_cont2": "{이름}님 주문 감사"}
        with patch.object(migrate_gnuboard5, "table_exists", return_value=True), patch.object(
            migrate_gnuboard5, "fetch_rows", side_effect=[[config_row], [shop_row]]
        ):
            ImportCommand().import_public_config(Mock(), {"tables": {"config_table": "c", "g5_shop_default_table": "d"}})

        stored = dict(Config.objects.values_list("name", "value"))
        self.assertEqual(stored["cf_sms_use"], "icode")
        self.assertEqual(stored["cf_sms_type"], "LMS")
        self.assertEqual(stored["de_sms_hp"], "010-2222-3333")
        self.assertEqual(stored["de_sms_use2"], "1")
        self.assertEqual(stored["de_sms_cont2"], "{이름}님 주문 감사")
        for sentinel in ("private-id-sentinel", "private-pw-sentinel", "private-token-sentinel"):
            self.assertNotIn(sentinel, stored.values())
