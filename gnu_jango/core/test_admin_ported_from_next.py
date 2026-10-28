"""Features of the removed Next.js admin SPA (/admin) now live in the Django admin (/admin/).

The SPA duplicated the Django admin and several of its forms did not save what they showed; the
pieces the Django admin lacked are ported here: 1:1 inquiries with answers, blocking and leaving
members, point grants through the ledger, order status changes and cancellation with refunds, the
category tree, and an unanswered-inquiry count on the dashboard.
"""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext

from gnu_jango.api.community_common import GENERAL_QA_PRODUCT_ID
from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopOrderItem, ShopProduct, ShopQA
from gnu_jango.shop.order_statuses import STATUS_READY, STATUS_SHIPPING
from gnu_jango.users.models import Profile, User_Point


class AdminTestBase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="port-admin", email="port-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)

    def run_action(self, changelist, action, objects, **extra):
        data = {"action": action, "_selected_action": [str(obj.pk) for obj in objects], **extra}
        return self.client.post(reverse(changelist), data, follow=True)


class GeneralInquiryAdminTests(AdminTestBase):
    def setUp(self):
        super().setUp()
        self.general, _ = ShopProduct.objects.get_or_create(
            it_id=GENERAL_QA_PRODUCT_ID, defaults={"it_name": "1:1 inquiries", "it_use": "0"}
        )
        self.product = ShopProduct.objects.create(it_id="P100", it_name="Product", it_use="1")
        self.inquiry = ShopQA.objects.create(
            product=self.general, mb_id="buyer", iq_name="Buyer", iq_subject="배송 문의", iq_question="언제 오나요?"
        )
        self.product_question = ShopQA.objects.create(
            product=self.product, mb_id="buyer", iq_subject="Size?", iq_question="How big?"
        )
        Config.objects.create(
            name=f"qa_meta_{self.inquiry.pk}",
            value=json.dumps({"files": [{"path": "shop/qas/1/a.png", "name": "photo.png", "url": "/media/shop/qas/1/a.png"}, {}]}),
        )

    def test_the_inquiry_list_shows_only_1_1_inquiries(self):
        body = self.client.get(reverse("admin:shop_generalinquiry_changelist")).content.decode()
        self.assertIn("배송 문의", body)
        self.assertNotIn("Size?", body)

    def test_the_product_question_list_leaves_1_1_inquiries_out(self):
        body = self.client.get(reverse("admin:shop_shopqa_changelist")).content.decode()
        self.assertIn("Size?", body)
        self.assertNotIn("배송 문의", body)

    def test_the_waiting_filter_lists_unanswered_inquiries(self):
        ShopQA.objects.create(product=self.general, mb_id="other", iq_subject="답변 완료 문의", iq_answer="done")
        body = self.client.get(reverse("admin:shop_generalinquiry_changelist"), {"answer_status": "pending"}).content.decode()
        self.assertIn("배송 문의", body)
        self.assertNotIn("답변 완료 문의", body)

    def test_the_inquiry_page_shows_the_question_and_its_attachments(self):
        body = self.client.get(reverse("admin:shop_generalinquiry_change", args=[self.inquiry.pk])).content.decode()
        self.assertIn("언제 오나요?", body)
        self.assertIn("photo.png", body)
        self.assertIn("/media/shop/qas/1/a.png", body)

    def test_answering_saves_the_answer_and_a_default_answer_subject(self):
        url = reverse("admin:shop_generalinquiry_change", args=[self.inquiry.pk])
        response = self.client.post(url, {"iq_answer": "내일 도착합니다.", "answer_subject": "", "iq_secret": "0"})

        self.assertEqual(response.status_code, 302, response.content[:500])
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.iq_answer, "내일 도착합니다.")
        meta = json.loads(Config.objects.get(name=f"qa_meta_{self.inquiry.pk}").value)
        self.assertEqual(meta["answer_subject"], "RE: 배송 문의")
        self.assertEqual(meta["files"][0]["name"], "photo.png")

    def test_an_answer_subject_given_by_the_admin_is_kept(self):
        url = reverse("admin:shop_generalinquiry_change", args=[self.inquiry.pk])
        self.client.post(url, {"iq_answer": "답변", "answer_subject": "배송 안내", "iq_secret": "0"})
        meta = json.loads(Config.objects.get(name=f"qa_meta_{self.inquiry.pk}").value)
        self.assertEqual(meta["answer_subject"], "배송 안내")

    def test_inquiries_cannot_be_added_from_the_admin(self):
        self.assertEqual(self.client.get(reverse("admin:shop_generalinquiry_add")).status_code, 403)


