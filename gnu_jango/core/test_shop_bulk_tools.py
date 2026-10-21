"""youngcart bulk admin tools: 상품 엑셀 일괄등록 (itemexcel), 재고 일괄수정 (itemstocklist), 옵션 재고
(optionstocklist), 송장 일괄등록 (orderdelivery), 후기 일괄 승인·숨김 (itemuselist), 주문 검색 항목
(orderlist), 개인결제 복사 (personalpaycopy) and 미수금 개인결제 (personalpayform?od_id=)."""

import csv
from unittest.mock import patch
from urllib.parse import quote
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from gnu_jango.shop.models import (
    ShopCategory,
    ShopOrder,
    ShopOrderItem,
    ShopPersonalPay,
    ShopProduct,
    ShopReview,
    ShopStockAdjustment,
)
from gnu_jango.shop.product_import import COLUMNS, FIELD_NAMES
from gnu_jango.shop.spreadsheet import SpreadsheetError, read_csv_upload

LABELS = [label for _name, label in COLUMNS]


def csv_upload(rows, *, name="upload.csv", encoding="utf-8-sig"):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return SimpleUploadedFile(name, buffer.getvalue().encode(encoding), content_type="text/csv")


def product_row(**values):
    return [values.get(name, "") for name in FIELD_NAMES]


