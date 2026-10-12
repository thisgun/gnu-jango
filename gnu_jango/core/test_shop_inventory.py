"""Stock and order-cancellation behaviour.

The shop app carries no tests of its own, so the money- and inventory-critical
paths -- reserving stock for an order and putting it back when the order is
cancelled -- were only exercised incidentally. These pin the current behaviour.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.shop.inventory import (
    StockAdjustmentError,
    cancel_order_with_stock_restore,
    reserve_product_stock,
)
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopOrderItem, ShopProduct


class StockReservationTests(TestCase):
    def setUp(self):
        self.category = ShopCategory.objects.create(ca_id="20", ca_name="Stock category")
        self.product = ShopProduct.objects.create(
            it_id="TP001",
            category=self.category,
            it_name="Stock product",
            it_price=1000,
            it_stock_qty=10,
            it_use="1",
        )

    def test_reserving_stock_subtracts_the_ordered_quantity(self):
        reserve_product_stock(self.product.pk, 3)

        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 7)
        self.assertNotEqual(self.product.it_soldout, "1")

    def test_reserving_the_last_unit_marks_the_product_sold_out(self):
        reserve_product_stock(self.product.pk, 10)

        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 0)
        self.assertEqual(self.product.it_soldout, "1")

    def test_reserving_more_than_available_is_refused_and_changes_nothing(self):
        with self.assertRaises(StockAdjustmentError) as caught:
            reserve_product_stock(self.product.pk, 11)

        self.assertEqual(caught.exception.code, "insufficient_stock")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 10)

    def test_reserving_zero_or_negative_is_refused(self):
        for quantity in (0, -1):
            with self.subTest(quantity=quantity):
                with self.assertRaises(StockAdjustmentError) as caught:
                    reserve_product_stock(self.product.pk, quantity)
                self.assertEqual(caught.exception.code, "invalid_quantity")

        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 10)

    def test_reserving_a_disabled_product_is_refused(self):
        self.product.it_use = "0"
        self.product.save(update_fields=["it_use"])

        with self.assertRaises(StockAdjustmentError) as caught:
            reserve_product_stock(self.product.pk, 1)

        self.assertEqual(caught.exception.code, "product_unavailable")

    def test_reserving_an_unknown_product_is_refused(self):
        with self.assertRaises(StockAdjustmentError) as caught:
            reserve_product_stock("NOPE", 1)

        self.assertEqual(caught.exception.code, "product_not_found")


class OrderCancellationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="buyer", password="password123")
        self.other = User.objects.create_user(username="stranger", password="password123")
        self.category = ShopCategory.objects.create(ca_id="21", ca_name="Cancel category")
        self.product = ShopProduct.objects.create(
            it_id="TP002",
            category=self.category,
            it_name="Cancel product",
            it_price=1000,
            it_stock_qty=7,
            it_use="1",
        )
        self.order = ShopOrder.objects.create(
            od_id="TESTORD1",
            user=self.user,
            od_name="Buyer",
            od_cart_price=3000,
            od_receipt_price=3000,
            od_misu=3000,
            od_status="order",
        )
        self.item = ShopOrderItem.objects.create(
            order=self.order,
            product=self.product,
            ct_id="ct-1",
            it_id=self.product.it_id,
            it_name=self.product.it_name,
            ct_price=1000,
            ct_qty=3,
            stock_adjusted=True,
        )

    def auth_headers(self, user):
        access = RefreshToken.for_user(user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def test_cancelling_puts_the_reserved_stock_back(self):
        cancel_order_with_stock_restore(self.order, reason="테스트 취소")

        self.product.refresh_from_db()
        self.item.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 10)
        self.assertFalse(self.item.stock_adjusted)
        self.assertEqual(self.item.ct_status, "취소")
        self.assertEqual(self.order.od_status, "취소")

    def test_cancelling_clears_the_amount_still_owed(self):
        cancel_order_with_stock_restore(self.order)

        self.order.refresh_from_db()
        self.assertEqual(self.order.od_misu, 0)
        self.assertEqual(self.order.od_receipt_price, 0)
        self.assertEqual(self.order.od_cancel_price, 3000)

    def test_cancelling_twice_does_not_restore_stock_again(self):
        cancel_order_with_stock_restore(self.order)
        cancel_order_with_stock_restore(self.order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 10)

    def test_a_sold_out_product_becomes_orderable_again_after_a_cancel(self):
        self.product.it_stock_qty = 0
        self.product.it_soldout = "1"
        self.product.save(update_fields=["it_stock_qty", "it_soldout"])

        cancel_order_with_stock_restore(self.order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 3)
        self.assertNotEqual(self.product.it_soldout, "1")

    def test_cancel_endpoint_rejects_someone_elses_order(self):
        response = self.client.post(
            "/api/v1/shop/payment/cancel",
            data=json.dumps({"order_id": self.order.od_id}),
            content_type="application/json",
            **self.auth_headers(self.other),
        )

        self.assertIn(response.status_code, {403, 404})
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.od_status, "order")
        self.assertEqual(self.product.it_stock_qty, 7)