class MemberActionTests(AdminTestBase):
    def setUp(self):
        super().setUp()
        self.member = get_user_model().objects.create_user(username="member1", email="m1@example.test", password="pw")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)

    def test_blocking_deactivates_and_signs_the_member_out(self):
        version = self.profile.token_version
        self.run_action("admin:auth_user_changelist", "block_selected_members", [self.member])

        self.member.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertGreater(self.profile.token_version, version)

    def test_leaving_stamps_the_leave_date_and_deactivates(self):
        self.run_action("admin:auth_user_changelist", "leave_selected_members", [self.member])

        self.member.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertIsNotNone(self.profile.leave_date)

    def test_superusers_and_the_acting_admin_are_never_blocked(self):
        other_admin = get_user_model().objects.create_superuser(username="boss", email="boss@example.test", password="pw")
        self.run_action("admin:auth_user_changelist", "block_selected_members", [other_admin, self.admin])

        other_admin.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertTrue(other_admin.is_active)
        self.assertTrue(self.admin.is_active)


class PointGrantTests(AdminTestBase):
    def setUp(self):
        super().setUp()
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        self.member = get_user_model().objects.create_user(username="pointee", email="p@example.test", password="pw")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)

    def grant(self, points, content="관리자 지급"):
        return self.client.post(
            reverse("admin:users_user_point_add"), {"user": self.member.pk, "po_point": points, "po_content": content}
        )

    def test_a_grant_goes_through_the_ledger_and_updates_the_balance(self):
        response = self.grant(1500)

        self.assertEqual(response.status_code, 302, response.content[:500])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 1500)
        row = User_Point.objects.get(user=self.member)
        self.assertEqual((row.po_point, row.po_mb_point, row.po_rel_table), (1500, 1500, "@passive"))

    def test_a_deduction_larger_than_the_balance_is_refused(self):
        self.grant(100)
        response = self.grant(-500)

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 100)
        self.assertEqual(User_Point.objects.filter(user=self.member).count(), 1)


class OrderStatusAdminTests(AdminTestBase):
    def setUp(self):
        super().setUp()
        self.product = ShopProduct.objects.create(it_id="O100", it_name="Shirt", it_use="1", it_stock_qty=5)
        self.order = ShopOrder.objects.create(od_id="ORDADMIN1", od_name="Buyer", od_status="입금")
        self.item = ShopOrderItem.objects.create(
            order=self.order, product=self.product, ct_id="c1", it_id="O100", it_name="Shirt", ct_status="입금"
        )

    def test_the_bulk_action_changes_the_order_and_its_items(self):
        # youngcart orderlistupdate.php moves one step at a time: 입금 -> 준비
        self.run_action("admin:shop_shoporder_changelist", "change_selected_order_status", [self.order], od_status="준비")

        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((self.order.od_status, self.item.ct_status), ("준비", "준비"))

    def test_choosing_cancel_runs_the_cancellation_with_refunds(self):
        self.run_action("admin:shop_shoporder_changelist", "change_selected_order_status", [self.order], od_status="취소")

        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.order.od_status, "취소")
        self.assertEqual(self.item.ct_status, "취소")

    def test_the_bulk_action_without_a_status_changes_nothing(self):
        self.run_action("admin:shop_shoporder_changelist", "change_selected_order_status", [self.order], od_status="")
        self.order.refresh_from_db()
        self.assertEqual(self.order.od_status, "입금")


class CategoryTreeAdminTests(AdminTestBase):
    def test_the_list_shows_the_tree_depth_and_product_counts(self):
        top = ShopCategory.objects.create(ca_id="10", ca_name="의류")
        ShopCategory.objects.create(ca_id="1010", ca_name="상의", ca_parent="10")
        ShopProduct.objects.create(it_id="C1", it_name="One", category=top)
        ShopProduct.objects.create(it_id="C2", it_name="Two", category=top)

        body = self.client.get(reverse("admin:shop_shopcategory_changelist")).content.decode()

        self.assertIn("└ 상의", body)
        self.assertIn('data-product-count="2"', body)