def decoded_csv(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


class SuperuserMixin:
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("bulk-admin", "bulk@example.test", "pw")
        self.client.force_login(self.admin)
        self.category = ShopCategory.objects.create(ca_id="10", ca_name="의류")
        ShopCategory.objects.create(ca_id="1010", ca_name="상의")

    def staff_with(self, *codenames):
        user = get_user_model().objects.create_user("staff-" + "-".join(codenames)[:100], "s@example.test", "pw", is_staff=True)
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
        return user


class SpreadsheetReadingTests(TestCase):
    def test_reads_utf8_bom_and_cp949_and_drops_blank_rows(self):
        self.assertEqual(read_csv_upload(csv_upload([["상품코드"], [""], ["A1"]]), max_rows=10), [["상품코드"], ["A1"]])
        self.assertEqual(read_csv_upload(csv_upload([["상품명"], ["바지"]], encoding="cp949"), max_rows=10), [["상품명"], ["바지"]])

    def test_refuses_spreadsheet_binaries_oversized_and_too_many_rows(self):
        with self.assertRaisesMessage(SpreadsheetError, "CSV UTF-8"):
            read_csv_upload(SimpleUploadedFile("items.xlsx", b"PK\x03\x04data"), max_rows=10)
        with self.assertRaisesMessage(SpreadsheetError, "CSV 파일이 아닙니다"):
            read_csv_upload(SimpleUploadedFile("items.csv", b"PK\x03\x04data"), max_rows=10)
        with self.assertRaisesMessage(SpreadsheetError, "너무 큽니다"):
            read_csv_upload(SimpleUploadedFile("big.csv", b"a," * 100), max_rows=10, max_bytes=50)
        with self.assertRaisesMessage(SpreadsheetError, "3행까지"):
            read_csv_upload(csv_upload([["a"]] * 5), max_rows=3)

    def test_quoted_formula_cells_read_back_as_text(self):
        rows = read_csv_upload(csv_upload([["'=SUM(A1)", '="2026102100000000000001"', "=1+1"]]), max_rows=5)
        self.assertEqual(rows, [["=SUM(A1)", "2026102100000000000001", "=1+1"]])


class ProductUploadTests(SuperuserMixin, TestCase):
    url = "admin:shop_shopproduct_bulk_upload"

    def post(self, rows, *, step="apply", mode="create"):
        return self.client.post(
            reverse(self.url), {"file": csv_upload([LABELS, list(FIELD_NAMES), *rows]), "step": step, "mode": mode}
        )

    def test_template_download_has_youngcart_columns_and_uploads_back(self):
        response = self.client.get(reverse(self.url) + "?download=template")
        self.assertEqual(response.status_code, 200)
        rows = decoded_csv(response)
        self.assertEqual(rows[0][:5], ["상품코드", "기본분류", "2차분류", "3차분류", "상품명"])
        self.assertEqual(rows[1][0], "it_id")
        self.assertEqual(len(rows[1]), 40)
        response = self.client.post(
            reverse(self.url),
            {"file": SimpleUploadedFile("t.csv", response.content), "step": "apply", "mode": "create"},
        )
        self.assertContains(response, "반영")
        self.assertTrue(ShopProduct.objects.filter(pk="1700000001", it_name="예시 상품").exists())

    def test_preview_saves_nothing_and_apply_creates_valid_rows_only(self):
        rows = [
            product_row(it_id="P100", ca_id="10", ca_id2="1010", it_name="셔츠", it_price="12,000", it_stock_qty="5",
                        it_type1="1", it_img1="shirt/1.jpg", it_img2="https://cdn.example.test/2.jpg"),
            product_row(it_id="P101", ca_id="99", it_name="없는 분류"),
            product_row(it_id="P102", ca_id="10", it_name="가격 오류", it_price="abc"),
            product_row(it_id="P100", ca_id="10", it_name="중복"),
            product_row(it_id="P103", ca_id="10", it_name="이미지 오류", it_img1="javascript:alert(1)"),
            product_row(it_id="1.7E+09", ca_id="10", it_name="지수 코드"),
        ]
        response = self.post(rows, step="preview")
        self.assertContains(response, "미리보기")
        self.assertContains(response, "분류 &#x27;99&#x27;이(가) 없습니다.")
        self.assertFalse(ShopProduct.objects.exists())

        self.post(rows)
        product = ShopProduct.objects.get(pk="P100")
        self.assertEqual((product.it_price, product.it_stock_qty, product.it_type1, product.it_use), (12000, 5, "1", "1"))
        self.assertEqual(product.category2_id, "1010")
        self.assertEqual(product.image_url, "/data/item/shirt/1.jpg")
        self.assertEqual([image["url"] for image in product.images], ["/data/item/shirt/1.jpg", "https://cdn.example.test/2.jpg"])
        self.assertTrue(ShopProduct.objects.filter(pk="1700000000").exists())
        self.assertEqual(set(ShopProduct.objects.values_list("pk", flat=True)), {"P100", "1700000000"})

    def test_existing_codes_fail_in_create_mode_and_update_in_update_mode(self):
        ShopProduct.objects.create(it_id="P200", it_name="원래 이름", category=self.category, it_price=1000, it_stock_qty=3, it_brand="B")
        self.post([product_row(it_id="P200", it_name="새 이름")])
        self.assertEqual(ShopProduct.objects.get(pk="P200").it_name, "원래 이름")

        self.post([product_row(it_id="P200", it_name="새 이름", it_stock_qty="10")], mode="update")
        product = ShopProduct.objects.get(pk="P200")
        self.assertEqual((product.it_name, product.it_stock_qty, product.it_brand, product.it_price), ("새 이름", 10, "B", 1000))
        log = ShopStockAdjustment.objects.get(it_id="P200")
        self.assertEqual((log.before_qty, log.after_qty, log.actor), (3, 10, self.admin))

    def test_permissions(self):
        self.client.force_login(self.staff_with("view_shopproduct"))
        self.assertEqual(self.client.get(reverse(self.url)).status_code, 403)
        adder = self.staff_with("add_shopproduct")
        self.client.force_login(adder)
        self.assertEqual(self.client.get(reverse(self.url)).status_code, 200)
        self.assertEqual(self.post([product_row(it_id="X", ca_id="10", it_name="x")], mode="update").status_code, 403)

    def test_a_header_less_file_is_refused(self):
        response = self.client.post(reverse(self.url), {"file": csv_upload([["P1", "10", "", "", "이름"]]), "step": "apply"})
        self.assertContains(response, "항목 이름 행을 찾을 수 없습니다")


class StockListTests(SuperuserMixin, TestCase):
    url = "admin:shop_shopproduct_stock_list"

    def setUp(self):
        super().setUp()
        self.product = ShopProduct.objects.create(it_id="S1", it_name="양말", category=self.category, it_stock_qty=5)
        ShopProduct.objects.create(it_id="S2", it_name="모자", category=self.category, it_stock_qty=50)

    def post_row(self, **values):
        data = {"row_count": "1", "it_id_0": "S1", "stock_was_0": "5", "stock_0": "5", "use_0": "1", **values}
        return self.client.post(reverse(self.url) + "?low=10", data)

    def test_list_filters_by_low_stock_and_category(self):
        response = self.client.get(reverse(self.url) + "?low=10")
        self.assertContains(response, "양말")
        self.assertNotContains(response, "모자")
        self.assertContains(self.client.get(reverse(self.url) + "?ca=1010"), "조건에 맞는 상품이 없습니다")

    def test_bulk_save_sets_stock_and_flags_and_logs_the_change(self):
        response = self.post_row(stock_0="12", soldout_0="1", sms_0="1", reason="실사 반영")
        self.assertRedirects(response, reverse(self.url) + "?low=10", fetch_redirect_response=False)
        self.product.refresh_from_db()
        self.assertEqual((self.product.it_stock_qty, self.product.it_soldout, self.product.it_stock_sms, self.product.it_use), (12, "1", "1", "1"))
        log = ShopStockAdjustment.objects.get(it_id="S1")
        self.assertEqual((log.scope, log.before_qty, log.delta, log.after_qty, log.reason), ("product", 5, 7, 12, "실사 반영"))

        self.post_row(stock_0="12", stock_was_0="12", use_0="")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_use, "0")
        self.assertEqual(ShopStockAdjustment.objects.count(), 1)

    def test_a_stock_change_made_meanwhile_is_not_overwritten(self):
        ShopProduct.objects.filter(pk="S1").update(it_stock_qty=4)  # an order reserved one
        response = self.post_row(stock_0="20")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 4)
        self.assertFalse(ShopStockAdjustment.objects.exists())
        self.assertIn("바뀌어 저장하지 않았습니다", " ".join(str(m) for m in response.wsgi_request._messages))

    def test_switches_still_save_when_only_the_live_stock_moved(self):
        ShopProduct.objects.filter(pk="S1").update(it_stock_qty=4)  # an order reserved one
        response = self.post_row(soldout_0="1")  # stock left at the 5 the list showed
        self.product.refresh_from_db()
        self.assertEqual((self.product.it_stock_qty, self.product.it_soldout), (4, "1"))
        self.assertFalse(ShopStockAdjustment.objects.exists())
        self.assertNotIn("바뀌어 저장하지 않았습니다", " ".join(str(m) for m in response.wsgi_request._messages))

    def test_invalid_quantity_is_reported(self):
        self.post_row(stock_0="-3")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 5)

    def test_view_permission_lists_but_cannot_save(self):
        self.client.force_login(self.staff_with("view_shopproduct"))
        self.assertEqual(self.client.get(reverse(self.url)).status_code, 200)
        self.assertEqual(self.post_row(stock_0="9").status_code, 403)
        self.client.force_login(self.staff_with("view_shoporder"))
        self.assertEqual(self.client.get(reverse(self.url)).status_code, 403)


