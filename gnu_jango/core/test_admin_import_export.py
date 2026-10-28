"""Admin CSV import/export resources and their permission boundaries."""

from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from tablib import Dataset

from gnu_jango.shop.import_export_resources import (
    ShopOrderRegistrationResource,
    ShopOrderResource,
    ShopProductResource,
)
from gnu_jango.shop.models import ShopOrder, ShopOrderItem, ShopProduct
from gnu_jango.users.import_export_resources import UserResource
from gnu_jango.users.models import Profile


class AdminBase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="csv-admin", email="csv-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)


class ProductResourceTests(AdminBase):
    def test_import_creates_a_product_and_export_lists_it(self):
        dataset = Dataset(headers=["it_id", "it_name", "it_price", "it_stock_qty", "it_use"])
        dataset.append(["P-IMPORT", "Imported product", "12,000", "7", "1"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product = ShopProduct.objects.get(pk="P-IMPORT")
        self.assertEqual((product.it_name, product.it_price, product.it_stock_qty), ("Imported product", 12000, 7))
        self.assertIn("P-IMPORT", ShopProductResource().export([product]).csv)

    def test_existing_product_stock_must_not_change_by_import(self):
        ShopProduct.objects.create(it_id="P-STOCK", it_name="Stocked", it_stock_qty=3)
        dataset = Dataset(headers=["it_id", "it_name", "it_stock_qty"])
        dataset.append(["P-STOCK", "Changed", "4"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertEqual(ShopProduct.objects.get(pk="P-STOCK").it_stock_qty, 3)

    def test_an_existing_product_keeps_values_not_supplied_by_the_import(self):
        product = ShopProduct.objects.create(
            it_id="P-KEEP", it_name="Original", it_price=2500, it_stock_qty=7, it_use="1"
        )
        dataset = Dataset(headers=["it_id", "it_name"])
        dataset.append(["P-KEEP", "Renamed"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product.refresh_from_db()
        self.assertEqual((product.it_name, product.it_price, product.it_stock_qty, product.it_use), ("Renamed", 2500, 7, "1"))

    def test_blank_existing_cells_are_preserved(self):
        product = ShopProduct.objects.create(
            it_id="P-BLANK",
            it_name="Original",
            it_price=2500,
            it_stock_qty=7,
            it_use="1",
            it_brand="Original brand",
            it_seo_title="Original SEO",
            it_nocoupon=True,
        )
        dataset = Dataset(headers=["it_id", "it_name", "it_brand", "it_seo_title", "it_price", "it_nocoupon"])
        dataset.append(["P-BLANK", "Renamed", "", "", "", ""])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product.refresh_from_db()
        self.assertEqual(product.it_name, "Renamed")
        self.assertEqual(product.it_brand, "Original brand")
        self.assertEqual(product.it_seo_title, "Original SEO")
        self.assertEqual(product.it_price, 2500)
        self.assertTrue(product.it_nocoupon)

    def test_an_existing_on_sale_product_cannot_be_changed_to_zero_price(self):
        product = ShopProduct.objects.create(
            it_id="P-ZERO", it_name="Original", it_price=2500, it_stock_qty=7, it_use="1"
        )
        dataset = Dataset(headers=["it_id", "it_name", "it_price"])
        dataset.append(["P-ZERO", "Original", "0"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        product.refresh_from_db()
        self.assertEqual(product.it_price, 2500)

    def test_a_legacy_zero_price_product_can_still_update_other_columns(self):
        product = ShopProduct.objects.create(
            it_id="P-LEGACY", it_name="Legacy", it_price=0, it_stock_qty=7, it_use="1"
        )
        dataset = Dataset(headers=["it_id", "it_name", "it_brand"])
        dataset.append(["P-LEGACY", "Legacy renamed", "Brand"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product.refresh_from_db()
        self.assertEqual((product.it_name, product.it_brand, product.it_price), ("Legacy renamed", "Brand", 0))

    def test_a_hidden_product_cannot_be_put_on_sale_at_zero_price(self):
        product = ShopProduct.objects.create(
            it_id="P-HIDDEN", it_name="Hidden", it_price=0, it_stock_qty=7, it_use=""
        )
        dataset = Dataset(headers=["it_id", "it_use"])
        dataset.append(["P-HIDDEN", "1"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        product.refresh_from_db()
        self.assertEqual(product.it_use, "")

    def test_an_import_bumps_the_modification_time(self):
        product = ShopProduct.objects.create(it_id="P-TIME", it_name="Original", it_price=2500)
        old = timezone.now() - timedelta(days=3)
        ShopProduct.objects.filter(pk=product.pk).update(updated_at=old)
        dataset = Dataset(headers=["it_id", "it_name"])
        dataset.append(["P-TIME", "Renamed"])

        result = ShopProductResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product.refresh_from_db()
        self.assertGreater(product.updated_at, old)

    def test_stock_changes_during_an_import_are_not_overwritten(self):
        product = ShopProduct.objects.create(
            it_id="P-RACE", it_name="Original", it_price=2500, it_stock_qty=7, it_use="1"
        )

        class StockChangingResource(ShopProductResource):
            def before_save_instance(self, instance, row, **kwargs):
                super().before_save_instance(instance, row, **kwargs)
                ShopProduct.objects.filter(pk=instance.pk).update(it_stock_qty=99)

        dataset = Dataset(headers=["it_id", "it_name"])
        dataset.append(["P-RACE", "Renamed"])
        result = StockChangingResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        product.refresh_from_db()
        self.assertEqual((product.it_name, product.it_stock_qty), ("Renamed", 99))

    def test_export_prefixes_formula_leading_text_but_keeps_numbers_numeric(self):
        product = ShopProduct.objects.create(it_id="P-FORMULA", it_name="@SUM(1+1)", it_price=1000)

        csv_text = ShopProductResource().export([product]).csv

        self.assertIn("'@SUM(1+1)", csv_text)
        self.assertIn("1000", csv_text)
        self.assertNotIn("'1000", csv_text)

    def test_a_new_on_sale_product_needs_a_price_or_phone_inquiry_flag(self):
        free = Dataset(headers=["it_id", "it_name", "it_price", "it_use"])
        free.append(["P-FREE", "Free mistake", "0", "1"])
        result = ShopProductResource().import_data(free, dry_run=False, raise_errors=False)
        self.assertTrue(result.has_errors())
        self.assertFalse(ShopProduct.objects.filter(pk="P-FREE").exists())

        inquiry = Dataset(headers=["it_id", "it_name", "it_price", "it_use", "it_tel_inq"])
        inquiry.append(["P-INQUIRY", "Phone inquiry", "0", "1", "1"])
        result = ShopProductResource().import_data(inquiry, dry_run=False, raise_errors=False)
        self.assertFalse(result.has_errors())
        self.assertTrue(ShopProduct.objects.filter(pk="P-INQUIRY").exists())


class MemberResourceTests(AdminBase):
    def test_import_creates_a_member_without_a_usable_password_and_updates_profile_fields(self):
        dataset = Dataset(headers=["username", "email", "first_name", "nickname", "real_name", "phone"])
        dataset.append(["imported-member", "imported@example.test", "Imported", "imported-nick", "Import Name", "010-1"])

        result = UserResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        member = get_user_model().objects.get(username="imported-member")
        profile = Profile.objects.get(user=member)
        self.assertFalse(member.has_usable_password())
        self.assertFalse(member.is_staff)
        self.assertFalse(member.is_superuser)
        self.assertEqual((profile.nickname, profile.realname, profile.user_hp), ("imported-nick", "Import Name", "010-1"))

    def test_admin_accounts_are_not_edited_by_member_import(self):
        staff = get_user_model().objects.create_user("csv-staff", "staff@example.test", "pw", is_staff=True)
        dataset = Dataset(headers=["username", "first_name"])
        dataset.append(["csv-staff", "Changed"])

        result = UserResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        staff.refresh_from_db()
        self.assertEqual(staff.first_name, "")

    def test_an_email_change_revokes_existing_member_sessions(self):
        member = get_user_model().objects.create_user("csv-email", "old@example.test", "pw")
        profile = Profile.objects.get(user=member)
        before = profile.token_version
        dataset = Dataset(headers=["username", "email"])
        dataset.append(["csv-email", "new@example.test"])

        result = UserResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        profile.refresh_from_db()
        self.assertGreater(profile.token_version, before)

    def test_malformed_and_duplicate_emails_are_rejected(self):
        get_user_model().objects.create_user("csv-existing", "taken@example.test", "pw")

        malformed = Dataset(headers=["username", "email"])
        malformed.append(["csv-bad-email", "not-an-email"])
        result = UserResource().import_data(malformed, dry_run=False, raise_errors=False)
        self.assertTrue(result.has_errors())

        existing_duplicate = Dataset(headers=["username", "email"])
        existing_duplicate.append(["csv-new", "taken@example.test"])
        result = UserResource().import_data(existing_duplicate, dry_run=False, raise_errors=False)
        self.assertTrue(result.has_errors())

        file_duplicate = Dataset(headers=["username", "email"])
        file_duplicate.append(["csv-dupe-1", "dupe@example.test"])
        file_duplicate.append(["csv-dupe-2", "dupe@example.test"])
        result = UserResource().import_data(file_duplicate, dry_run=False, raise_errors=False)
        self.assertTrue(result.has_errors())
        self.assertFalse(get_user_model().objects.filter(username="csv-dupe-2").exists())


class OrderResourceTests(AdminBase):
    def test_import_updates_only_descriptive_fields_of_an_existing_order(self):
        order = ShopOrder.objects.create(od_id="CSV-ORDER", od_name="Old", od_status="주문", od_shop_memo="old")
        dataset = Dataset(headers=["od_id", "od_name", "od_shop_memo", "od_status", "od_receipt_price"])
        dataset.append(["CSV-ORDER", "New", "support note", "취소", "999999"])

        result = ShopOrderResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        order.refresh_from_db()
        self.assertEqual((order.od_name, order.od_shop_memo, order.od_status), ("New", "support note", "주문"))
        self.assertEqual(order.od_receipt_price, 0)

    def test_unknown_orders_are_rejected_instead_of_created(self):
        dataset = Dataset(headers=["od_id", "od_name"])
        dataset.append(["MISSING-ORDER", "Unknown"])

        result = ShopOrderResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertFalse(ShopOrder.objects.filter(pk="MISSING-ORDER").exists())

    def test_order_export_omits_secret_payment_columns(self):
        order = ShopOrder.objects.create(od_id="CSV-EXPORT", od_name="Export buyer")
        csv_text = ShopOrderResource().export([order]).csv

        self.assertIn("CSV-EXPORT", csv_text)
        self.assertIn("od_status", csv_text)
        self.assertNotIn("od_vbank_secret_hash", csv_text)

    def test_order_export_escapes_formula_text(self):
        order = ShopOrder.objects.create(od_id="CSV-FORMULA", od_name="Buyer", od_memo="@SUM(1+1)")

        csv_text = ShopOrderResource().export([order]).csv

        self.assertIn("'@SUM(1+1)", csv_text)

    def test_csv_export_keeps_negative_amounts_numeric_and_escapes_dash_text(self):
        order = ShopOrder.objects.create(od_id="CSV-NEGATIVE", od_name="Buyer", od_misu=-500, od_memo="-cmd")

        csv_text = ShopOrderResource().export([order]).csv

        self.assertIn(",-500,", csv_text)
        self.assertNotIn("'-500", csv_text)
        self.assertIn("'-cmd", csv_text)

    def test_blank_order_cells_are_preserved(self):
        order = ShopOrder.objects.create(
            od_id="CSV-BLANK", od_name="Original", od_memo="keep memo", od_shop_memo="keep shop memo"
        )
        dataset = Dataset(headers=["od_id", "od_name", "od_memo", "od_shop_memo"])
        dataset.append(["CSV-BLANK", "Renamed", "", ""])

        result = ShopOrderResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        order.refresh_from_db()
        self.assertEqual(order.od_name, "Renamed")
        self.assertEqual(order.od_memo, "keep memo")
        self.assertEqual(order.od_shop_memo, "keep shop memo")


class OrderRegistrationResourceTests(AdminBase):
    def test_registration_creates_an_unpaid_bank_order_and_reserves_stock(self):
        product = ShopProduct.objects.create(it_id="REG-P1", it_name="Registration item", it_use="1", it_price=1000, it_stock_qty=10)
        dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty", "od_b_zip", "od_deposit_name"])
        dataset.append(["CSV-NEW-1", "Buyer", "REG-P1", "2", "06236", "Buyer"])

        result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertFalse(result.has_errors())
        order = ShopOrder.objects.get(pk="CSV-NEW-1")
        item = ShopOrderItem.objects.get(order=order)
        product.refresh_from_db()
        self.assertEqual(order.od_status, "주문")
        self.assertEqual(order.od_settle_case, "bank")
        self.assertEqual(order.od_cart_price, 2000)
        self.assertGreaterEqual(order.od_misu, 2000)
        self.assertEqual((item.it_id, item.ct_qty, item.stock_adjusted), ("REG-P1", 2, True))
        self.assertEqual(product.it_stock_qty, 8)

    def test_registration_rejects_unknown_products_and_duplicate_order_ids(self):
        ShopOrder.objects.create(od_id="CSV-DUP", od_name="Existing")
        dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty"])
        dataset.append(["CSV-DUP", "Duplicate", "MISSING", "1"])

        result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertEqual(ShopOrder.objects.filter(pk="CSV-DUP").count(), 1)

    def test_registration_rejects_options(self):
        ShopProduct.objects.create(it_id="REG-OPT", it_name="Option item", it_use="1", it_price=1000, it_stock_qty=3)
        dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty", "ct_option"])
        dataset.append(["CSV-OPT", "Buyer", "REG-OPT", "1", "red"])

        result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertFalse(ShopOrder.objects.filter(pk="CSV-OPT").exists())

    def test_registration_rolls_back_the_order_when_stock_is_insufficient(self):
        product = ShopProduct.objects.create(it_id="REG-LOW", it_name="Low stock", it_use="1", it_price=1000, it_stock_qty=1)
        dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty"])
        dataset.append(["CSV-LOW", "Buyer", "REG-LOW", "2"])

        result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertFalse(ShopOrder.objects.filter(pk="CSV-LOW").exists())
        product.refresh_from_db()
        self.assertEqual(product.it_stock_qty, 1)

    def test_registration_rejects_quantity_outside_product_bounds(self):
        ShopProduct.objects.create(
            it_id="REG-BOUNDS",
            it_name="Bounded",
            it_use="1",
            it_price=1000,
            it_stock_qty=10,
            it_buy_min_qty=2,
            it_buy_max_qty=4,
        )
        for name, quantity in (("CSV-LOW-QTY", "1"), ("CSV-HIGH-QTY", "5")):
            dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty"])
            dataset.append([name, "Buyer", "REG-BOUNDS", quantity])
            result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)
            self.assertTrue(result.has_errors(), name)
            self.assertFalse(ShopOrder.objects.filter(pk=name).exists(), name)

    def test_registration_rejects_zero_price_products(self):
        product = ShopProduct.objects.create(
            it_id="REG-FREE", it_name="Free", it_use="1", it_price=0, it_tel_inq="1", it_stock_qty=3
        )
        dataset = Dataset(headers=["od_id", "od_name", "it_id", "ct_qty"])
        dataset.append(["CSV-FREE", "Buyer", "REG-FREE", "1"])

        result = ShopOrderRegistrationResource().import_data(dataset, dry_run=False, raise_errors=False)

        self.assertTrue(result.has_errors())
        self.assertFalse(ShopOrder.objects.filter(pk="CSV-FREE").exists())
        product.refresh_from_db()
        self.assertEqual(product.it_stock_qty, 3)


class ImportExportAdminTests(AdminBase):
    def test_superuser_can_open_the_import_and_export_screens(self):
        for name in (
            "admin:shop_shopproduct_import",
            "admin:shop_shopproduct_export",
            "admin:auth_user_import",
            "admin:auth_user_export",
            "admin:shop_shoporder_import",
            "admin:shop_shoporder_export",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_staff_without_import_permission_is_denied(self):
        staff = get_user_model().objects.create_user("csv-viewer", "viewer@example.test", "pw", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse("admin:shop_shopproduct_import"))

        self.assertEqual(response.status_code, 403)

    def test_staff_without_export_permission_is_denied(self):
        staff = get_user_model().objects.create_user("csv-export-viewer", "export-viewer@example.test", "pw", is_staff=True)
        self.client.force_login(staff)

        for name in ("admin:shop_shopproduct_export", "admin:shop_shoporder_export"):
            for method in (self.client.get, self.client.post):
                with self.subTest(name=name, method=method.__name__):
                    response = method(reverse(name), {"format": "0", "resource": "0"})
                    self.assertEqual(response.status_code, 403)

    def test_product_export_requires_only_product_view_permission(self):
        staff = get_user_model().objects.create_user("csv-product-viewer", "product-viewer@example.test", "pw", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="shop", codename="view_shopproduct"))
        ShopProduct.objects.create(it_id="CSV-PRODUCT-EXPORT", it_name="Exported product")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("admin:shop_shopproduct_export"),
            {
                "format": "0",
                "resource": "0",
                "shopproductresource_it_id": "on",
                "shopproductresource_it_name": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CSV-PRODUCT-EXPORT", response.content)
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=staff.pk,
                object_repr__contains="Export products",
                change_message__contains="rows=1",
            ).exists()
        )

    def test_order_export_requires_view_and_a_separate_export_permission(self):
        staff = get_user_model().objects.create_user("csv-order-viewer", "order-viewer@example.test", "pw", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="shop", codename="view_shoporder"))
        self.client.force_login(staff)
        ShopOrder.objects.create(od_id="CSV-ORDER-EXPORT", od_name="Buyer")

        response = self.client.post(
            reverse("admin:shop_shoporder_export"), {"format": "0", "resource": "0"}
        )
        self.assertEqual(response.status_code, 403)

        staff.user_permissions.add(
            Permission.objects.get(content_type__app_label="shop", codename="export_shoporder")
        )
        response = self.client.post(
            reverse("admin:shop_shoporder_export"),
            {"format": "0", "resource": "0", "shoporderresource_od_id": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CSV-ORDER-EXPORT", response.content)
        self.assertTrue(
            LogEntry.objects.filter(
                user_id=staff.pk,
                object_repr__contains="Export orders",
                change_message__contains="rows=1",
            ).exists()
        )
