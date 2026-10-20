"""youngcart purchase points (구매 포인트): recorded per order line, paid after the line has been
완료 for de_point_days days, never twice, and taken back when a paid line leaves 완료."""

import io
import json
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_payments_api import FAKE_TOSS, FAKE_TOSS_VBANK, ORDER_FIELDS, PREPARE_URL
from gnu_jango.shop import order_points
from gnu_jango.shop.admin.orders import set_order_status
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopOrderItem, ShopProduct, ShopShippingPolicy
from gnu_jango.shop.order_points import (
    item_purchase_point,
    item_status_update,
    order_line_points_enabled,
    save_order_points,
    take_back_order_points,
)
from gnu_jango.users.models import Profile, User_Point

BANK_ACCOUNT = "Test Bank 000-00 Holder"
COMPLETED = "완료"


def set_config(name, value):
    Config.objects.update_or_create(name=name, defaults={"value": str(value)})


def product_stub(**fields):
    values = {"it_price": 0, "it_point": 0, "it_point_type": 0, **fields}
    return SimpleNamespace(**values)


class ItemPurchasePointTests(TestCase):
    def test_a_fixed_point_is_used_as_it_is(self):
        self.assertEqual(item_purchase_point(product_stub(it_price=12000, it_point=500)), 500)

    def test_a_percentage_point_is_rounded_down_to_ten_won(self):
        product = product_stub(it_price=12345, it_point=5, it_point_type=1)
        self.assertEqual(item_purchase_point(product), 610)  # 617.25 -> 610

    def test_type_one_ignores_the_option_price(self):
        product = product_stub(it_price=10000, it_point=10, it_point_type=1)
        self.assertEqual(item_purchase_point(product, io_price=5000, has_option=True), 1000)

    def test_type_two_adds_the_option_price(self):
        product = product_stub(it_price=10000, it_point=10, it_point_type=2)
        self.assertEqual(item_purchase_point(product, io_price=2000, has_option=True), 1200)
        self.assertEqual(item_purchase_point(product, io_price=2000, has_option=False), 1000)

    def test_supplement_lines_and_missing_products_earn_nothing(self):
        product = product_stub(it_price=10000, it_point=500)
        self.assertEqual(item_purchase_point(product, io_type=1, io_price=3000, has_option=True), 0)
        self.assertEqual(item_purchase_point(None), 0)

    def test_a_negative_point_is_clamped_to_zero(self):
        self.assertEqual(item_purchase_point(product_stub(it_price=1000, it_point=-100)), 0)
        self.assertEqual(item_purchase_point(product_stub(it_price=-1000, it_point=10, it_point_type=1)), 0)


class SettleCaseRuleTests(TestCase):
    def test_pg_orders_earn_no_points_unless_de_card_point_is_on(self):
        for settle_case in ("card", "신용카드", "iche", "계좌이체", "hp", "휴대폰", "easy_pay", "tosspay"):
            self.assertFalse(order_line_points_enabled(settle_case, 10000), settle_case)
        set_config("de_card_point", "1")
        for settle_case in ("card", "iche", "hp"):
            self.assertTrue(order_line_points_enabled(settle_case, 10000), settle_case)

    def test_bank_virtual_account_and_free_orders_keep_points(self):
        for settle_case in ("bank", "무통장", "무통장입금", "vbank", "가상계좌"):
            self.assertTrue(order_line_points_enabled(settle_case, 10000), settle_case)
        self.assertTrue(order_line_points_enabled("card", 0))

    def test_nothing_is_recorded_while_points_are_off(self):
        set_config("cf_use_point", "0")
        self.assertFalse(order_line_points_enabled("bank", 10000))


class PurchasePointBase(TestCase):
    PRICE = 100000

    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="buyer", email="buyer@example.test", password="password")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        category = ShopCategory.objects.create(ca_id="50", ca_name="Point category")
        # 3% of the price: 3,000 points per unit
        self.product = ShopProduct.objects.create(
            it_id="PP001", category=category, it_name="Point product", it_price=self.PRICE,
            it_point=3, it_point_type=1, it_stock_qty=50, it_use="1",
        )
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_delivery_company": "Courier"})
        set_config("de_bank_use", "1")
        set_config("de_bank_account", BANK_ACCOUNT)
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def bank_order(self, qty=1):
        response = self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": qty}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        response = self.client.post(
            "/api/v1/shop/orders",
            {**ORDER_FIELDS, "od_settle_case": "bank", "od_bank_account": BANK_ACCOUNT, "od_deposit_name": "Buyer"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])

    def make_order(self, *, user=True, ct_point=3000, qty=2, status="배송", od_id="2026102000001"):
        order = ShopOrder.objects.create(od_id=od_id, user=self.member if user else None, od_status=status)
        ShopOrderItem.objects.create(
            order=order, product=self.product, ct_id="1", it_id=self.product.it_id, it_name="Point product",
            ct_price=self.PRICE, ct_qty=qty, ct_point=ct_point, ct_status=status,
        )
        return order

    def balance(self):
        return Profile.objects.get(user=self.member).user_point

    def delivery_rows(self):
        return User_Point.objects.filter(user=self.member, po_rel_table="@delivery")