class OptionStockListTests(SuperuserMixin, TestCase):
    url = "admin:shop_shopproduct_option_stock_list"

    def setUp(self):
        super().setUp()
        self.product = ShopProduct.objects.create(
            it_id="O1",
            it_name="티셔츠",
            category=self.category,
            options=[
                {"io_id": "빨강\x1eS", "io_type": 0, "io_stock_qty": 3, "io_noti_qty": 5, "io_use": 1},
                {"io_id": "포장", "io_type": 1, "io_stock_qty": 100, "io_use": 1},
            ],
        )

    def test_lists_every_option_and_filters_below_the_notice_quantity(self):
        response = self.client.get(reverse(self.url))
        self.assertContains(response, "빨강 / S")
        self.assertContains(response, "포장")
        response = self.client.get(reverse(self.url) + "?below_noti=1")
        self.assertContains(response, "빨강 / S")
        self.assertNotContains(response, "포장")

    def test_bulk_save_updates_the_option_json_and_logs_stock(self):
        data = {
            "row_count": "2",
            "it_id_0": "O1", "io_type_0": "0", "io_key_0": quote("빨강\x1eS", safe=""), "stock_was_0": "3", "stock_0": "8", "noti_0": "2", "use_0": "1",
            "it_id_1": "O1", "io_type_1": "1", "io_key_1": quote("포장", safe=""), "stock_was_1": "100", "stock_1": "100", "noti_1": "0",
        }
        self.client.post(reverse(self.url), data)
        self.product.refresh_from_db()
        first, second = self.product.options
        self.assertEqual((first["io_stock_qty"], first["io_noti_qty"], first["io_use"]), (8, 2, 1))
        self.assertEqual(second["io_use"], 0)
        log = ShopStockAdjustment.objects.get()
        self.assertEqual((log.scope, log.io_id, log.io_type, log.before_qty, log.after_qty), ("option", "빨강\x1eS", 0, 3, 8))

    def test_option_switches_save_when_only_the_live_stock_moved(self):
        options = self.product.options
        options[0]["io_stock_qty"] = 2  # an order took one meanwhile
        ShopProduct.objects.filter(pk="O1").update(options=options)
        data = {
            "row_count": "1",
            "it_id_0": "O1", "io_type_0": "0", "io_key_0": quote("빨강\x1eS", safe=""), "stock_was_0": "3", "stock_0": "3", "noti_0": "1",
        }
        self.client.post(reverse(self.url), data)
        self.product.refresh_from_db()
        first = self.product.options[0]
        self.assertEqual((first["io_stock_qty"], first["io_noti_qty"], first["io_use"]), (2, 1, 0))
        self.assertFalse(ShopStockAdjustment.objects.exists())

        # a typed quantity over the moved one is still refused
        data.update({"stock_was_0": "3", "stock_0": "9", "use_0": "1"})
        self.client.post(reverse(self.url), data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.options[0]["io_stock_qty"], 2)

    def test_unknown_option_is_reported_not_created(self):
        data = {"row_count": "1", "it_id_0": "O1", "io_type_0": "0", "io_key_0": quote("파랑", safe=""), "stock_was_0": "1", "stock_0": "9", "use_0": "1"}
        self.client.post(reverse(self.url), data)
        self.product.refresh_from_db()
        self.assertEqual(len(self.product.options), 2)
        self.assertFalse(ShopStockAdjustment.objects.exists())


