"""youngcart order processing in the shop admin (adm/shop_admin/orderlistupdate.php,
orderformcartupdate.php, orderlistdelete.php): status transitions, payment and refund records,
PG cancellation, permission checks on the order reports, and order lines that cannot be edited
by hand."""

import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from gnu_jango.shop.models import ShopOrder

REPORT_URLS = (
    "admin:shop_shoporder_reports",
    "admin:shop_shoporder_sales_rank",
    "admin:shop_shoporder_print",
    "admin:shop_shoporder_unresolved",
)


class OrderReportPermissionTests(TestCase):
    def setUp(self):
        ShopOrder.objects.create(od_id="PERM1", od_name="홍길동", od_hp="010-1234-5678", od_misu=1000)
        self.staff = get_user_model().objects.create_user(
            username="community", email="community@example.test", password="pw", is_staff=True
        )
        call_command("setup_admin_role_presets", stdout=io.StringIO())
        self.staff.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        self.client.force_login(self.staff)

    def test_staff_without_order_permissions_get_403_on_every_report_and_export(self):
        for name in REPORT_URLS:
            for query in ("", "?export=csv"):
                with self.subTest(name=name, query=query):
                    response = self.client.get(reverse(name) + query)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("010-1234-5678", response.content.decode("utf-8", "replace"))

    def test_the_order_view_permission_opens_the_reports(self):
        self.staff.user_permissions.add(Permission.objects.get(codename="view_shoporder"))
        for name in REPORT_URLS:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        response = self.client.get(reverse("admin:shop_shoporder_unresolved") + "?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PERM1", response.content.decode("utf-8-sig"))

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        self.client.logout()
        response = self.client.get(reverse("admin:shop_shoporder_reports"))
        self.assertEqual(response.status_code, 302)
