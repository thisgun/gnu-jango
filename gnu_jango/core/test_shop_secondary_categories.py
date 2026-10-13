"""Secondary product categories (PHP ca_id2 / ca_id3) are preserved and honoured.

Gnuboard5 treats ca_id, ca_id2 and ca_id3 as equal category memberships for
category listings, item counts and category coupons (cp_method=1).
"""
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.v1_shop import (
    annotate_product_coupon_badge,
    coupon_matches_cart_item,
    product_coupon_badge_available,
)
from gnu_jango.config.models import Config
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as GnuboardImportCommand
from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopProduct


class SecondaryCategoryFixtureMixin:
    def build_catalog(self):
        self.primary = ShopCategory.objects.create(ca_id="10", ca_name="Primary")
        self.second = ShopCategory.objects.create(ca_id="20", ca_name="Second")
        self.third = ShopCategory.objects.create(ca_id="30", ca_name="Third")
        self.unrelated = ShopCategory.objects.create(ca_id="40", ca_name="Unrelated")
        self.product = ShopProduct.objects.create(
            it_id="SEC001",
            category=self.primary,
            category2=self.second,
            category3=self.third,
            it_name="Multi category product",
            it_price=1000,
        )
        self.primary_only = ShopProduct.objects.create(
            it_id="SEC002",
            category=self.primary,
            it_name="Primary only product",
            it_price=2000,
        )

    def make_coupon(self, target, *, method=1, start_offset=-1, end_offset=30):
        today = timezone.localdate()
        return ShopCoupon.objects.create(
            cp_subject=f"coupon-{method}-{target}",
            cp_method=method,
            cp_target=target,
            cp_start=today + timedelta(days=start_offset),
            cp_end=today + timedelta(days=end_offset),
        )


class SecondaryCategoryModelTests(SecondaryCategoryFixtureMixin, TestCase):
    def test_product_stores_secondary_and_tertiary_categories(self):
        self.build_catalog()
        stored = ShopProduct.objects.get(pk="SEC001")
        self.assertEqual(stored.category_id, "10")
        self.assertEqual(stored.category2_id, "20")
        self.assertEqual(stored.category3_id, "30")

    def test_deleting_a_category_does_not_delete_the_product(self):
        self.build_catalog()
        self.second.delete()
        stored = ShopProduct.objects.get(pk="SEC001")
        self.assertIsNone(stored.category2_id)
        self.assertEqual(stored.category_id, "10")

    def test_category_ids_lists_every_assigned_category_once(self):
        self.build_catalog()
        self.assertEqual(self.product.category_ids, ("10", "20", "30"))
        self.assertEqual(self.primary_only.category_ids, ("10",))


class SecondaryCategoryCouponTests(SecondaryCategoryFixtureMixin, TestCase):
    def setUp(self):
        self.build_catalog()

    def badge_ids(self):
        queryset = annotate_product_coupon_badge(ShopProduct.objects.all())
        return {product.it_id for product in queryset if product.has_coupon}

    def test_category_coupon_on_secondary_category_marks_product(self):
        self.make_coupon("20")
        self.assertEqual(self.badge_ids(), {"SEC001"})
        self.assertTrue(product_coupon_badge_available(self.product))
        self.assertFalse(product_coupon_badge_available(self.primary_only))

    def test_category_coupon_on_tertiary_category_marks_product(self):
        self.make_coupon("30")
        self.assertEqual(self.badge_ids(), {"SEC001"})

    def test_category_coupon_on_primary_category_still_marks_every_member(self):
        self.make_coupon("10")
        self.assertEqual(self.badge_ids(), {"SEC001", "SEC002"})

    def test_unrelated_or_expired_category_coupon_does_not_mark_product(self):
        self.make_coupon("40")
        self.make_coupon("20", end_offset=-1)
        self.assertEqual(self.badge_ids(), set())

    def test_coupon_target_matching_a_product_id_is_not_treated_as_category(self):
        self.make_coupon("20", method=0)
        self.assertEqual(self.badge_ids(), set())

    def test_cart_item_matches_category_coupon_on_any_assigned_category(self):
        item = {"it_id": "SEC001"}
        self.assertTrue(coupon_matches_cart_item(self.make_coupon("20"), item))
        self.assertTrue(coupon_matches_cart_item(self.make_coupon("30"), item))
        self.assertTrue(coupon_matches_cart_item(self.make_coupon("10"), item))
        self.assertFalse(coupon_matches_cart_item(self.make_coupon("40"), item))
        self.assertFalse(coupon_matches_cart_item(self.make_coupon("20"), {"it_id": "SEC002"}))