class ReviewActionTests(SuperuserMixin, TestCase):
    def test_approve_and_hide_recount_the_product(self):
        product = ShopProduct.objects.create(it_id="R1", it_name="리뷰 상품")
        first = ShopReview.objects.create(product=product, is_subject="좋아요", is_score=5, is_confirm="0")
        second = ShopReview.objects.create(product=product, is_subject="보통", is_score=3, is_confirm="0")
        url = reverse("admin:shop_shopreview_changelist")
        self.client.post(url, {"action": "approve_selected_reviews", "_selected_action": [first.pk, second.pk]})
        product.refresh_from_db()
        self.assertEqual((product.it_use_cnt, str(product.it_use_avg)), (2, "4.0"))
        self.client.post(url, {"action": "hide_selected_reviews", "_selected_action": [second.pk]})
        product.refresh_from_db()
        self.assertEqual((product.it_use_cnt, str(product.it_use_avg)), (1, "5.0"))
        self.assertEqual(ShopReview.objects.get(pk=second.pk).is_confirm, "0")


class DeliveryUploadTests(SuperuserMixin, TestCase):
    url = "admin:shop_shopproduct_bulk_upload"

    def setUp(self):
        super().setUp()
        self.url = reverse("admin:shop_shoporder_delivery_upload")
        self.ready = ShopOrder.objects.create(
            od_id="2026102100000000000001", od_name="홍길동", od_email="buyer@example.test", od_b_name="김수령",
            od_status="준비", od_settle_case="무통장", od_cart_price=1000, od_receipt_price=1000,
        )
        ShopOrderItem.objects.create(order=self.ready, ct_id="L1", it_id="X", it_name="상품", ct_price=1000, ct_status="준비")
        self.paid = ShopOrder.objects.create(od_id="2026102100000000000002", od_name="이몽룡", od_status="입금")

    def upload(self, rows, step="apply"):
        header = ["주문번호", "주문자명", "주문자전화1", "주문자전화2", "배송자명", "배송지전화1", "배송지전화2", "배송지주소", "배송회사", "운송장번호"]
        return self.client.post(self.url, {"file": csv_upload([header, *rows]), "step": step})

    def test_template_lists_ready_orders_with_the_order_id_kept_as_text(self):
        rows = decoded_csv(self.client.get(self.url + "?download=template"))
        self.assertEqual(rows[0][8:], ["배송회사", "운송장번호"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], '="2026102100000000000001"')

    def test_preview_changes_nothing_then_apply_moves_ready_orders_to_shipping(self):
        rows = [
            ["2026102100000000000001", "", "", "", "", "", "", "", "CJ대한통운", "123-456"],
            ["2026102100000000000002", "", "", "", "", "", "", "", "CJ대한통운", "999"],
            ["NOPE", "", "", "", "", "", "", "", "CJ대한통운", "1"],
            ["2.03E+19", "", "", "", "", "", "", "", "CJ대한통운", "1"],
            ["2026102100000000000003", "", "", "", "", "", "", "", "CJ대한통운", "1.23E+11"],
        ]
        response = self.upload(rows, step="preview")
        self.assertContains(response, "준비 상태의 주문만")
        self.assertContains(response, "주문번호가 지수 형식")
        self.assertContains(response, "운송장번호가 지수 형식")
        self.ready.refresh_from_db()
        self.assertEqual(self.ready.od_status, "준비")

        with self.captureOnCommitCallbacks(execute=True):
            self.upload(rows)
        self.ready.refresh_from_db()
        self.assertEqual((self.ready.od_status, self.ready.od_delivery_company, self.ready.od_invoice), ("배송", "CJ대한통운", "123-456"))
        self.assertTrue(self.ready.od_invoice_time)
        self.assertEqual(self.ready.items.get().ct_status, "배송")
        self.paid.refresh_from_db()
        self.assertEqual((self.paid.od_status, self.paid.od_invoice), ("입금", ""))
        self.assertEqual(len(mail.outbox), 1)

    def test_the_shipping_text_goes_out_only_when_the_sms_box_is_ticked(self):
        row = ["2026102100000000000001", "", "", "", "", "", "", "", "CJ대한통운", "123-456"]
        header = ["주문번호", "주문자명", "주문자전화1", "주문자전화2", "배송자명", "배송지전화1", "배송지전화2", "배송지주소", "배송회사", "운송장번호"]
        with patch("gnu_jango.shop.sms.notifications.queue_order_status_sms") as queued:
            self.upload([row])
            queued.assert_not_called()
            self.ready.refresh_from_db()
            self.assertEqual(self.ready.od_status, "배송")
            # a second ready order, uploaded with 배송안내 문자 발송 ticked
            self.ready.od_status = "준비"
            self.ready.save(update_fields=["od_status"])
            self.client.post(self.url, {"file": csv_upload([header, row]), "step": "apply", "send_sms": "1"})
        queued.assert_called_once()
        self.assertEqual(queued.call_args.args[1], "배송")

    def test_rows_without_courier_or_invoice_fail_and_headerless_files_use_youngcart_columns(self):
        response = self.client.post(
            self.url,
            {"file": csv_upload([["2026102100000000000001", "", "", "", "", "", "", "", "", ""]]), "step": "apply"},
        )
        self.assertContains(response, "배송회사가 없습니다")
        self.assertContains(response, "운송장번호가 없습니다")
        self.ready.refresh_from_db()
        self.assertEqual(self.ready.od_status, "준비")

    def test_requires_order_change_permission(self):
        self.client.force_login(self.staff_with("view_shoporder"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url + "?download=template").status_code, 403)


