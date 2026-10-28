"""Admin role presets: which groups may export orders."""

from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase


class RolePresetExportTests(TestCase):
    def setUp(self):
        call_command("setup_admin_role_presets", stdout=StringIO())

    def codenames(self, role):
        return set(Group.objects.get(name=role).permissions.values_list("codename", flat=True))

    def test_shop_and_settlement_roles_can_export_orders(self):
        for role in ("쇼핑몰 운영자", "정산 담당자"):
            with self.subTest(role=role):
                self.assertTrue({"view_shoporder", "export_shoporder"} <= self.codenames(role))

    def test_customer_support_cannot_bulk_export_orders(self):
        codenames = self.codenames("고객지원")
        self.assertIn("view_shoporder", codenames)
        self.assertNotIn("export_shoporder", codenames)

    def test_export_grants_nothing_beyond_the_order_export_permission(self):
        for role in ("쇼핑몰 운영자", "정산 담당자"):
            with self.subTest(role=role):
                exports = {codename for codename in self.codenames(role) if codename.startswith("export_")}
                self.assertEqual(exports, {"export_shoporder"})