class SecondaryCategoryApiTests(SecondaryCategoryFixtureMixin, TestCase):
    def setUp(self):
        self.build_catalog()

    def item_ids(self, response):
        self.assertEqual(response.status_code, 200, response.content[:300])
        return [item["it_id"] for item in response.json()["data"]["items"]]

    def test_product_payload_exposes_secondary_category_ids(self):
        response = self.client.get("/api/v1/shop/products/SEC001")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["ca_id"], "10")
        self.assertEqual(data["ca_id2"], "20")
        self.assertEqual(data["ca_id3"], "30")

        plain = self.client.get("/api/v1/shop/products/SEC002").json()["data"]
        self.assertEqual(plain["ca_id2"], "")
        self.assertEqual(plain["ca_id3"], "")

    def test_malformed_legacy_options_and_relation_settings_do_not_break_product_detail(self):
        ShopProduct.objects.filter(pk="SEC001").update(options=["not-an-object", {"io_type": "bad"}])
        Config.objects.update_or_create(
            name="nextjs_smoke_rel_SEC001",
            defaults={"value": json.dumps(["not-an-object"])},
        )

        response = self.client.get("/api/v1/shop/products/SEC001")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["options"], [])

    def test_category_listing_includes_products_assigned_as_secondary_or_tertiary(self):
        self.assertEqual(self.item_ids(self.client.get("/api/v1/shop/categories/20")), ["SEC001"])
        self.assertEqual(self.item_ids(self.client.get("/api/v1/shop/categories/30")), ["SEC001"])
        self.assertCountEqual(
            self.item_ids(self.client.get("/api/v1/shop/categories/10")), ["SEC001", "SEC002"]
        )

    def test_category_listing_does_not_repeat_a_product_assigned_twice_to_the_same_category(self):
        ShopProduct.objects.filter(pk="SEC001").update(category2=self.primary)
        ids = self.item_ids(self.client.get("/api/v1/shop/categories/10"))
        self.assertEqual(sorted(ids), ["SEC001", "SEC002"])

    def test_category_listing_and_counts_include_nested_category_products(self):
        child = ShopCategory.objects.create(ca_id="1010", ca_name="Child", ca_parent="10")
        grandchild = ShopCategory.objects.create(ca_id="101010", ca_name="Grandchild", ca_parent="1010")
        ShopProduct.objects.create(
            it_id="SEC003",
            category=grandchild,
            category2=self.unrelated,
            it_name="Nested primary product",
            it_price=3000,
        )
        ShopProduct.objects.create(
            it_id="SEC004",
            category=self.unrelated,
            category2=grandchild,
            it_name="Nested secondary product",
            it_price=4000,
        )

        root_response = self.client.get("/api/v1/shop/categories/10")
        self.assertCountEqual(
            self.item_ids(root_response),
            ["SEC001", "SEC002", "SEC003", "SEC004"],
        )
        self.assertEqual(root_response.json()["data"]["category"]["item_count"], 4)
        child_response = self.client.get("/api/v1/shop/categories/1010")
        self.assertCountEqual(self.item_ids(child_response), ["SEC003", "SEC004"])

        root = next(
            row for row in self.client.get("/api/v1/shop/categories").json()["data"] if row["ca_id"] == "10"
        )
        self.assertEqual(root["item_count"], 4)
        self.assertEqual(root["children"][0]["ca_id"], child.ca_id)
        self.assertEqual(root["children"][0]["item_count"], 2)
        products_response = self.client.get("/api/v1/shop/products", {"ca_id": "10"})
        self.assertEqual(products_response.status_code, 200)
        self.assertCountEqual(
            [row["it_id"] for row in products_response.json()["data"]],
            ["SEC001", "SEC002", "SEC003", "SEC004"],
        )

    def test_nested_category_assignment_is_counted_once_across_membership_slots(self):
        child = ShopCategory.objects.create(ca_id="1010", ca_name="Child", ca_parent="10")
        grandchild = ShopCategory.objects.create(ca_id="101010", ca_name="Grandchild", ca_parent=child.ca_id)
        ShopProduct.objects.create(
            it_id="SEC005",
            category=grandchild,
            category2=child,
            category3=self.primary,
            it_name="Repeated nested assignments",
            it_price=5000,
        )

        root = next(
            row for row in self.client.get("/api/v1/shop/categories").json()["data"] if row["ca_id"] == "10"
        )
        self.assertEqual(root["item_count"], 3)
        self.assertEqual(root["children"][0]["item_count"], 1)
        self.assertEqual(self.item_ids(self.client.get("/api/v1/shop/categories/10")).count("SEC005"), 1)

    def test_products_endpoint_ca_id_filter_includes_secondary_categories(self):
        response = self.client.get("/api/v1/shop/products", {"ca_id": "20"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["it_id"] for item in response.json()["data"]], ["SEC001"])

    def test_category_item_counts_include_secondary_assignments(self):
        response = self.client.get("/api/v1/shop/categories")
        self.assertEqual(response.status_code, 200)
        counts = {item["ca_id"]: item["item_count"] for item in response.json()["data"]}
        self.assertEqual(counts["10"], 2)
        self.assertEqual(counts["20"], 1)
        self.assertEqual(counts["30"], 1)
        self.assertEqual(counts["40"], 0)

    def test_category_item_count_does_not_double_count_repeated_assignment(self):
        ShopProduct.objects.filter(pk="SEC001").update(category2=self.primary)
        counts = {
            item["ca_id"]: item["item_count"]
            for item in self.client.get("/api/v1/shop/categories").json()["data"]
        }
        self.assertEqual(counts["10"], 2)


