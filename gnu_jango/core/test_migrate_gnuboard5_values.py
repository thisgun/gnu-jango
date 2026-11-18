"""migrate_gnuboard5 run against a fake Gnuboard5/YoungCart source: the imported shop sells,
discounts and restocks the way the PHP shop did."""

from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import TestCase

from gnu_jango.core.management.commands import migrate_gnuboard5
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command
from gnu_jango.core.models import Poll
from gnu_jango.shop.inventory import cancel_order_with_stock_restore
from gnu_jango.shop.models import ShopCoupon, ShopCouponZone, ShopOrder, ShopOrderItem, ShopProduct, ShopReview
from gnu_jango.shop.stock_forecast import stock_level
from gnu_jango.users.models import User_Memo

CONFIG = {
    "tables": {
        "member_table": "g5_member",
        "memo_table": "g5_memo",
        "poll_table": "g5_poll",
        "g5_shop_item_table": "g5_shop_item",
        "g5_shop_item_use_table": "g5_shop_item_use",
        "g5_shop_item_option_table": "g5_shop_item_option",
        "g5_shop_order_table": "g5_shop_order",
        "g5_shop_cart_table": "g5_shop_cart",
        "g5_shop_coupon_zone_table": "g5_shop_coupon_zone",
        "g5_shop_coupon_table": "g5_shop_coupon",
    }
}
SHOP = {"shop_item", "shop_item_option", "shop_order", "shop_cart"}


def item(it_id, **fields):
    return {"it_id": it_id, "it_name": it_id, "it_use": "1", "it_soldout": 0, "it_stock_qty": 10, **fields}


def option(it_id, io_id, **fields):
    return {"it_id": it_id, "io_id": io_id, "io_type": 0, "io_no": 0, "io_price": 0, "io_stock_qty": 10, "io_use": 1, **fields}


def cart(ct_id, it_id, ct_status, ct_qty, ct_stock_use, io_id="", od_id=1001, **fields):
    return {
        "ct_id": ct_id, "od_id": od_id, "it_id": it_id, "it_name": it_id, "io_id": io_id, "io_type": 0,
        "ct_option": f"색상:{io_id}" if io_id else it_id, "ct_status": ct_status, "ct_qty": ct_qty,
        "ct_stock_use": ct_stock_use, "ct_price": 1000, **fields,
    }


def source():
    return {
        "g5_shop_item": [
            item("SOLD0", it_stock_qty=0, it_buy_min_qty=0, it_sc_price=0, it_sc_minimum=0),
            item("PLAIN"),
            item("OPT", it_option_subject="색상"),
        ],
        "g5_shop_item_option": [option("OPT", "빨강", io_stock_qty=7), option("OPT", "파랑", io_stock_qty=3, io_use=0)],
        "g5_shop_order": [{"od_id": 1001, "od_name": "구매자", "od_status": "주문", "od_cart_price": 1000}],
        "g5_shop_cart": [
            cart(1, "PLAIN", "주문", 3, 0),
            cart(2, "PLAIN", "입금", 2, 0),
            cart(3, "PLAIN", "배송", 4, 1),
            cart(4, "PLAIN", "취소", 5, 0),
            cart(5, "OPT", "준비", 2, 0, io_id="빨강"),
            cart(6, "OPT", "완료", 1, 1, io_id="빨강"),
            # a cart row whose order row is gone is not imported, so nothing holds its stock
            cart(7, "PLAIN", "주문", 1, 0, od_id=9999),
        ],
    }


