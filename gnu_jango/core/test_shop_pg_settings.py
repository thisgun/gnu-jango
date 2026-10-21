"""youngcart 결제설정 in the admin shop settings: Toss keys entered in the admin (sealed in
Config, never rendered), the environment keys winning over them, 결제 테스트 choosing the key
pair, 에스크로 사용 and 복합과세 결제 reaching the Toss requests, and the youngcart section order.

No test talks to Toss: urlopen and toss_api_confirm are patched and every key is fake."""

import base64
import json
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gnu_jango.api import shop_payments
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_partial_cancel import URLOPEN, PartialCancelBase
from gnu_jango.core.test_shop_payments_api import CONFIG_URL, FAKE_TOSS, PaymentTestBase, fake_http_response
from gnu_jango.core.test_shop_personal_pay_checkout import PP_ID, PersonalPayCheckoutBase
from gnu_jango.core.test_shop_orders_more import API
from gnu_jango.shop import pg_settings
from gnu_jango.shop.admin_settings import SETTINGS_GROUPS, ShopSettingsForm
from gnu_jango.shop.models import ShopOrder, ShopShippingPolicy
from gnu_jango.shop.order_flow import move_order_status
from gnu_jango.shop.order_lines import change_order_lines

NO_ENV = {"SHOP_TOSS_CLIENT_KEY": "", "SHOP_TOSS_SECRET_KEY": "", "SHOP_PAYMENT_PROVIDER": ""}
TEST_CLIENT = "test_ck_admin_client_1234"
TEST_SECRET = "test_sk_admin_secret_5678"
LIVE_CLIENT = "live_ck_admin_client_abcd"
LIVE_SECRET = "live_sk_admin_secret_efgh"


def store_keys(**keys):
    """store_keys(test_client=..., live_secret=...) saves sealed admin keys like the form does."""
    for name, value in keys.items():
        mode, kind = name.split("_")
        Config.objects.update_or_create(
            name=pg_settings.TOSS_KEY_ROWS[(mode, kind)], defaults={"value": pg_settings.seal_key(mode, kind, value)}
        )


def set_config(**values):
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": value})


def basic_secret(request):
    token = request.get_header("Authorization").removeprefix("Basic ")
    return base64.b64decode(token).decode("utf-8").rstrip(":")