class DashboardInquiryCountTests(AdminTestBase):
    def test_the_dashboard_counts_unanswered_1_1_inquiries(self):
        cache.delete("admin_ops_summary")
        general, _ = ShopProduct.objects.get_or_create(
            it_id=GENERAL_QA_PRODUCT_ID, defaults={"it_name": "1:1 inquiries", "it_use": "0"}
        )
        ShopQA.objects.create(product=general, iq_subject="waiting one")
        body = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn(reverse("admin:shop_generalinquiry_changelist"), body)


class DashboardKpiTests(AdminTestBase):
    def test_the_dashboard_shows_sales_and_inventory_kpis(self):
        cache.delete("admin_ops_summary")
        ShopProduct.objects.create(it_id="LOW-STOCK", it_name="Low stock", it_use="1", it_stock_qty=0)
        ShopOrder.objects.create(
            od_id="KPI-ORDER",
            od_name="KPI buyer",
            od_receipt_price=10000,
            od_refund_price=1000,
        )

        body = self.client.get(reverse("admin:index")).content.decode()

        self.assertIn(gettext("Today sales"), body)
        self.assertIn(gettext("Low stock"), body)
        self.assertIn("stock-list", body)


class ShippingBulkActionTests(AdminTestBase):
    def test_selected_ready_orders_get_a_carrier_invoice_and_move_to_shipping(self):
        product = ShopProduct.objects.create(it_id="SHIP-P1", it_name="Shipped item", it_use="1")
        order = ShopOrder.objects.create(od_id="SHIP-ORDER", od_name="Buyer", od_status=STATUS_READY)
        ShopOrderItem.objects.create(
            order=order,
            product=product,
            ct_id="SHIP-LINE",
            it_id=product.it_id,
            it_name=product.it_name,
            ct_status=STATUS_READY,
        )

        self.run_action(
            "admin:shop_shoporder_changelist",
            "set_selected_shipping",
            [order],
            od_delivery_company="CJ",
            od_invoice="1234567890",
        )

        order.refresh_from_db()
        self.assertEqual(order.od_status, STATUS_SHIPPING)
        self.assertEqual(order.od_invoice, "1234567890")
        self.assertTrue(order.od_delivery_company)
        self.assertTrue(order.od_invoice_time)

    def test_send_sms_option_is_forwarded_to_the_shipping_transition(self):
        product = ShopProduct.objects.create(it_id="SHIP-SMS", it_name="SMS item", it_use="1")
        order = ShopOrder.objects.create(od_id="SHIP-SMS-ORDER", od_name="Buyer", od_status=STATUS_READY)
        ShopOrderItem.objects.create(
            order=order,
            product=product,
            ct_id="SHIP-SMS-LINE",
            it_id=product.it_id,
            it_name=product.it_name,
            ct_status=STATUS_READY,
        )

        with patch("gnu_jango.shop.delivery_import.move_order_status", return_value=object()) as transition:
            self.run_action(
                "admin:shop_shoporder_changelist",
                "set_selected_shipping",
                [order],
                od_delivery_company="CJ",
                od_invoice="SMS-123",
                send_sms="on",
            )

        transition.assert_called_once()
        self.assertTrue(transition.call_args.kwargs["send_sms"])

    def test_no_sms_is_sent_unless_the_option_is_checked(self):
        product = ShopProduct.objects.create(it_id="SHIP-NOSMS", it_name="Quiet item", it_use="1")
        order = ShopOrder.objects.create(od_id="SHIP-NOSMS-ORDER", od_name="Buyer", od_status=STATUS_READY)
        ShopOrderItem.objects.create(
            order=order,
            product=product,
            ct_id="SHIP-NOSMS-LINE",
            it_id=product.it_id,
            it_name=product.it_name,
            ct_status=STATUS_READY,
        )

        with patch("gnu_jango.shop.delivery_import.move_order_status", return_value=object()) as transition:
            self.run_action(
                "admin:shop_shoporder_changelist",
                "set_selected_shipping",
                [order],
                od_delivery_company="CJ",
                od_invoice="NOSMS-123",
            )

        transition.assert_called_once()
        self.assertFalse(transition.call_args.kwargs["send_sms"])


