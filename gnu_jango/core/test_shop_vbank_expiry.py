from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from rest_framework.response import Response

from gnu_jango.shop.models import ShopOrder


class TossVirtualAccountExpiryCommandTests(TestCase):
    def create_order(self, *, due_date=None):
        return ShopOrder.objects.create(
            od_id="ODVBANKEXP",
            od_name="Virtual account buyer",
            od_receipt_price=1000,
            od_misu=1000,
            od_status="order",
            od_settle_case="가상계좌",
            od_pg="toss",
            od_tno="pay-expiry-test",
            od_vbank_status="WAITING_FOR_DEPOSIT",
            od_vbank_due_date=(due_date or timezone.now() - timedelta(hours=1)).isoformat(),
        )

    @patch("gnu_jango.core.management.commands.expire_toss_vbank_orders.cancel_pending_toss_vbank")
    def test_dry_run_lists_expired_order_without_provider_or_database_changes(self, cancel_provider):
        order = self.create_order()
        output = StringIO()

        call_command("expire_toss_vbank_orders", stdout=output)

        cancel_provider.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertIn("expired=1", output.getvalue())
        self.assertIn("mode=dry-run", output.getvalue())

    @patch("gnu_jango.core.management.commands.expire_toss_vbank_orders.cancel_pending_toss_vbank", return_value=None)
    def test_apply_cancels_expired_order_after_provider_confirmation(self, cancel_provider):
        order = self.create_order()
        output = StringIO()

        call_command("expire_toss_vbank_orders", "--apply", stdout=output)

        cancel_provider.assert_called_once()
        order.refresh_from_db()
        self.assertIn(order.od_status, {"취소", "cancel", "cancelled"})
        self.assertEqual(order.od_vbank_status, "CANCELED")
        self.assertEqual(order.od_receipt_price, 0)
        self.assertIn("cancelled=1", output.getvalue())

    @patch(
        "gnu_jango.core.management.commands.expire_toss_vbank_orders.cancel_pending_toss_vbank",
        return_value=Response({"message": "Toss unavailable"}, status=502),
    )
    def test_provider_failure_keeps_order_and_reservation_unchanged(self, cancel_provider):
        order = self.create_order()

        with self.assertRaises(CommandError):
            call_command("expire_toss_vbank_orders", "--apply", stdout=StringIO(), stderr=StringIO())

        cancel_provider.assert_called_once()
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertEqual(order.od_receipt_price, 1000)
        self.assertEqual(order.od_vbank_status, "WAITING_FOR_DEPOSIT")

    @patch("gnu_jango.core.management.commands.expire_toss_vbank_orders.cancel_pending_toss_vbank")
    def test_future_due_date_is_left_pending(self, cancel_provider):
        order = self.create_order(due_date=timezone.now() + timedelta(days=1))

        output = StringIO()
        call_command("expire_toss_vbank_orders", "--apply", stdout=output)

        cancel_provider.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertIn("skipped=1", output.getvalue())