class OrderSearchTests(SuperuserMixin, TestCase):
    def test_search_covers_recipient_depositor_member_and_phones(self):
        member = get_user_model().objects.create_user("buyer01", "b@example.test", "pw")
        ShopOrder.objects.create(od_id="Q1", od_name="주문자", od_b_name="받는이름", od_deposit_name="입금자명", user=member,
                                 od_tel="02-111-2222", od_b_hp="010-9999-8888")
        url = reverse("admin:shop_shoporder_changelist")
        for term in ("받는이름", "입금자명", "buyer01", "02-111-2222", "010-9999-8888"):
            with self.subTest(term=term):
                self.assertContains(self.client.get(url, {"q": term}), "Q1")


class PersonalPayActionTests(SuperuserMixin, TestCase):
    def test_copy_creates_a_fresh_request_with_the_same_customer_and_amount(self):
        source = ShopPersonalPay.objects.create(
            pp_id="PP1", pp_name="고객", pp_price=5000, pp_receipt_price=5000, pp_tno="T1", pp_content="추가금", pp_hp="010"
        )
        response = self.client.post(
            reverse("admin:shop_shoppersonalpay_changelist"),
            {"action": "copy_selected_personal_pays", "_selected_action": [source.pk]},
        )
        copy = ShopPersonalPay.objects.exclude(pk="PP1").get()
        self.assertRedirects(response, reverse("admin:shop_shoppersonalpay_change", args=[copy.pk]), fetch_redirect_response=False)
        self.assertEqual((copy.pp_name, copy.pp_price, copy.pp_content, copy.pp_hp), ("고객", 5000, "추가금", "010"))
        self.assertEqual((copy.pp_receipt_price, copy.pp_tno, copy.pp_receipt_time), (0, "", ""))

    def test_a_copy_is_not_linked_to_the_source_order(self):
        order = ShopOrder.objects.create(od_id="C1", od_name="x")
        source = ShopPersonalPay.objects.create(pp_id="PP2", pp_name="고객", pp_price=1000, order=order)
        self.client.post(
            reverse("admin:shop_shoppersonalpay_changelist"),
            {"action": "copy_selected_personal_pays", "_selected_action": [source.pk]},
        )
        self.assertIsNone(ShopPersonalPay.objects.exclude(pk="PP2").get().order_id)

    def test_order_balance_becomes_a_linked_personal_pay(self):
        order = ShopOrder.objects.create(od_id="M1", od_name="미수 고객", od_status="주문", od_cart_price=30000, od_receipt_price=10000,
                                         od_settle_case="무통장", od_misu=20000)
        settled = ShopOrder.objects.create(od_id="M2", od_name="완납", od_status="입금", od_cart_price=1000, od_receipt_price=1000)
        self.client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "create_personal_pay_for_balance", "_selected_action": [order.pk, settled.pk]},
        )
        pay = ShopPersonalPay.objects.get()
        self.assertEqual((pay.order_id, pay.pp_name, pay.pp_price, pay.active), ("M1", "미수 고객", 20000, True))
        self.assertIn("M1", pay.pp_content)
        # a second run does not ask for the same balance twice
        self.client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "create_personal_pay_for_balance", "_selected_action": [order.pk]},
        )
        self.assertEqual(ShopPersonalPay.objects.count(), 1)

    def test_balance_action_needs_the_personal_pay_add_permission(self):
        staff = self.staff_with("view_shoporder", "change_shoporder")
        self.client.force_login(staff)
        order = ShopOrder.objects.create(od_id="M3", od_name="x", od_cart_price=1000, od_settle_case="무통장")
        self.client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "create_personal_pay_for_balance", "_selected_action": [order.pk]},
        )
        self.assertFalse(ShopPersonalPay.objects.exists())


class ToolPagesRenderTests(SuperuserMixin, TestCase):
    def test_every_tool_page_opens_for_a_superuser(self):
        for name in (
            "admin:shop_shopproduct_bulk_upload",
            "admin:shop_shopproduct_stock_list",
            "admin:shop_shopproduct_option_stock_list",
            "admin:shop_shopproduct_price_compare",
            "admin:shop_shopproduct_wishlist_report",
            "admin:shop_shoporder_delivery_upload",
            "admin:shop_shoporder_sales",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("Content-Security-Policy", response.headers)

    def test_anonymous_visitors_go_to_the_login_page(self):
        self.client.logout()
        response = self.client.get(reverse("admin:shop_shopproduct_stock_list"))
        self.assertEqual(response.status_code, 302)