class NextAdminRemovalTests(AdminTestBase):
    def test_the_old_spa_address_moves_to_the_django_admin(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/admin/")

    def test_the_spa_pages_are_gone(self):
        for path in ("/admin/boards", "/admin/members", "/admin/qas", "/admin/settings", "/admin.txt"):
            with self.subTest(path=path):
                self.assertNotIn("__NEXT_DATA__", self.client.get(path, follow=True).content.decode())
                self.assertNotIn("/_next/static/", self.client.get(path, follow=True).content.decode())

    def test_the_shop_app_index_of_the_django_admin_is_reachable_again(self):
        self.assertEqual(self.client.get("/admin/shop/").status_code, 200)

    def test_the_admin_rest_api_is_gone(self):
        for path in ("/api/v1/admin/dashboard/stats", "/api/v1/admin/members", "/api/v1/admin/shop/orders"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class ReviewFollowUpTests(AdminTestBase):
    """Gaps found in review: proxy deletes, cancelled orders, staff limits, audit log, local invoice time."""

    def test_deleting_an_inquiry_in_its_admin_drops_the_attachment_metadata(self):
        general, _ = ShopProduct.objects.get_or_create(
            it_id=GENERAL_QA_PRODUCT_ID, defaults={"it_name": "1:1 inquiries", "it_use": "0"}
        )
        inquiry = ShopQA.objects.create(product=general, iq_subject="지울 문의")
        Config.objects.create(name=f"qa_meta_{inquiry.pk}", value=json.dumps({"files": [{}, {}]}))

        self.client.post(reverse("admin:shop_generalinquiry_delete", args=[inquiry.pk]), {"post": "yes"})

        self.assertFalse(ShopQA.objects.filter(pk=inquiry.pk).exists())
        self.assertFalse(Config.objects.filter(name=f"qa_meta_{inquiry.pk}").exists())

    def make_order(self, status):
        product = ShopProduct.objects.create(it_id=f"R{ShopOrder.objects.count()}", it_name="Item", it_use="1")
        order = ShopOrder.objects.create(od_id=f"REVIEW{ShopOrder.objects.count()}", od_name="Buyer", od_status=status)
        ShopOrderItem.objects.create(order=order, product=product, ct_id="c", it_id=product.it_id, it_name="Item", ct_status=status)
        return order

    def test_a_cancelled_order_is_not_moved_back_by_the_bulk_action(self):
        order = self.make_order("취소")
        self.run_action("admin:shop_shoporder_changelist", "change_selected_order_status", [order], od_status="입금")
        order.refresh_from_db()
        self.assertEqual(order.od_status, "취소")

    def test_status_changes_are_written_to_the_admin_log(self):
        from django.contrib.admin.models import LogEntry

        order = self.make_order("입금")
        self.run_action("admin:shop_shoporder_changelist", "change_selected_order_status", [order], od_status="준비")
        self.assertTrue(LogEntry.objects.filter(object_id=str(order.pk), change_message__contains="준비").exists())

    def test_the_order_form_applies_the_status_after_the_items_are_saved(self):
        from types import SimpleNamespace

        from django.contrib import admin
        from django.test import RequestFactory

        order = self.make_order("준비")
        model_admin = admin.site._registry[ShopOrder]
        request = RequestFactory().post("/admin/")
        request.user = self.admin
        form = SimpleNamespace(
            changed_data=["od_status", "od_invoice", "od_delivery_company"],
            initial={"od_status": "준비"},
            instance=order,
            save_m2m=lambda: None,
        )
        order.od_status = "배송"
        order.od_invoice = "123-456"
        order.od_delivery_company = "CJ대한통운"
        model_admin.save_model(request, order, form, True)
        model_admin.save_related(request, form, [], True)

        order.refresh_from_db()
        self.assertEqual(order.od_status, "배송")
        self.assertEqual(order.items.get().ct_status, "배송")
        from django.utils import timezone

        self.assertTrue(order.od_invoice_time.startswith(timezone.localtime().strftime("%Y-%m-%d")))

    def test_staff_without_superuser_rights_cannot_block_other_staff(self):
        from django.contrib.auth.models import Permission

        manager = get_user_model().objects.create_user(username="manager", email="mgr@example.test", password="pw", is_staff=True)
        manager.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        colleague = get_user_model().objects.create_user(username="colleague", email="col@example.test", password="pw", is_staff=True)
        member = get_user_model().objects.create_user(username="plain", email="plain@example.test", password="pw")
        self.client.force_login(manager)

        self.run_action("admin:auth_user_changelist", "block_selected_members", [colleague, member])

        colleague.refresh_from_db()
        member.refresh_from_db()
        self.assertTrue(colleague.is_active)
        self.assertFalse(member.is_active)