class OrderLinePointTests(PurchasePointBase):
    def test_a_bank_order_records_the_purchase_point(self):
        order = self.bank_order(qty=2)
        item = order.items.get()
        self.assertEqual(item.ct_point, 3000)
        self.assertFalse(item.ct_point_use)
        self.assertIsNone(item.ct_complete_time)

    def test_no_purchase_point_is_recorded_while_points_are_off(self):
        set_config("cf_use_point", "0")
        self.assertEqual(self.bank_order().items.get().ct_point, 0)

    def prepare(self, settle_case):
        self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        response = self.client.post(
            PREPARE_URL, {**ORDER_FIELDS, "od_settle_case": settle_case, "pg_service": "toss"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

    @override_settings(**FAKE_TOSS)
    def test_a_card_order_records_no_point_while_de_card_point_is_off(self):
        self.assertEqual(self.prepare("card").items.get().ct_point, 0)

    @override_settings(**FAKE_TOSS)
    def test_a_card_order_records_the_point_when_de_card_point_is_on(self):
        set_config("de_card_point", "1")
        self.assertEqual(self.prepare("card").items.get().ct_point, 3000)

    @override_settings(**FAKE_TOSS_VBANK)
    def test_a_virtual_account_order_keeps_the_point(self):
        self.assertEqual(self.prepare("가상계좌").items.get().ct_point, 3000)

    def test_payment_config_reports_the_purchase_point_rule(self):
        data = self.client.get("/api/v1/shop/payment/config").json()["data"]
        self.assertEqual(data["purchase_point"], {"enabled": True, "pg_orders": False})
        set_config("de_card_point", "1")
        set_config("cf_use_point", "0")
        data = self.client.get("/api/v1/shop/payment/config").json()["data"]
        self.assertEqual(data["purchase_point"], {"enabled": False, "pg_orders": True})


class CompleteTimeTests(PurchasePointBase):
    def test_saving_a_line_as_completed_stamps_it_and_leaving_clears_it(self):
        order = self.make_order()
        item = order.items.get()
        item.ct_status = COMPLETED
        item.save(update_fields=["ct_status"])
        item.refresh_from_db()
        stamped = item.ct_complete_time
        self.assertIsNotNone(stamped)
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.ct_complete_time, stamped)  # staying 완료 keeps the first time
        item.ct_status = "배송"
        item.save(update_fields=["ct_status"])
        item.refresh_from_db()
        self.assertIsNone(item.ct_complete_time)

    def test_the_complete_time_is_assigned_before_the_status(self):
        # MySQL evaluates SET left to right: the CASE must see the old status
        for status in (COMPLETED, "배송"):
            self.assertEqual(list(item_status_update(status)), ["ct_complete_time", "ct_status"])

    def test_the_bulk_status_update_keeps_an_existing_complete_time(self):
        order = self.make_order(status=COMPLETED)
        earlier = timezone.now() - timedelta(days=3)
        order.items.update(ct_complete_time=earlier)
        order.items.update(**item_status_update(COMPLETED))
        self.assertEqual(order.items.get().ct_complete_time, earlier)
        order.items.update(**item_status_update("배송"))
        self.assertIsNone(order.items.get().ct_complete_time)
        order.items.update(**item_status_update(COMPLETED))
        self.assertIsNotNone(order.items.get().ct_complete_time)


class SaveOrderPointsTests(PurchasePointBase):
    def test_zero_days_pays_as_soon_as_the_admin_completes_the_order(self):
        set_config("de_point_days", "0")
        order = self.make_order()
        self.assertTrue(set_order_status(order, COMPLETED, "test"))
        item = order.items.get()
        self.assertTrue(item.ct_point_use)
        self.assertIsNotNone(item.ct_complete_time)
        self.assertEqual(self.balance(), 6000)
        row = self.delivery_rows().get()
        self.assertEqual((row.po_rel_id, row.po_rel_action, row.po_point), (item.pk, order.od_id, 6000))
        self.assertEqual(row.po_content, f"주문번호 {order.od_id} (1) 배송완료")

    def test_the_admin_bulk_action_pays_once_after_the_selection(self):
        set_config("de_point_days", "0")
        order = self.make_order()
        self.assertTrue(set_order_status(order, COMPLETED, "test", pay_due_points=False))
        self.assertEqual(self.balance(), 0)
        admin = get_user_model().objects.create_superuser("bulkadmin", "bulkadmin@example.test", "password")
        self.client.force_login(admin)
        order.items.update(ct_status="배송", ct_complete_time=None)
        ShopOrder.objects.filter(pk=order.pk).update(od_status="배송")
        response = self.client.post(
            "/admin/shop/shoporder/",
            {"action": "change_selected_order_status", "_selected_action": [order.pk], "od_status": COMPLETED},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.balance(), 6000)

    def test_the_point_waits_for_de_point_days(self):
        set_config("de_point_days", "7")
        order = self.make_order()
        set_order_status(order, COMPLETED, "test")
        self.assertEqual(self.balance(), 0)
        self.assertFalse(order.items.get().ct_point_use)
        self.assertEqual(save_order_points(timezone.now() + timedelta(days=6))["marked"], 0)
        summary = save_order_points(timezone.now() + timedelta(days=7, minutes=1))
        self.assertEqual((summary["awarded"], summary["points"]), (1, 6000))
        self.assertEqual(self.balance(), 6000)

    def test_running_twice_pays_once(self):
        set_config("de_point_days", "0")
        order = self.make_order(status=COMPLETED)
        self.assertEqual(save_order_points()["awarded"], 1)
        self.assertEqual(save_order_points()["due"], 0)
        # a second claim on the same line (another worker) finds nothing to do
        self.assertIsNone(order_points._award_line(order.items.get().pk))
        # even a line whose flag was lost is not paid twice: the ledger refuses the duplicate
        order.items.update(ct_point_use=False)
        self.assertEqual(save_order_points()["awarded"], 0)
        self.assertTrue(order.items.get().ct_point_use)
        self.assertEqual(self.balance(), 6000)
        self.assertEqual(self.delivery_rows().count(), 1)

    def test_guest_and_zero_point_lines_are_marked_without_points(self):
        set_config("de_point_days", "0")
        guest = self.make_order(user=False, status=COMPLETED, od_id="2026102000002")
        zero = self.make_order(ct_point=0, status=COMPLETED, od_id="2026102000003")
        summary = save_order_points()
        self.assertEqual((summary["marked"], summary["awarded"]), (2, 0))
        self.assertTrue(guest.items.get().ct_point_use)
        self.assertTrue(zero.items.get().ct_point_use)
        self.assertEqual(User_Point.objects.filter(po_rel_table="@delivery").count(), 0)

    def test_nothing_is_paid_or_marked_while_points_are_off(self):
        set_config("de_point_days", "0")
        order = self.make_order(status=COMPLETED)
        set_config("cf_use_point", "0")
        self.assertEqual(save_order_points()["skipped"], "points_disabled")
        self.assertFalse(order.items.get().ct_point_use)
        set_config("cf_use_point", "1")
        self.assertEqual(save_order_points()["awarded"], 1)
        self.assertEqual(self.balance(), 6000)

    def test_a_completed_line_without_a_time_starts_its_clock_now(self):
        set_config("de_point_days", "7")
        order = self.make_order()
        order.items.update(ct_status=COMPLETED, ct_complete_time=None)  # a path that did not stamp
        summary = save_order_points()
        self.assertEqual((summary["stamped"], summary["marked"]), (1, 0))
        self.assertIsNotNone(order.items.get().ct_complete_time)
        self.assertEqual(save_order_points(timezone.now() + timedelta(days=8))["awarded"], 1)

    def test_the_command_is_a_dry_run_without_apply(self):
        set_config("de_point_days", "0")
        order = self.make_order(status=COMPLETED)
        out = io.StringIO()
        call_command("save_order_points", "--json", stdout=out)
        self.assertEqual(json.loads(out.getvalue())["due"], 1)
        self.assertFalse(order.items.get().ct_point_use)
        out = io.StringIO()
        call_command("save_order_points", "--apply", "--json", stdout=out)
        self.assertEqual(json.loads(out.getvalue())["awarded"], 1)
        self.assertTrue(order.items.get().ct_point_use)

    def test_opening_the_order_in_the_admin_pays_due_points(self):
        set_config("de_point_days", "0")
        order = self.make_order(status=COMPLETED)
        admin = get_user_model().objects.create_superuser("shopadmin", "shopadmin@example.test", "password")
        self.client.force_login(admin)
        response = self.client.get(f"/admin/shop/shoporder/{order.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(order.items.get().ct_point_use)
        self.assertEqual(self.balance(), 6000)


class TakeBackTests(PurchasePointBase):
    def paid_order(self):
        set_config("de_point_days", "0")
        order = self.make_order()
        set_order_status(order, COMPLETED, "test")
        self.assertEqual(self.balance(), 6000)
        return order

    def assert_taken_back(self, order):
        item = order.items.get()
        self.assertFalse(item.ct_point_use)
        self.assertIsNone(item.ct_complete_time)
        self.assertEqual(self.balance(), 0)
        self.assertFalse(self.delivery_rows().exists())

    def test_an_admin_cancel_of_a_completed_order_is_refused_and_keeps_the_point(self):
        # youngcart orderlistupdate.php cancels only 주문/입금/준비 orders; a completed one is a return
        order = self.paid_order()
        self.assertFalse(set_order_status(order, "취소", "test"))
        self.assertEqual(order.items.get().ct_status, COMPLETED)
        self.assertEqual(self.balance(), 6000)

    def test_cancelling_a_line_that_earned_its_point_takes_it_back(self):
        order = self.paid_order()
        ShopOrder.objects.filter(pk=order.pk).update(od_status="준비")
        self.assertTrue(set_order_status(order, "취소", "test"))
        self.assert_taken_back(order)
        self.assertEqual(order.items.get().ct_status, "취소")

    def test_the_shared_cancel_path_takes_the_point_back_once(self):
        order = self.paid_order()
        cancel_order_and_refund_benefits(order, "test")
        cancel_order_and_refund_benefits(order, "test")
        self.assert_taken_back(order)

    def test_moving_a_paid_line_off_completed_takes_it_back_and_completing_pays_again(self):
        # the admin no longer moves an order back; the virtual account webhook still can
        order = self.paid_order()
        ShopOrder.objects.filter(pk=order.pk).update(od_status="배송")
        order.items.update(**item_status_update("배송"))
        take_back_order_points(order)
        self.assert_taken_back(order)
        set_order_status(order, COMPLETED, "test")
        self.assertEqual(self.balance(), 6000)
        self.assertEqual(self.delivery_rows().count(), 1)

    def test_a_point_imported_from_gnuboard5_is_taken_back_by_its_legacy_key(self):
        order = self.make_order(status="취소")
        order.items.update(ct_point_use=True)
        self.profile.user_point = 6000
        self.profile.save(update_fields=["user_point"])
        User_Point.objects.create(
            user=self.member, po_datetime=timezone.now(), po_content="legacy", po_point=6000, po_use_point=0,
            po_mb_point=6000, po_expired=0, po_rel_table="@delivery", po_rel_id=0, po_rel_action=f"{order.od_id},1",
        )
        self.assertEqual(take_back_order_points(order), 1)
        self.assert_taken_back(order)


class Gnuboard5ImportTests(PurchasePointBase):
    def import_rows(self, rows):
        from gnu_jango.core.management.commands.migrate_gnuboard5 import Command

        return Command().import_shop_cart_items(rows)

    def cart_row(self, **fields):
        return {"od_id": "2026102000009", "ct_id": 7, "it_id": self.product.it_id, "it_name": "Point product",
                "ct_price": self.PRICE, "ct_qty": 1, "ct_point": 3000, "ct_status": COMPLETED, **fields}

    def test_completed_lines_keep_their_point_state(self):
        ShopOrder.objects.create(od_id="2026102000009", user=self.member, od_status=COMPLETED)
        self.import_rows([self.cart_row(ct_point_use=1, ct_complete_time="2026-10-01 10:00:00")])
        item = ShopOrderItem.objects.get(order_id="2026102000009")
        self.assertTrue(item.ct_point_use)
        self.assertEqual(timezone.localtime(item.ct_complete_time).strftime("%Y-%m-%d %H:%M"), "2026-10-01 10:00")
        set_config("de_point_days", "0")
        self.assertEqual(save_order_points()["due"], 0)

    def test_an_unpaid_completed_line_counts_from_its_cart_time(self):
        ShopOrder.objects.create(od_id="2026102000009", user=self.member, od_status=COMPLETED)
        self.import_rows([self.cart_row(ct_point_use=0, ct_complete_time=None, ct_time="2026-09-01 09:00:00")])
        item = ShopOrderItem.objects.get(order_id="2026102000009")
        self.assertFalse(item.ct_point_use)
        self.assertEqual(timezone.localtime(item.ct_complete_time).strftime("%Y-%m-%d"), "2026-09-01")

    def test_a_completed_row_without_the_column_counts_as_paid(self):
        ShopOrder.objects.create(od_id="2026102000009", user=self.member, od_status=COMPLETED)
        self.import_rows([self.cart_row()])
        self.assertTrue(ShopOrderItem.objects.get(order_id="2026102000009").ct_point_use)