class SecondaryCategoryAdminTests(SecondaryCategoryFixtureMixin, TestCase):
    """The category admin counts a product once in each of its ca_id, ca_id2 and ca_id3 categories."""

    def setUp(self):
        self.build_catalog()
        self.admin = get_user_model().objects.create_superuser(
            username="sec-admin", email="sec-admin@example.test", password="password123"
        )

    def test_admin_category_list_counts_secondary_assignments(self):
        from django.contrib import admin
        from django.test import RequestFactory

        request = RequestFactory().get("/admin/shop/shopcategory/")
        request.user = self.admin
        queryset = admin.site._registry[ShopCategory].get_queryset(request)
        counts = dict(queryset.values_list("ca_id", "item_total"))
        self.assertEqual(counts["10"], 2)
        self.assertEqual(counts["20"], 1)
        self.assertEqual(counts["30"], 1)
        self.assertEqual(counts["40"], 0)


class SecondaryCategoryImportTests(TestCase):
    def setUp(self):
        for ca_id in ("10", "20", "30"):
            ShopCategory.objects.create(ca_id=ca_id, ca_name=f"Category {ca_id}")
        self.source = tempfile.TemporaryDirectory()
        self.addCleanup(self.source.cleanup)
        self.command = GnuboardImportCommand()
        self.command.source_root = Path(self.source.name)

    def import_row(self, **overrides):
        row = {"it_id": "IMP001", "it_name": "Imported", "it_price": 1000, "ca_id": "10"}
        row.update(overrides)
        self.assertEqual(self.command.import_shop_products([row]), 1)
        return ShopProduct.objects.get(pk="IMP001")

    def test_import_preserves_all_three_categories(self):
        product = self.import_row(ca_id="10", ca_id2="20", ca_id3="30")
        self.assertEqual((product.category_id, product.category2_id, product.category3_id), ("10", "20", "30"))

    def test_import_leaves_empty_or_unknown_secondary_categories_unset(self):
        product = self.import_row(ca_id="10", ca_id2="", ca_id3="999")
        self.assertEqual(product.category_id, "10")
        self.assertIsNone(product.category2_id)
        self.assertIsNone(product.category3_id)

    def test_reimport_clears_secondary_category_removed_in_source(self):
        self.import_row(ca_id="10", ca_id2="20")
        product = self.import_row(ca_id="10", ca_id2="")
        self.assertIsNone(product.category2_id)

    def test_category_backfill_updates_only_secondary_category_columns(self):
        ShopProduct.objects.create(
            it_id="BF001",
            category=ShopCategory.objects.get(pk="10"),
            it_name="Local name",
            it_price=4321,
            it_hit=77,
            it_stock_qty=5,
        )
        rows = [
            {
                "it_id": "BF001",
                "it_name": "PHP name",
                "it_price": 1,
                "it_hit": 1,
                "ca_id": "30",
                "ca_id2": "20",
                "ca_id3": "30",
            },
            {"it_id": "MISSING", "ca_id2": "20"},
        ]

        self.assertEqual(self.command.import_shop_product_categories(rows), 1)

        stored = ShopProduct.objects.get(pk="BF001")
        self.assertEqual(stored.category2_id, "20")
        self.assertEqual(stored.category3_id, "30")
        self.assertEqual(stored.category_id, "10")
        self.assertEqual((stored.it_name, stored.it_price, stored.it_hit, stored.it_stock_qty), ("Local name", 4321, 77, 5))

    def test_category_backfill_clears_categories_removed_in_source(self):
        ShopProduct.objects.create(
            it_id="BF002", category2=ShopCategory.objects.get(pk="20"), it_name="Local"
        )
        self.command.import_shop_product_categories([{"it_id": "BF002", "ca_id2": "", "ca_id3": ""}])
        self.assertIsNone(ShopProduct.objects.get(pk="BF002").category2_id)

    def test_import_keeps_falling_back_to_a_known_secondary_when_primary_is_unknown(self):
        product = self.import_row(ca_id="999", ca_id2="20")
        self.assertEqual(product.category_id, "20")
        self.assertEqual(product.category2_id, "20")
