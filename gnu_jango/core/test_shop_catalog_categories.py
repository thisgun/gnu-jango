"""youngcart catalog admin parity: category tools, list settings and coupon exclusion."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_coupons import coupon_matches_cart_item
from gnu_jango.api.v1_shop import annotate_product_coupon_badge
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as GnuboardImportCommand
from gnu_jango.shop.category_tree import category_delete_blockers, next_child_category_id
from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopCouponZone, ShopProduct
from gnu_jango.shop.shop_display import category_list_display

API = "/api/v1/shop"


class CategoryAdminBase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="category-admin", email="category-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)

    def category(self, ca_id, **fields):
        return ShopCategory.objects.create(ca_id=ca_id, ca_name=fields.pop("ca_name", f"분류 {ca_id}"),
                                           ca_parent=ca_id[:-2], **fields)


class ChildCategoryTests(CategoryAdminBase):
    def test_next_codes_follow_categoryform(self):
        self.assertEqual(next_child_category_id(""), "10")
        self.category("10")
        self.category("20")
        self.assertEqual(next_child_category_id(""), "30")
        self.assertEqual(next_child_category_id("10"), "1010")
        self.category("1010")
        self.category("10z0")
        self.assertEqual(next_child_category_id("10"), "1011")  # past z0 the first free code is offered
        self.assertEqual(next_child_category_id("1010101010"), "")

    def test_add_child_link_prefills_the_add_form(self):
        self.category("10", ca_list_mod=4, ca_list_row=2)
        self.category("1010")
        changelist = self.client.get(reverse("admin:shop_shopcategory_changelist")).content.decode()
        self.assertIn(f"{reverse('admin:shop_shopcategory_add')}?parent=10", changelist)
        self.assertIn("하위분류 추가", changelist)
        response = self.client.get(f"{reverse('admin:shop_shopcategory_add')}?parent=10")
        initial = response.context["adminform"].form.initial
        self.assertEqual((initial["ca_id"], initial["ca_parent"]), ("1020", "10"))
        self.assertEqual((initial["ca_list_mod"], initial["ca_list_row"], initial["ca_mobile_list_mod"]), (4, 2, 3))
        top = self.client.get(reverse("admin:shop_shopcategory_add")).context["adminform"].form.initial
        self.assertEqual((top["ca_id"], top["ca_list_mod"], top["ca_list_row"]), ("20", 3, 5))

    def add(self, **fields):
        data = {
            "ca_id": "", "ca_name": "새 분류", "ca_parent": "", "ca_order": "0", "ca_skin": "", "ca_use": "on",
            "ca_list_mod": "3", "ca_list_row": "5", "ca_mobile_list_mod": "3", "ca_mobile_list_row": "5",
        }
        data.update(fields)
        return self.client.post(reverse("admin:shop_shopcategory_add"), data)

    def test_the_add_form_checks_the_code_and_fills_the_parent(self):
        self.category("10")
        self.assertEqual(self.add(ca_id="1010").status_code, 302)
        self.assertEqual(ShopCategory.objects.get(pk="1010").ca_parent, "10")
        for bad, message in (("101", "2자씩"), ("2010", "상위 분류 20"), ("1-", "영문자와 숫자")):
            with self.subTest(bad):
                response = self.add(ca_id=bad)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.content.decode())
        response = self.add(ca_id="1020", ca_list_mod="9")
        self.assertIn("8 이하", response.content.decode())


class CategoryDeleteTests(CategoryAdminBase):
    def test_a_category_with_children_or_products_is_refused(self):
        parent = self.category("10")
        self.category("1010")
        with_product = self.category("20")
        secondary = self.category("30")
        ShopProduct.objects.create(it_id="P1", it_name="상품", category=with_product)
        ShopProduct.objects.create(it_id="P2", it_name="상품", category3=secondary)
        self.assertIn("하위 분류가 있으므로", category_delete_blockers(parent)[0])
        self.assertIn("총 1건", category_delete_blockers(secondary)[0])

        for category in (parent, with_product, secondary):
            url = reverse("admin:shop_shopcategory_delete", args=[category.pk])
            page = self.client.get(url).content.decode()
            self.assertIn("삭제할 수 없습니다", page)
            self.client.post(url, {"post": "yes"})
            self.assertTrue(ShopCategory.objects.filter(pk=category.pk).exists())

        empty = self.category("40")
        self.client.post(reverse("admin:shop_shopcategory_delete", args=[empty.pk]), {"post": "yes"})
        self.assertFalse(ShopCategory.objects.filter(pk="40").exists())

    def test_bulk_delete_refuses_blocked_categories(self):
        self.category("10")
        self.category("1010")
        self.category("50")
        response = self.client.post(
            reverse("admin:shop_shopcategory_changelist"),
            {"action": "delete_selected", "_selected_action": ["10", "50"], "post": "yes"},
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(ShopCategory.objects.filter(pk="10").exists())

    def test_the_model_admin_guards_direct_deletes(self):
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        parent = self.category("10")
        self.category("1010")
        free = self.category("60")
        request = RequestFactory().post("/")
        request.user = self.admin
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        model_admin = site._registry[ShopCategory]
        model_admin.delete_queryset(request, ShopCategory.objects.filter(pk__in=["10", "60"]))
        self.assertTrue(ShopCategory.objects.filter(pk=parent.pk).exists())
        self.assertFalse(ShopCategory.objects.filter(pk=free.pk).exists())
        model_admin.delete_model(request, parent)
        self.assertTrue(ShopCategory.objects.filter(pk=parent.pk).exists())


class CategoryListDisplayTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def make(self, ca_id, count, **fields):
        category = ShopCategory.objects.create(ca_id=ca_id, ca_name=f"분류 {ca_id}", **fields)
        for index in range(count):
            ShopProduct.objects.create(it_id=f"{ca_id}-{index:03d}", it_name="상품", category=category, it_use="1")
        return category

    def test_unset_settings_keep_the_standard_grid(self):
        category = self.make("10", 25)
        self.assertEqual(category_list_display(category), {
            "configured": False, "pc_cols": 4, "rows": 5, "per_page": 20, "mobile_cols": 2, "mobile_rows": 5,
        })
        data = self.client.get(f"{API}/categories/10").json()["data"]
        self.assertEqual(len(data["items"]), 20)
        self.assertFalse(data["category"]["list_display"]["configured"])

    def test_the_category_settings_size_the_page_and_grid(self):
        self.make("20", 10, ca_list_mod=3, ca_list_row=2, ca_mobile_list_mod=2, ca_mobile_list_row=4)
        data = self.client.get(f"{API}/categories/20").json()["data"]
        self.assertEqual(len(data["items"]), 6)
        self.assertEqual(data["meta"]["last_page"], 2)
        self.assertEqual(
            data["category"]["list_display"],
            {"configured": True, "pc_cols": 3, "rows": 2, "per_page": 6, "mobile_cols": 2, "mobile_rows": 4},
        )
        self.assertEqual((data["category"]["ca_list_mod"], data["category"]["ca_mobile_list_row"]), (3, 4))
        # an explicit per_page still wins
        self.assertEqual(len(self.client.get(f"{API}/categories/20?per_page=4").json()["data"]["items"]), 4)

    def test_large_settings_are_capped(self):
        category = ShopCategory(ca_id="30", ca_name="x", ca_list_mod=12, ca_list_row=20)
        display = category_list_display(category)
        self.assertEqual((display["pc_cols"], display["per_page"], display["mobile_cols"]), (8, 100, 2))

    def test_the_importer_maps_category_settings_and_coupon_flags(self):
        command = GnuboardImportCommand()
        source = TemporaryDirectory()
        self.addCleanup(source.cleanup)
        command.source_root = Path(source.name)
        command.import_shop_categories([{
            "ca_id": "70", "ca_name": "수입", "ca_list_mod": 4, "ca_list_row": 3,
            "ca_mobile_list_mod": 2, "ca_mobile_list_row": 6, "ca_nocoupon": 1,
        }])
        category = ShopCategory.objects.get(pk="70")
        self.assertEqual(
            (category.ca_list_mod, category.ca_list_row, category.ca_mobile_list_mod, category.ca_mobile_list_row, category.ca_nocoupon),
            (4, 3, 2, 6, True),
        )
        command.import_shop_products([{"it_id": "IMP-1", "it_name": "수입상품", "ca_id": "70", "it_nocoupon": "1"}])
        self.assertTrue(ShopProduct.objects.get(pk="IMP-1").it_nocoupon)


class CouponExclusionTests(TestCase):
    def setUp(self):
        self.free = ShopCategory.objects.create(ca_id="10", ca_name="일반")
        self.blocked = ShopCategory.objects.create(ca_id="20", ca_name="쿠폰제외", ca_nocoupon=True)
        self.product = ShopProduct.objects.create(it_id="CP-1", it_name="일반상품", category=self.free, category2=self.blocked, it_use="1")
        self.excluded = ShopProduct.objects.create(it_id="CP-2", it_name="제외상품", category=self.free, it_use="1", it_nocoupon=True)

    def coupon(self, method, target=""):
        return ShopCoupon(cp_subject="쿠폰", cp_method=method, cp_target=target, cp_price=1000,
                          cp_start=timezone.localdate(), cp_end=timezone.localdate() + timedelta(days=3))

    def test_product_and_category_coupons_skip_excluded_products_and_categories(self):
        line, excluded_line = {"it_id": "CP-1"}, {"it_id": "CP-2"}
        self.assertTrue(coupon_matches_cart_item(self.coupon(0, "CP-1"), line))
        self.assertFalse(coupon_matches_cart_item(self.coupon(0, "CP-2"), excluded_line))
        self.assertTrue(coupon_matches_cart_item(self.coupon(1, "10"), line))
        self.assertFalse(coupon_matches_cart_item(self.coupon(1, "20"), line))  # ca_nocoupon
        self.assertFalse(coupon_matches_cart_item(self.coupon(1, "10"), excluded_line))  # it_nocoupon
        # order and shipping coupons still apply (youngcart only limits product/category coupons)
        self.assertTrue(coupon_matches_cart_item(self.coupon(2), excluded_line))
        self.assertTrue(coupon_matches_cart_item(self.coupon(3), excluded_line))

    def test_coupons_cannot_be_aimed_at_excluded_targets(self):
        for coupon, target in ((self.coupon(0, "CP-2"), "상품"), (self.coupon(1, "20"), "분류")):
            with self.subTest(target), self.assertRaises(ValidationError) as caught:
                coupon.clean()
            self.assertIn(f"쿠폰적용안함으로 설정된 {target}", str(caught.exception))
        self.coupon(0, "CP-1").clean()
        self.coupon(0, "UNKNOWN").clean()
        zone = ShopCouponZone(cz_subject="존", cp_method=1, cp_target="20")
        with self.assertRaises(ValidationError):
            zone.clean()

    def test_the_coupon_badge_ignores_excluded_products_and_categories(self):
        ShopCoupon.objects.create(cp_subject="분류", cp_method=1, cp_target="20", cp_price=1000,
                                  cp_start=timezone.localdate(), cp_end=timezone.localdate())
        badges = dict(annotate_product_coupon_badge(ShopProduct.objects.all()).values_list("it_id", "has_coupon"))
        self.assertEqual(badges, {"CP-1": False, "CP-2": False})
        ShopCoupon.objects.create(cp_subject="상품", cp_method=0, cp_target="CP-2", cp_price=1000,
                                  cp_start=timezone.localdate(), cp_end=timezone.localdate())
        ShopCoupon.objects.create(cp_subject="분류2", cp_method=1, cp_target="10", cp_price=1000,
                                  cp_start=timezone.localdate(), cp_end=timezone.localdate())
        badges = dict(annotate_product_coupon_badge(ShopProduct.objects.all()).values_list("it_id", "has_coupon"))
        self.assertEqual(badges, {"CP-1": True, "CP-2": False})
        detail = APIClient().get(f"{API}/products/CP-2").json()["data"]
        self.assertEqual((detail["has_coupon"], detail["it_nocoupon"]), (False, True))

    def test_the_admin_shows_the_flags(self):
        admin = get_user_model().objects.create_superuser(username="cp-admin", email="cp@example.test", password="pw")
        self.client.force_login(admin)
        product_page = self.client.get(reverse("admin:shop_shopproduct_change", args=["CP-1"])).content.decode()
        category_page = self.client.get(reverse("admin:shop_shopcategory_change", args=["20"])).content.decode()
        self.assertIn('name="it_nocoupon"', product_page)
        self.assertIn('name="ca_nocoupon"', category_page)
        self.assertIn('name="ca_list_mod"', category_page)
