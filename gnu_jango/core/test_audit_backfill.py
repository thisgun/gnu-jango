"""Tests for the one-time audit-history backfill command."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopOrder,
    ShopProduct,
    ShopShippingPolicy,
)


class BackfillAuditHistoryTests(TestCase):
    def test_backfills_missing_snapshots_and_is_idempotent(self):
        category = ShopCategory.objects.create(ca_id="BF", ca_name="Backfill")
        ShopProduct.objects.bulk_create(
            [
                ShopProduct(
                    it_id="BF-PRODUCT",
                    it_name="Backfill product",
                    category=category,
                    it_price=1000,
                )
            ]
        )
        ShopCoupon.objects.bulk_create(
            [ShopCoupon(cp_id="BF-COUPON", cp_subject="Backfill coupon", cp_price=500)]
        )
        ShopShippingPolicy.objects.bulk_create(
            [ShopShippingPolicy(de_delivery_company="Backfill courier", de_send_cost_list="3000")]
        )

        out = StringIO()
        call_command(
            "backfill_audit_history",
            models=["shop.ShopProduct", "shop.ShopCoupon", "shop.ShopShippingPolicy"],
            stdout=out,
        )

        self.assertEqual(ShopProduct.history.get(it_id="BF-PRODUCT").history_type, "+")
        self.assertEqual(ShopCoupon.history.get(cp_id="BF-COUPON").history_type, "+")
        self.assertEqual(ShopShippingPolicy.history.count(), 1)
        self.assertIn("initial snapshot", ShopProduct.history.get(it_id="BF-PRODUCT").history_change_reason)

        counts = (
            ShopProduct.history.count(),
            ShopCoupon.history.count(),
            ShopShippingPolicy.history.count(),
        )
        call_command(
            "backfill_audit_history",
            models=["shop.ShopProduct", "shop.ShopCoupon", "shop.ShopShippingPolicy"],
            stdout=StringIO(),
        )
        self.assertEqual(
            counts,
            (
                ShopProduct.history.count(),
                ShopCoupon.history.count(),
                ShopShippingPolicy.history.count(),
            ),
        )

    def test_config_backfill_only_tracks_site_settings(self):
        Config.objects.bulk_create(
            [
                Config(name="cf_backfill_setting", value="one"),
                Config(name="auth_cart_backfill", value='{"items": []}'),
            ]
        )

        call_command("backfill_audit_history", models=["config.Config"], stdout=StringIO())

        self.assertEqual(Config.history.filter(name="cf_backfill_setting").count(), 1)
        self.assertEqual(Config.history.filter(name="auth_cart_backfill").count(), 0)

    def test_order_history_import_creates_status_events(self):
        get_user_model().objects.create_user(username="backfill-admin", password="pw")
        order = ShopOrder.objects.create(
            od_id="BF-ORDER",
            od_name="Backfill order",
            od_status="준비",
            od_mod_history=(
                "2026-10-20 10:00:00 backfill-admin 주문상태 주문→입금 처리\n"
                "2026-10-20 11:00:00 backfill-admin 주문상태 입금→준비 처리\n"
            ),
        )
        order.history.all().delete()

        call_command(
            "backfill_audit_history",
            models=["shop.ShopOrder"],
            import_order_history=True,
            stdout=StringIO(),
        )

        self.assertEqual(order.history.count(), 3)
        snapshot = order.history.get(history_type="+")
        self.assertIn("initial snapshot", snapshot.history_change_reason)
        imported = list(order.history.filter(history_type="~").order_by("history_date"))
        self.assertEqual([row.od_status for row in imported], ["입금", "준비"])
        self.assertEqual(imported[0].history_user.username, "backfill-admin")
        self.assertIn("od_mod_history import", imported[0].history_change_reason)
        self.assertLess(imported[-1].history_date, timezone.now())

    def test_dry_run_does_not_write(self):
        category = ShopCategory.objects.create(ca_id="DR", ca_name="Dry run")
        ShopProduct.objects.bulk_create(
            [ShopProduct(it_id="DR-PRODUCT", it_name="Dry run product", category=category)]
        )

        out = StringIO()
        call_command(
            "backfill_audit_history",
            models=["shop.ShopProduct"],
            dry_run=True,
            stdout=out,
        )

        self.assertEqual(ShopProduct.history.count(), 0)
        self.assertIn("dry run", out.getvalue())
