"""Field-level audit history for orders, points, coupon usage and settings.

The history tables are written by django-simple-history's save signals. These tests prove the
four models the shop needs for dispute handling are tracked, that credentials never reach the
settings history, and that the admin history screen is wired to the Unfold admin.
"""

from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from simple_history.middleware import HistoryRequestMiddleware

from gnu_jango.config.models import Config, REDACTED_CONFIG_VALUE
from gnu_jango.shop.admin.orders import ShopOrderAdmin
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopShippingPolicy,
)
from gnu_jango.shop.order_points import save_order_item_status
from gnu_jango.users.models import User_Point


class AuditHistoryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user(
            username="audit-member",
            password="audit-pass",
            email="audit@example.com",
        )

    def test_shop_order_change_creates_history_rows(self):
        order = ShopOrder.objects.create(od_id="AUDIT-ORDER-1", od_name="Audit Customer", od_addr1="Old address")
        self.assertEqual(order.history.count(), 1)
        self.assertEqual(order.history.first().history_type, "+")

        order.od_addr1 = "New address"
        order.save()

        self.assertEqual(order.history.count(), 2)
        latest = order.history.first()
        self.assertEqual(latest.history_type, "~")
        self.assertEqual(latest.od_addr1, "New address")
        self.assertEqual(latest.prev_record.od_addr1, "Old address")

    def test_shop_order_history_omits_sensitive_network_and_vbank_fields(self):
        order = ShopOrder.objects.create(
            od_id="AUDIT-ORDER-2",
            od_ip="203.0.113.10",
            od_vbank_secret_hash="secret-hash",
        )
        record = order.history.first()

        self.assertFalse(hasattr(record, "od_ip"))
        self.assertFalse(hasattr(record, "od_vbank_secret_hash"))

    def test_user_point_change_creates_history_rows(self):
        point = User_Point.objects.create(
            user=self.member,
            po_datetime=timezone.now(),
            po_content="Audit grant",
            po_point=100,
            po_mb_point=100,
        )
        self.assertEqual(point.history.count(), 1)

        point.po_content = "Audit grant (corrected)"
        point.save()
        self.assertEqual(point.history.count(), 2)
        self.assertEqual(point.history.first().po_content, "Audit grant (corrected)")

    def test_coupon_log_change_creates_history_rows(self):
        coupon_log = ShopCouponLog.objects.create(
            cl_id=990001,
            cp_id="AUDIT-COUPON",
            mb_id=self.member.username,
            user=self.member,
            cp_price=1000,
        )
        self.assertEqual(coupon_log.history.count(), 1)

        coupon_log.cp_price = 1500
        coupon_log.save()
        self.assertEqual(coupon_log.history.count(), 2)
        self.assertEqual(coupon_log.history.first().cp_price, 1500)

    def test_config_change_creates_history_rows(self):
        setting = Config.objects.create(name="cf_title", value="first")
        self.assertEqual(setting.history.count(), 1)

        setting.value = "second"
        setting.save()
        self.assertEqual(setting.history.count(), 2)
        self.assertEqual(setting.history.first().value, "second")

    def test_secret_config_value_is_redacted_in_history(self):
        setting = Config.objects.create(name="cf_toss_secret_key", value="live-secret-value")

        self.assertEqual(setting.value, "live-secret-value")
        self.assertEqual(setting.history.first().value, REDACTED_CONFIG_VALUE)
        self.assertNotEqual(setting.history.first().value, setting.value)

    def test_non_setting_config_rows_are_not_audited(self):
        cart = Config.objects.create(name="auth_cart_audit-member", value='{"items": []}')

        self.assertEqual(cart.history.count(), 0)

    def test_product_price_change_creates_history(self):
        product = ShopProduct.objects.create(
            it_id="AUDIT-PRODUCT",
            it_name="Audit product",
            it_price=1000,
        )
        self.assertEqual(product.history.count(), 1)

        product.it_price = 2000
        product.save()

        self.assertEqual(product.history.count(), 2)
        self.assertEqual(product.history.first().it_price, 2000)
        self.assertEqual(product.history.first().prev_record.it_price, 1000)
        self.assertFalse(hasattr(product.history.first(), "it_content"))
        self.assertFalse(hasattr(product.history.first(), "images"))

    def test_order_line_change_creates_history(self):
        order = ShopOrder.objects.create(od_id="AUDIT-LINE-ORDER", od_name="Audit line")
        line = ShopOrderItem.objects.create(
            order=order,
            ct_id="1",
            it_id="AUDIT-PRODUCT",
            it_name="Audit product",
            ct_price=1000,
            ct_qty=1,
            ct_status="주문",
        )
        self.assertEqual(line.history.count(), 1)

        line.ct_qty = 2
        line.ct_status = "취소"
        line.save()

        self.assertEqual(line.history.count(), 2)
        self.assertEqual(line.history.first().ct_qty, 2)
        self.assertEqual(line.history.first().ct_status, "취소")

    def test_bulk_line_status_helper_writes_history(self):
        order = ShopOrder.objects.create(od_id="AUDIT-LINE-HELPER", od_name="Audit helper")
        line = ShopOrderItem.objects.create(
            order=order,
            ct_id="1",
            it_id="AUDIT-PRODUCT",
            it_name="Audit product",
            ct_price=1000,
            ct_qty=1,
            ct_status="주문",
        )
        with transaction.atomic():
            save_order_item_status(
                ShopOrderItem.objects.filter(pk=line.pk),
                "입금",
                reason="test line transition",
            )

        self.assertEqual(line.history.count(), 2)
        self.assertEqual(line.history.first().ct_status, "입금")
        self.assertEqual(line.history.first().history_change_reason, "test line transition")

    def test_coupon_definition_change_creates_history(self):
        coupon = ShopCoupon.objects.create(cp_subject="Audit coupon", cp_price=1000)
        self.assertEqual(coupon.history.count(), 1)

        coupon.cp_price = 2000
        coupon.save()

        self.assertEqual(coupon.history.count(), 2)
        self.assertEqual(coupon.history.first().cp_price, 2000)
        self.assertFalse(hasattr(coupon.history.first(), "cp_used"))

    def test_shipping_policy_change_creates_history(self):
        policy = ShopShippingPolicy.objects.create(
            de_delivery_company="Audit courier",
            de_send_cost_list="3000",
        )
        self.assertEqual(policy.history.count(), 1)

        policy.de_send_cost_list = "4000"
        policy.save()

        self.assertEqual(policy.history.count(), 2)
        self.assertEqual(policy.history.first().de_send_cost_list, "4000")


class AuditHistoryAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = get_user_model().objects.create_superuser(
            username="audit-admin",
            email="audit-admin@example.com",
            password="audit-admin-pass",
        )
        cls.member = get_user_model().objects.create_user(
            username="audit-member-2",
            password="audit-pass",
            email="audit2@example.com",
        )
        cls.order = ShopOrder.objects.create(od_id="AUDIT-ADMIN-ORDER", od_name="Audit Customer")
        cls.point = User_Point.objects.create(
            user=cls.member,
            po_datetime=timezone.now(),
            po_content="Audit admin point",
            po_point=10,
            po_mb_point=10,
        )
        cls.coupon_log = ShopCouponLog.objects.create(cl_id=990002, cp_id="AUDIT-ADMIN-COUPON", cp_price=500)
        cls.config = Config.objects.create(name="cf_title", value="one")
        cls.category = ShopCategory.objects.create(ca_id="AUD", ca_name="Audit category")
        cls.product = ShopProduct.objects.create(
            it_id="AUDIT-ADMIN-PRODUCT",
            it_name="Audit product",
            category=cls.category,
            it_price=1000,
        )
        cls.order_item = ShopOrderItem.objects.create(
            order=cls.order,
            ct_id="1",
            it_id=cls.product.it_id,
            it_name=cls.product.it_name,
            ct_price=1000,
            ct_qty=1,
            ct_status="주문",
        )
        cls.coupon = ShopCoupon.objects.create(cp_subject="Audit coupon", cp_price=1000)
        cls.shipping_policy = ShopShippingPolicy.objects.create(
            de_delivery_company="Audit courier",
            de_send_cost_list="3000",
        )
        cls.order.history.update(history_user=cls.admin_user)
        cls.point.history.update(history_user=cls.admin_user)
        cls.coupon_log.history.update(history_user=cls.admin_user)
        cls.config.history.update(history_user=cls.admin_user)
        cls.product.history.update(history_user=cls.admin_user)
        cls.order_item.history.update(history_user=cls.admin_user)
        cls.coupon.history.update(history_user=cls.admin_user)
        cls.shipping_policy.history.update(history_user=cls.admin_user)

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_history_pages_render_for_each_audited_model(self):
        for url in (
            reverse("admin:shop_shoporder_history", args=[self.order.pk]),
            reverse("admin:shop_shoporderitem_history", args=[self.order_item.pk]),
            reverse("admin:shop_shopproduct_history", args=[self.product.pk]),
            reverse("admin:shop_shopcoupon_history", args=[self.coupon.pk]),
            reverse("admin:shop_shopcouponlog_history", args=[self.coupon_log.pk]),
            reverse("admin:shop_shopshippingpolicy_history", args=[self.shipping_policy.pk]),
            reverse("admin:users_user_point_history", args=[self.point.pk]),
            reverse("admin:config_config_history", args=[self.config.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_bulk_product_type_action_creates_history(self):
        before = self.product.history.count()

        response = self.client.post(
            reverse("admin:shop_shopproduct_changelist"),
            {
                "action": "update_selected_product_type",
                "_selected_action": [str(self.product.pk)],
                "product_type": "1",
                "product_type_operation": "show",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_type1, "1")
        self.assertEqual(self.product.history.count(), before + 1)
        latest = self.product.history.order_by("-history_date", "-history_id").first()
        self.assertEqual(latest.history_change_reason, "admin bulk product type change")

    def test_history_list_uses_action_verbs_for_created_rows(self):
        response = self.client.get(reverse("admin:shop_shoporder_history", args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "생성")
        self.assertNotContains(response, "생성일시")
        self.assertNotContains(response, "Project override")

    def test_history_record_view_renders_and_attributes_the_admin_user(self):
        record = self.order.history.first()
        response = self.client.get(
            reverse("admin:shop_shoporder_simple_history", args=[self.order.pk, record.history_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.admin_user.username)

    def test_history_revert_button_is_bound_to_the_admin_form(self):
        record = self.config.history.order_by("history_date").first()
        response = self.client.get(
            reverse("admin:config_config_simple_history", args=[self.config.pk, record.history_id])
        )

        self.assertEqual(response.status_code, 200)
        # Unfold renders submit buttons outside the form; without this attribute Revert does nothing.
        form_id = f"{Config.history.model._meta.model_name}_form"
        self.assertContains(response, f'form="{form_id}"')
        self.assertContains(response, 'name="_save"')

    def test_audit_log_uses_action_verbs_not_timestamp_labels(self):
        response = self.client.get(reverse("admin-audit-log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "생성")
        self.assertNotContains(response, "생성일시")

    def test_audit_log_can_be_exported_as_csv(self):
        response = self.client.get(reverse("admin-audit-log"), {"export": "csv"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        body = response.content.decode("utf-8-sig")
        self.assertIn("시각,사용자,모델,대상,작업,변경 내용,이력 URL", body)
        self.assertIn(self.order.od_id, body)
        self.assertIn(self.product.it_id, body)

    def test_audit_log_paginates_history_beyond_one_page(self):
        for index in range(55):
            Config.objects.create(name=f"cf_audit_page_{index}", value=str(index))

        response = self.client.get(reverse("admin-audit-log"), {"page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["page_obj"].paginator.num_pages, 1)
        self.assertTrue(response.context["entries"])

    def test_audit_log_export_refuses_more_than_the_row_limit(self):
        with patch("gnu_jango.core.audit.AUDIT_EXPORT_LIMIT", 1):
            response = self.client.get(reverse("admin-audit-log"), {"export": "csv"})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Too many audit rows", status_code=400)

    def test_audit_log_lists_each_audited_model_and_the_actor(self):
        response = self.client.get(reverse("admin-audit-log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.od_id)
        self.assertContains(response, self.coupon_log.cp_id)
        self.assertContains(response, self.config.name)
        self.assertContains(response, self.product.it_id)
        self.assertContains(response, self.coupon.cp_subject)
        self.assertContains(response, self.admin_user.username)
        self.assertContains(response, "Audit log")
        self.assertContains(
            response,
            reverse(
                "admin:shop_shoporder_simple_history",
                args=[self.order.pk, self.order.history.first().history_id],
            ),
        )

    def test_audit_log_can_be_filtered_to_one_model(self):
        response = self.client.get(reverse("admin-audit-log"), {"model": "shop.shoporder"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.od_id)
        self.assertNotContains(response, self.coupon_log.cp_id)

    def test_audit_log_is_staff_only(self):
        self.client.logout()
        response = self.client.get(reverse("admin-audit-log"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_audit_log_shows_only_models_the_staff_user_may_view(self):
        staff = get_user_model().objects.create_user(
            username="settings-viewer",
            password="pw",
            is_staff=True,
        )
        staff.user_permissions.add(Permission.objects.get(codename="view_config"))
        self.client.force_login(staff)

        response = self.client.get(reverse("admin-audit-log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.config.name)
        self.assertNotContains(response, self.order.od_id)

    def test_audit_log_renders_for_staff_without_any_model_permission(self):
        staff = get_user_model().objects.create_user(
            username="audit-viewer",
            password="pw",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("admin-audit-log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No audit entries")

    def test_history_request_middleware_attributes_the_admin_user(self):
        order = ShopOrder.objects.create(od_id="AUDIT-MIDDLEWARE", od_name="Audit Middleware")
        request = RequestFactory().get("/admin/")
        request.user = self.admin_user

        def change_order(_request):
            order.od_shop_memo = "changed in an admin request"
            order.save()
            return HttpResponse("ok")

        HistoryRequestMiddleware(change_order)(request)

        self.assertEqual(order.history.first().history_user, self.admin_user)

    def test_config_history_revert_restores_the_previous_value(self):
        original = self.config.history.order_by("history_date").first()
        self.config.value = "two"
        self.config.save()

        response = self.client.post(
            reverse("admin:config_config_simple_history", args=[self.config.pk, original.history_id]),
            {"name": self.config.name, "value": "one", "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.value, "one")

    def test_config_history_revert_rejects_an_invalid_value_type(self):
        setting = Config.objects.create(name="cf_point_term", value="30")
        original = setting.history.order_by("history_date").first()
        setting.value = "60"
        setting.save()

        response = self.client.post(
            reverse("admin:config_config_simple_history", args=[setting.pk, original.history_id]),
            {"name": setting.name, "value": "not-an-integer", "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        setting.refresh_from_db()
        self.assertEqual(setting.value, "60")

    def test_config_history_revert_rejects_an_unknown_setting(self):
        setting = Config.objects.create(name="cf_audit_unknown", value="one")
        original = setting.history.order_by("history_date").first()
        setting.value = "two"
        setting.save()

        response = self.client.post(
            reverse("admin:config_config_simple_history", args=[setting.pk, original.history_id]),
            {"name": setting.name, "value": "one", "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        setting.refresh_from_db()
        self.assertEqual(setting.value, "two")

    def test_secret_config_history_cannot_be_reverted(self):
        secret = Config.objects.create(name="cf_toss_secret_key", value="live-secret")
        original = secret.history.order_by("history_date").first()
        secret.value = "new-secret"
        secret.save()

        response = self.client.post(
            reverse("admin:config_config_simple_history", args=[secret.pk, original.history_id]),
            {"name": secret.name, "value": REDACTED_CONFIG_VALUE, "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        secret.refresh_from_db()
        self.assertEqual(secret.value, "new-secret")

    def test_order_restore_keeps_protected_fields_and_applies_safe_fields(self):
        model_admin = ShopOrderAdmin(ShopOrder, admin.site)
        record = self.order.history.order_by("history_date").first()

        historical = record.instance
        historical.od_status = "취소"
        historical.od_addr1 = "Restored address"
        historical.od_cart_price = 999999
        historical.od_mod_history = "old history text"
        self.assertTrue(model_admin._restore_safe_history_fields(historical))

        self.assertEqual(historical.od_status, self.order.od_status)
        self.assertEqual(historical.od_cart_price, self.order.od_cart_price)
        self.assertEqual(historical.od_mod_history, self.order.od_mod_history)
        self.assertEqual(historical.od_addr1, "Restored address")

    def test_order_history_post_restores_safe_fields_and_keeps_order_state(self):
        self.order.od_addr1 = "Current address"
        self.order.save()
        record = self.order.history.order_by("history_date").first()
        data = {
            key: ("" if value is None else value)
            for key, value in model_to_dict(record.instance).items()
        }
        ordered_at = timezone.localtime(self.order.od_datetime)
        data.update(
            od_datetime_0=ordered_at.strftime("%Y-%m-%d"),
            od_datetime_1=ordered_at.strftime("%H:%M:%S"),
            od_addr1="Restored by history",
            od_status="취소",
            _save="Revert",
        )

        response = self.client.post(
            reverse("admin:shop_shoporder_simple_history", args=[self.order.pk, record.history_id]),
            data,
        )

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.od_addr1, "Restored by history")
        self.assertEqual(self.order.od_status, "order")

    def test_point_history_revert_is_rejected_server_side(self):
        record = self.point.history.order_by("history_date").first()
        before = self.point.po_content

        response = self.client.post(
            reverse("admin:users_user_point_simple_history", args=[self.point.pk, record.history_id]),
            {"po_content": "forged restore", "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        self.point.refresh_from_db()
        self.assertEqual(self.point.po_content, before)

    def test_coupon_log_history_revert_is_rejected_server_side(self):
        record = self.coupon_log.history.order_by("history_date").first()
        before = self.coupon_log.cp_price

        response = self.client.post(
            reverse(
                "admin:shop_shopcouponlog_simple_history",
                args=[self.coupon_log.pk, record.history_id],
            ),
            {"cp_price": 999999, "_save": "Revert"},
        )

        self.assertEqual(response.status_code, 302)
        self.coupon_log.refresh_from_db()
        self.assertEqual(self.coupon_log.cp_price, before)