@override_settings(**NO_ENV)
class AdminTossKeyResolutionTests(TestCase):
    def test_admin_keys_are_sealed_and_the_test_pair_is_used_by_default(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET, live_client=LIVE_CLIENT, live_secret=LIVE_SECRET)
        stored = dict(Config.objects.filter(name__startswith="cf_toss_").values_list("name", "value"))
        self.assertTrue(all(value.startswith("sv2:") for value in stored.values()))
        self.assertNotIn(TEST_SECRET, " ".join(stored.values()))

        config = shop_payments.toss_payment_config()
        self.assertEqual((config["source"], config["key_status"], config["client_key"]), ("admin", "test", TEST_CLIENT))
        self.assertNotIn("secret_key", config)
        self.assertEqual(shop_payments.configured_payment_provider(), "toss")

    def test_card_test_off_picks_the_live_pair(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET, live_client=LIVE_CLIENT, live_secret=LIVE_SECRET)
        set_config(de_card_test="0")
        config, authorization = shop_payments.toss_api_context()
        self.assertEqual((config["key_status"], config["client_key"]), ("live", LIVE_CLIENT))
        self.assertEqual(base64.b64decode(authorization.removeprefix("Basic ")).decode(), f"{LIVE_SECRET}:")

    def test_a_missing_half_of_the_selected_pair_disables_toss(self):
        store_keys(test_client=TEST_CLIENT, live_client=LIVE_CLIENT, live_secret=LIVE_SECRET)
        config, authorization = shop_payments.toss_api_context()
        self.assertEqual((config["key_status"], authorization), ("incomplete", ""))
        self.assertEqual(shop_payments.configured_payment_provider(), "bank")

    def test_a_sealed_key_copied_to_another_row_does_not_open(self):
        Config.objects.create(
            name=pg_settings.TOSS_KEY_ROWS[("test", "secret")],
            value=pg_settings.seal_key("live", "secret", TEST_SECRET),
        )
        self.assertEqual(pg_settings.admin_keys()[("test", "secret")], "")
        Config.objects.create(name=pg_settings.TOSS_KEY_ROWS[("test", "client")], value=TEST_CLIENT)  # plaintext
        self.assertEqual(pg_settings.admin_keys()[("test", "client")], "")

    @override_settings(SHOP_TOSS_CLIENT_KEY="live_ck_env_client", SHOP_TOSS_SECRET_KEY="live_sk_env_secret")
    def test_environment_keys_win_over_the_admin_pair(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        config, authorization = shop_payments.toss_api_context()
        self.assertEqual((config["source"], config["client_key"]), ("env", "live_ck_env_client"))
        self.assertIn(base64.b64encode(b"live_sk_env_secret:").decode(), authorization)

    @override_settings(SHOP_TOSS_ADMIN_KEYS_ENABLED=False)
    def test_admin_keys_can_be_switched_off_for_previews(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        self.assertEqual(shop_payments.toss_payment_config()["source"], "none")

    def test_pg_service_none_keeps_checkout_on_bank_deposit(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        set_config(de_pg_service="none")
        self.assertEqual(shop_payments.configured_payment_provider(), "bank")
        with override_settings(SHOP_PAYMENT_PROVIDER="toss"):
            self.assertEqual(shop_payments.configured_payment_provider(), "toss")

    def test_every_toss_call_uses_the_admin_secret(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        order = ShopOrder.objects.create(od_id="PG-KEY-1", od_status="입금", od_pg="toss", od_tno="pk_1",
                                         od_settle_case="신용카드", od_receipt_price=1000)
        from gnu_jango.shop import cash_receipt_toss

        calls = (
            lambda: shop_payments.check_toss_connection(),
            lambda: shop_payments.toss_api_confirm("pk_1", order.od_id, 1000),
            lambda: shop_payments.toss_api_get_payment_by_order(order.od_id),
            lambda: shop_payments.toss_api_cancel_payment(order, "test"),
            lambda: cash_receipt_toss.cancel_toss_cash_receipt("receipt-1"),
        )
        for call in calls:
            reply = {"orderId": order.od_id, "status": "CANCELED", "receiptKey": "receipt-1"}
            with self.subTest(call=call), patch(URLOPEN, return_value=fake_http_response(reply)) as urlopen:
                call()
                self.assertEqual(basic_secret(urlopen.call_args.args[0]), TEST_SECRET)


class ShopSettingsPgAdminTests(TestCase):
    minimal_form = {
        "de_admin_company_name": "Demo Shop", "de_admin_company_tel": "", "de_delivery_company": "CJ대한통운",
        "de_send_cost_case": "", "de_send_cost_limit": "", "de_send_cost_list": "", "de_baesong_content": "",
        "de_change_content": "", "de_settle_min_point": "0", "de_settle_max_point": "0", "de_settle_point_unit": "1",
    }

    def setUp(self):
        self.url = reverse("admin-shop-settings")
        self.admin = get_user_model().objects.create_superuser(
            username="pg-settings-admin", email="pg-settings@example.test", password="password"
        )
        self.client.force_login(self.admin)

    def save(self, **fields):
        return self.client.post(self.url, {**self.minimal_form, **fields})

    @override_settings(**NO_ENV)
    def test_saved_keys_are_sealed_never_rendered_and_logged_without_values(self):
        response = self.save(cf_toss_test_client_key=TEST_CLIENT, cf_toss_test_secret_key=TEST_SECRET,
                             de_card_test="1", de_pg_service="toss")
        self.assertEqual(response.status_code, 302)
        stored = Config.objects.get(name="cf_toss_test_secret_key").value
        self.assertTrue(stored.startswith("sv2:"))
        self.assertEqual(pg_settings.admin_keys()[("test", "secret")], TEST_SECRET)

        page = self.client.get(self.url).content.decode()
        self.assertNotIn(TEST_SECRET, page)
        self.assertNotIn(TEST_CLIENT, page)
        self.assertNotIn(stored, page)
        self.assertIn("test_ck_****1234", page)
        self.assertIn("현재 결제 모드: <strong>테스트결제</strong>", page)
        self.assertIn("키 출처: 관리자 설정", page)
        messages = " ".join(LogEntry.objects.values_list("change_message", flat=True))
        self.assertIn("테스트 시크릿 키 등록", messages)
        self.assertNotIn(TEST_SECRET, messages)
        self.assertNotIn(TEST_CLIENT, messages)

    @override_settings(**NO_ENV)
    def test_blank_key_inputs_keep_the_saved_keys_and_delete_removes_one(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        self.assertEqual(self.save().status_code, 302)
        self.assertEqual(pg_settings.admin_keys()[("test", "secret")], TEST_SECRET)
        self.assertEqual(self.save(cf_toss_test_secret_key_delete="on").status_code, 302)
        self.assertFalse(Config.objects.filter(name="cf_toss_test_secret_key").exists())
        self.assertEqual(pg_settings.admin_keys()[("test", "client")], TEST_CLIENT)
        self.assertIn("테스트 시크릿 키 삭제", LogEntry.objects.latest("pk").change_message)

    @override_settings(**NO_ENV)
    def test_keys_must_match_their_slot_and_kind(self):
        cases = (
            ({"cf_toss_test_secret_key": LIVE_SECRET}, "cf_toss_test_secret_key"),
            ({"cf_toss_client_key": TEST_CLIENT}, "cf_toss_client_key"),
            ({"cf_toss_test_client_key": "test_ck_has space 1234"}, "cf_toss_test_client_key"),
            ({"cf_toss_test_client_key": TEST_CLIENT, "cf_toss_test_secret_key": "test_gsk_widget_secret_99"},
             "cf_toss_test_client_key"),
        )
        for fields, field in cases:
            with self.subTest(fields=fields):
                form = ShopSettingsForm(data={**self.minimal_form, **fields}, instance=ShopShippingPolicy(pk=1))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
        self.assertFalse(Config.objects.filter(name__startswith="cf_toss_").exists())

    @override_settings(SHOP_TOSS_CLIENT_KEY="live_ck_env_client", SHOP_TOSS_SECRET_KEY="live_sk_env_secret",
                       SHOP_PAYMENT_PROVIDER="toss")
    def test_environment_keys_lock_the_inputs_and_warn_about_the_test_toggle(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("서버 환경 변수로 설정됨 (여기서 변경 불가)", page)
        self.assertIn('name="cf_toss_test_secret_key"', page)
        self.assertRegex(page, r'<input[^>]*name="cf_toss_client_key"[^>]*disabled')
        self.assertRegex(page, r'<input[^>]*name="de_pg_service"[^>]*disabled')
        self.assertIn("서버 환경 변수의 키는 실결제 키입니다", page)
        self.assertNotIn("live_sk_env_secret", page)
        self.save(cf_toss_test_client_key=TEST_CLIENT, de_pg_service="none")
        self.assertFalse(Config.objects.filter(name__in=["cf_toss_test_client_key", "de_pg_service"]).exists())

    @override_settings(**NO_ENV)
    def test_live_mode_without_a_live_pair_is_flagged(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        set_config(de_card_test="0")
        page = self.client.get(self.url).content.decode()
        self.assertIn("실결제 키 쌍(클라이언트 키·시크릿 키)을 모두 등록해야 결제할 수 있습니다", page)
        self.assertIn("현재 온라인 결제를 받을 수 없습니다", page)

    @override_settings(**NO_ENV)
    def test_payment_choices_save_and_a_missing_choice_keeps_the_saved_one(self):
        self.save(de_card_test="0", de_escrow_use="1", de_pg_service="none")
        saved = dict(Config.objects.filter(name__in=pg_settings.PG_SETTING_NAMES).values_list("name", "value"))
        self.assertEqual(saved, {"de_card_test": "0", "de_escrow_use": "1", "de_pg_service": "none"})
        self.save()
        self.assertEqual(Config.objects.get(name="de_card_test").value, "0")
        self.assertIn("에스크로 사용: 에스크로결제 사용", LogEntry.objects.order_by("pk")[1].change_message)

    @override_settings(**NO_ENV)
    def test_page_follows_youngcart_order_and_shows_the_payment_rows(self):
        page = self.client.get(self.url).content.decode()
        titles = ["사업자정보", "쇼핑몰 초기화면 진열", "결제 연결 상태", "결제대행사와 결제 방식", "무통장입금",
                  "온라인 결제수단", "현금영수증 발급", "포인트 사용·구매 포인트", "배송비와 배송 안내", "희망배송일",
                  "상품 후기", "장바구니", "신규회원 쿠폰", "비회원 개인정보 수집 안내", "쇼핑몰 로고", "SMS 연결 상태"]
        positions = [page.index(f'class="card-title">{title}</h3>') for title in titles]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("http://testserver/api/v1/shop/payment/toss/vbank/webhook", page)
        self.assertIn("data-copy-target=\"shop-webhook-url\"", page)
        self.assertIn("신용카드 무이자할부 (KCP만 해당)", page)
        self.assertIn("PG사 간편결제 버튼 노출", page)
        self.assertIn('form="shop-pg-check-form"', page)
        pg_section = page[page.index('id="shop-pg"'):page.index('id="shop-bank"')]
        self.assertIn('name="de_tax_flag_use"', pg_section)
        self.assertIn("복합과세 결제", pg_section)

    def test_every_form_field_is_in_one_section(self):
        form = ShopSettingsForm(instance=ShopShippingPolicy(pk=1))
        placed = [item["bound"].name for section in form.sections() for item in section.get("fields", [])]
        placed += [field.name for section in form.sections() for row in section.get("table", {}).get("rows", [])
                   for field in row["fields"]]
        self.assertEqual(sorted(placed), sorted(form.fields))
        self.assertEqual([group[1] for group in SETTINGS_GROUPS],
                         ["사업자정보", "쇼핑몰 진열", "결제설정", "배송설정", "기타 설정", "SMS 설정"])


@override_settings(**FAKE_TOSS)
class TossEscrowAndTaxFreeCheckoutTests(PaymentTestBase):
    def test_escrow_reaches_transfer_and_virtual_account_payments_only(self):
        set_config(de_escrow_use="1")
        with override_settings(SHOP_TOSS_VBANK_ENABLED=True):
            config = self.client.get(CONFIG_URL).json()["data"]
            self.assertEqual(config["escrow"], {"enabled": True, "methods": ["vbank", "iche"]})
            for settle_case, expected in (("iche", True), ("가상계좌", True), ("card", False)):
                with self.subTest(settle_case=settle_case):
                    data = self.prepare(od_settle_case=settle_case).json()["data"]
                    self.assertIs(data["use_escrow"], expected)
                    if expected:
                        (product,) = data["escrow_products"]
                        self.assertEqual(
                            {key: product[key] for key in ("name", "code", "unitPrice")},
                            {"name": "Payment product", "code": "PAY001", "unitPrice": 100000},
                        )
                        self.assertGreaterEqual(product["quantity"], 1)
                    else:
                        self.assertEqual(data["escrow_products"], [])

    def test_escrow_off_sends_no_escrow(self):
        data = self.prepare(od_settle_case="iche").json()["data"]
        self.assertFalse(data["use_escrow"])
        self.assertFalse(self.client.get(CONFIG_URL).json()["data"]["escrow"]["enabled"])

    def test_mixed_tax_orders_send_the_tax_free_amount(self):
        ShopShippingPolicy.objects.filter(pk=1).update(de_tax_flag_use=True, de_send_cost_case="")
        self.product.it_notax = 1
        self.product.save(update_fields=["it_notax"])
        data = self.prepare().json()["data"]
        self.assertEqual((data["tax_flag"], data["comm_free_mny"]), (1, 100000))
        ShopShippingPolicy.objects.filter(pk=1).update(de_tax_flag_use=False)
        data = self.prepare().json()["data"]
        self.assertEqual((data["tax_flag"], data["comm_free_mny"]), (0, 0))

    def test_an_escrow_payment_reminds_the_admin_to_register_the_delivery(self):
        order = self.prepared_order(od_settle_case="iche")
        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, method="계좌이체", useEscrow=True))
        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertIn(shop_payments.ESCROW_HISTORY_MARK, order.od_mod_history)
        self.assertTrue(move_order_status(order, "준비"))
        ShopOrder.objects.filter(pk=order.pk).update(od_delivery_company="CJ대한통운", od_invoice="1234")
        result = move_order_status(order, "배송", send_sms=False)
        self.assertTrue(result.ok)
        self.assertTrue(result.warning)
        self.assertIn("토스페이먼츠 상점관리자에서 배송 정보를 등록하세요", result.message)
        order.refresh_from_db()
        self.assertIn(shop_payments.ESCROW_DELIVERY_NOTICE, order.od_mod_history)

    def test_a_plain_payment_ships_without_the_escrow_notice(self):
        order = self.prepared_order()
        self.confirm_toss(order)
        move_order_status(order, "준비")
        ShopOrder.objects.filter(pk=order.pk).update(od_delivery_company="CJ대한통운", od_invoice="1234")
        result = move_order_status(order, "배송", send_sms=False)
        self.assertFalse(result.warning)
        order.refresh_from_db()
        self.assertNotIn(shop_payments.ESCROW_DELIVERY_NOTICE, order.od_mod_history)


@override_settings(**FAKE_TOSS)
class TossTaxFreeCancelTests(PartialCancelBase):
    def tax_order(self, **fields):
        ShopShippingPolicy.objects.filter(pk=1).update(de_send_cost_case="")
        order = self.toss_order(od_tax_flag=1, od_tax_mny=36364, od_vat_mny=3636, od_free_mny=10000, **fields)
        self.cap_line.ct_notax = 1
        self.cap_line.save(update_fields=["ct_notax"])
        return order

    def toss_payment(self, order, tax_free=10000, cancels=()):
        return fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "DONE",
                                   "taxFreeAmount": tax_free, "cancels": list(cancels)})

    def test_cancelling_a_tax_free_line_refunds_it_as_tax_free(self):
        order = self.tax_order()
        replies = [self.toss_payment(order), fake_http_response(
            {"orderId": order.od_id, "paymentKey": order.od_tno, "status": "PARTIAL_CANCELED"})]
        with patch(URLOPEN, side_effect=replies) as urlopen:
            result = change_order_lines(order, [self.cap_line.pk], "취소", "품절")
        self.assertTrue(result, result.message)
        lookup, cancel = (call.args[0] for call in urlopen.call_args_list)
        self.assertEqual((lookup.get_method(), lookup.full_url),
                         ("GET", f"https://api.tosspayments.com/v1/payments/{order.od_tno}"))
        self.assertEqual(json.loads(cancel.data), {"cancelReason": "품절", "cancelAmount": 10000, "taxFreeAmount": 10000})
        order.refresh_from_db()
        self.assertEqual(order.od_free_mny, 0)

    def test_full_cancel_sends_the_tax_free_part_left_at_toss(self):
        order = self.tax_order()
        replies = [self.toss_payment(order, cancels=[{"taxFreeAmount": 4000}]),
                   fake_http_response({"orderId": order.od_id, "status": "CANCELED"})]
        with patch(URLOPEN, side_effect=replies) as urlopen:
            shop_payments.toss_api_cancel_payment(order, "고객 요청")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"cancelReason": "고객 요청", "taxFreeAmount": 6000})

    def test_a_payment_toss_holds_without_a_tax_free_part_sends_none(self):
        order = self.tax_order()
        replies = [self.toss_payment(order, tax_free=0), fake_http_response(
            {"orderId": order.od_id, "paymentKey": order.od_tno, "status": "PARTIAL_CANCELED"})]
        with patch(URLOPEN, side_effect=replies) as urlopen:
            self.assertTrue(change_order_lines(order, [self.cap_line.pk], "취소"))
        self.assertNotIn("taxFreeAmount", json.loads(urlopen.call_args.args[0].data))

    def test_an_order_without_mixed_tax_never_looks_up_the_payment(self):
        order = self.toss_order()
        with patch(URLOPEN, return_value=fake_http_response({"orderId": order.od_id, "status": "CANCELED"})) as urlopen:
            shop_payments.toss_api_cancel_payment(order, "고객 요청")
        self.assertEqual(urlopen.call_count, 1)
        self.assertNotIn("taxFreeAmount", json.loads(urlopen.call_args.args[0].data))


@override_settings(**FAKE_TOSS)
class PersonalPayEscrowTests(PersonalPayCheckoutBase):
    def test_a_transfer_is_one_escrow_product_when_escrow_is_on(self):
        self.make_pay()
        set_config(de_escrow_use="1")
        prepare = f"{API}/personalpay/{PP_ID}/toss/prepare"
        data = self.client.post(prepare, {"method": "iche", "agree": True}, format="json").json()["data"]
        self.assertTrue(data["use_escrow"])
        self.assertEqual(data["escrow_products"],
                         [{"id": PP_ID, "name": "개인결제 Customer", "code": PP_ID, "unitPrice": 5000, "quantity": 1}])
        data = self.client.post(prepare, {"method": "card", "agree": True}, format="json").json()["data"]
        self.assertFalse(data["use_escrow"])


@override_settings(**NO_ENV)
class PgServiceNoneIsEnforcedTests(PaymentTestBase):
    def test_a_client_cannot_start_toss_when_the_admin_turned_the_pg_off(self):
        store_keys(test_client=TEST_CLIENT, test_secret=TEST_SECRET)
        set_config(de_pg_service="none")
        response = self.prepare(pg_service="toss")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "toss_payment_unconfigured")
        set_config(de_pg_service="toss")
        self.assertEqual(self.prepare(pg_service="toss").status_code, 200)