class Gnuboard5ImportValueTests(TestCase):
    def run_import(self, tables, selected=SHOP):
        command = Command()
        command.source_root = Path("missing-source")
        with (
            patch.object(migrate_gnuboard5, "fetch_rows", lambda cursor, table, limit=None: [dict(row) for row in tables[table]]),
            patch.object(migrate_gnuboard5, "table_exists", lambda cursor, table: table in tables),
        ):
            return command.import_selected(None, CONFIG, set(selected), None)

    def option_row(self, it_id, io_id):
        return next(row for row in ShopProduct.objects.get(pk=it_id).options if row["io_id"] == io_id)

    def stock_snapshot(self):
        return {
            product.it_id: (product.it_stock_qty, [(row["io_id"], row["io_stock_qty"]) for row in product.options or []])
            for product in ShopProduct.objects.order_by("it_id")
        }

    def test_a_source_zero_is_imported_as_zero(self):
        tables = {
            **source(),
            "g5_shop_coupon_zone": [{"cz_id": 1, "cz_subject": "상품쿠폰", "cp_method": 0, "cp_trunc": 0, "cz_period": 7}],
            "g5_shop_coupon": [{"cp_id": "CP-0", "cz_id": 1, "mb_id": "", "cp_subject": "상품쿠폰", "cp_method": 0, "cp_trunc": 0}],
            "g5_poll": [{"po_id": 1, "po_subject": "꺼 둔 투표", "po_use": 0, "po_level": 1}],
        }
        self.run_import(tables, SHOP | {"shop_coupon_zone", "shop_coupon", "poll"})

        sold_out = ShopProduct.objects.get(pk="SOLD0")
        self.assertEqual(
            (sold_out.it_stock_qty, sold_out.it_buy_min_qty, sold_out.it_sc_price, sold_out.it_sc_minimum), (0, 0, 0, 0)
        )
        self.assertTrue(stock_level(sold_out).is_out)
        self.assertEqual(self.option_row("OPT", "파랑")["io_use"], 0)
        zone = ShopCouponZone.objects.get(pk=1)
        coupon = ShopCoupon.objects.get(pk="CP-0")
        self.assertEqual((zone.cp_method, zone.cp_trunc, coupon.cp_method, coupon.cp_trunc), (0, 0, 0, 0))
        self.assertEqual(Poll.objects.get(pk=1).po_use, 0)

    def test_a_tinyint_flag_imports_as_the_zero_or_one_the_shop_reads(self):
        # PHP reads these columns as truthy (if ($it['it_soldout'])), so any value but 0 is on; a "10"
        # would also overflow the varchar(1) on PostgreSQL and roll the whole apply back
        flags = {"it_soldout": 10, "it_type1": -1, "it_type2": 1, "it_use": 0, "it_tel_inq": None, "it_stock_sms": ""}
        tables = {
            **source(),
            "g5_shop_item": [item("FLAGS", **flags)],
            "g5_shop_item_use": [
                {"is_id": 1, "it_id": "FLAGS", "is_subject": "좋아요", "is_content": "좋아요", "is_confirm": -1},
                {"is_id": 2, "it_id": "FLAGS", "is_subject": "숨김", "is_content": "숨김", "is_confirm": 0},
            ],
        }
        self.run_import(tables, SHOP | {"shop_review"})

        product = ShopProduct.objects.get(pk="FLAGS")
        self.assertEqual(
            {name: getattr(product, name) for name in flags},
            {"it_soldout": "1", "it_type1": "1", "it_type2": "1", "it_use": "0", "it_tel_inq": "0", "it_stock_sms": "0"},
        )
        self.assertEqual(dict(ShopReview.objects.values_list("pk", "is_confirm")), {1: "1", 2: "0"})

    def test_a_missing_or_blank_source_value_takes_the_default(self):
        self.run_import({**source(), "g5_shop_item": [{"it_id": "BARE", "it_name": "BARE", "it_stock_qty": None, "it_sc_price": ""}]})

        bare = ShopProduct.objects.get(pk="BARE")
        self.assertEqual((bare.it_stock_qty, bare.it_sc_price, bare.it_sc_minimum, bare.it_buy_min_qty), (9999, 3000, 50000, 1))

    def test_order_lines_store_the_option_id_not_its_label(self):
        self.run_import(source())

        lines = dict(ShopOrderItem.objects.values_list("ct_id", "ct_option"))
        self.assertEqual(lines["5"], "빨강")
        self.assertEqual(lines["1"], "")

    def test_lines_youngcart_holds_stock_for_are_stock_adjusted_and_deducted_once(self):
        self.run_import(source())

        adjusted = dict(ShopOrderItem.objects.values_list("ct_id", "stock_adjusted"))
        self.assertEqual(adjusted, {"1": True, "2": True, "3": True, "4": False, "5": True, "6": True})
        # youngcart: it_stock_qty 10 minus the 주문/입금 lines it has not taken out yet (3 + 2)
        self.assertEqual(ShopProduct.objects.get(pk="PLAIN").it_stock_qty, 5)
        self.assertEqual(self.option_row("OPT", "빨강")["io_stock_qty"], 5)
        self.assertEqual(ShopProduct.objects.get(pk="SOLD0").it_stock_qty, 0)

    def test_a_second_import_leaves_stock_unchanged(self):
        self.run_import(source())
        first = self.stock_snapshot()

        self.run_import(source())
        self.assertEqual(self.stock_snapshot(), first)
        self.run_import(source(), {"shop_item", "shop_item_option", "shop_cart"})
        self.assertEqual(self.stock_snapshot(), first)

    def test_order_lines_cannot_be_imported_without_their_products(self):
        # Lines youngcart holds stock for are marked stock_adjusted only because the product import
        # subtracts them; importing the lines alone onto older stock would let a cancel add stock back.
        self.run_import(source())

        with self.assertRaisesMessage(CommandError, "shop_item"):
            self.run_import(source(), {"shop_cart"})

    def test_cancelling_an_imported_order_puts_back_what_youngcart_held(self):
        self.run_import(source())

        cancel_order_with_stock_restore(ShopOrder.objects.get(pk="1001"))

        # youngcart: the shipped lines come back onto the shelf (10 + 4, 7 + 1) and the pending
        # lines stop counting against it
        self.assertEqual(ShopProduct.objects.get(pk="PLAIN").it_stock_qty, 14)
        self.assertEqual(self.option_row("OPT", "빨강")["io_stock_qty"], 8)


class Gnuboard5MemoImportTests(TestCase):
    def test_a_received_memo_points_at_its_sender_and_a_sent_one_at_its_copy(self):
        User = get_user_model()
        sender = User.objects.create_user(username="sender", password="x")
        User.objects.create_user(username="reader", password="x")
        rows = [
            {"me_id": 11, "me_type": "recv", "me_recv_mb_id": "reader", "me_send_mb_id": "sender", "me_send_id": 0,
             "me_memo": "안녕", "me_send_datetime": "2026-11-01 10:00:00", "me_send_ip": ""},
            {"me_id": 12, "me_type": "send", "me_recv_mb_id": "reader", "me_send_mb_id": "sender", "me_send_id": 11,
             "me_memo": "안녕", "me_send_datetime": "2026-11-01 10:00:00", "me_send_ip": ""},
        ]

        Command().import_memos(rows)

        self.assertEqual(User_Memo.objects.get(pk=11).me_send_id, sender.pk)
        self.assertEqual(User_Memo.objects.get(pk=12).me_send_id, 11)
