"""Shop display settings reach the home snapshot, the public settings and the product detail."""

import json

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from gnu_jango.api import page_bootstrap
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopProduct

API = "/api/v1/shop"
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "shop-display-tests"}}


def set_options(**values):
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": str(value)})


class DisplayBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        site_config.clear()
        self.addCleanup(site_config.clear)
        self.client = APIClient()
        self.category = ShopCategory.objects.create(ca_id="70", ca_name="Display category")

    def make_products(self, prefix, count, **fields):
        for index in range(count):
            ShopProduct.objects.create(
                it_id=f"{prefix}{index:02d}", it_name=f"{prefix} {index}", category=self.category,
                it_use="1", it_price=1000, it_stock_qty=5, **fields,
            )

    def data(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.content[:500])
        return response.json()["data"]


@override_settings(DEBUG=True, CACHES=LOCMEM)
class ShopHomeDisplayTests(DisplayBase):
    def test_default_sections_fetch_the_larger_of_the_pc_and_mobile_counts(self):
        self.make_products("HIT", 14, it_type1="1")
        home = self.data("/api/v1/shop/home")
        # youngcart defaults: PC 5 x 2 = 10, mobile 2 x 4 = 8.
        self.assertEqual(
            home["display"]["type1"],
            {"use": True, "pc_cols": 5, "pc_count": 10, "mobile_cols": 2, "mobile_count": 8, "count": 10},
        )
        self.assertEqual(len(home["products"]["type1"]), 10)
        self.assertEqual(home["products"]["type1"], self.data(f"{API}/products?it_type1=1&per_page=10"))
        self.assertEqual(home["catalogPreview"], [])

    def test_mobile_count_can_be_the_larger_one(self):
        self.make_products("NEW", 12, it_type3="1")
        set_options(de_type3_list_mod=3, de_type3_list_row=1, de_mobile_type3_list_mod=2, de_mobile_type3_list_row=5)
        home = self.data("/api/v1/shop/home")
        self.assertEqual(home["display"]["type3"]["pc_count"], 3)
        self.assertEqual(home["display"]["type3"]["mobile_count"], 10)
        self.assertEqual(len(home["products"]["type3"]), 10)

    def test_a_switched_off_section_is_empty_and_flagged(self):
        self.make_products("REC", 3, it_type2="1")
        set_options(de_type2_list_use="0")
        home = self.data("/api/v1/shop/home")
        self.assertEqual(home["products"]["type2"], [])
        self.assertFalse(home["display"]["type2"]["use"])
        self.assertEqual(home["display"]["type2"]["count"], 0)

    def test_catalog_preview_fills_the_hit_slot_only_while_hits_are_shown(self):
        self.make_products("PLAIN", 12)
        home = self.data("/api/v1/shop/home")
        self.assertEqual(len(home["catalogPreview"]), 10)
        with self.captureOnCommitCallbacks(execute=True):
            set_options(de_type1_list_use="0")
        self.assertEqual(self.data("/api/v1/shop/home")["catalogPreview"], [])

    def test_saving_a_display_setting_starts_a_new_snapshot(self):
        self.make_products("POP", 12, it_type4="1")
        self.assertEqual(len(self.data("/api/v1/shop/home")["products"]["type4"]), 10)
        version = cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY)
        with self.captureOnCommitCallbacks(execute=True):
            set_options(de_type4_list_mod=4, de_type4_list_row=1, de_mobile_type4_list_row=1)
        self.assertNotEqual(cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY), version)
        home = self.data("/api/v1/shop/home")
        self.assertEqual(len(home["products"]["type4"]), 4)
        self.assertEqual(home["display"]["type4"]["pc_cols"], 4)


class PublicSettingsDisplayTests(DisplayBase):
    def test_defaults_describe_search_type_lists_and_related_products(self):
        data = self.data("/api/v1/settings")
        self.assertEqual(
            data["shop_display"],
            {
                "search": {"pc_cols": 5, "rows": 4, "per_page": 20, "mobile_cols": 2},
                "listtype": {"pc_cols": 5, "rows": 4, "per_page": 20, "mobile_cols": 2},
                "related": {"use": True, "pc_cols": 4, "mobile_cols": 2},
            },
        )
        for key in ("shop_logo", "shop_logo_footer", "shop_logo_mobile", "shop_logo_mobile_footer"):
            self.assertEqual(data[key], "")

    def test_saved_values_and_uploaded_logos_are_public(self):
        set_options(
            de_search_list_mod=4, de_search_list_row=3, de_mobile_search_list_mod=1,
            de_listtype_list_mod=6, de_listtype_list_row=2, de_mobile_listtype_list_mod=3,
            de_rel_list_use="0", de_rel_list_mod=3, de_mobile_rel_list_mod=1,
            de_logo_img="shop/logo/de_logo_img-top.png", de_mobile_logo_img2="shop/logo/de_mobile_logo_img2-x.png",
        )
        data = self.data("/api/v1/settings")
        self.assertEqual(data["shop_display"]["search"], {"pc_cols": 4, "rows": 3, "per_page": 12, "mobile_cols": 1})
        self.assertEqual(data["shop_display"]["listtype"], {"pc_cols": 6, "rows": 2, "per_page": 12, "mobile_cols": 3})
        self.assertEqual(data["shop_display"]["related"], {"use": False, "pc_cols": 3, "mobile_cols": 1})
        self.assertEqual(data["shop_logo"], default_storage.url("shop/logo/de_logo_img-top.png"))
        self.assertEqual(data["shop_logo_mobile_footer"], default_storage.url("shop/logo/de_mobile_logo_img2-x.png"))
        self.assertEqual(data["shop_logo_footer"], "")

    def test_out_of_range_values_are_clamped(self):
        set_options(de_search_list_mod=99, de_search_list_row=0, de_mobile_search_list_mod="x")
        search = self.data("/api/v1/settings")["shop_display"]["search"]
        self.assertEqual(search, {"pc_cols": 8, "rows": 1, "per_page": 8, "mobile_cols": 2})


class RelatedProductsSwitchTests(DisplayBase):
    def setUp(self):
        super().setUp()
        self.make_products("REL", 3)
        set_options(nextjs_smoke_rel_REL00=json.dumps({"related_csv": "REL01,REL02"}))

    def test_related_items_are_listed_while_switched_on(self):
        data = self.data(f"{API}/products/REL00")
        self.assertEqual([row["it_id"] for row in data["related_items"]], ["REL01", "REL02"])

    def test_switching_related_products_off_returns_none(self):
        set_options(de_rel_list_use="0")
        self.assertEqual(self.data(f"{API}/products/REL00")["related_items"], [])
