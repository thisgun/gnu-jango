"""Cash receipt and tax invoice requests on shop orders (migration 0028).

Members may ask for a cash receipt (income deduction or business expense proof) when paying by bank
deposit, virtual account or account transfer, and for a tax invoice with company, business number
and email. Toss gets the receipt type and the customer's identification number for its own
issuance; that number is checked and handed back to the checkout browser only, never stored.
"""

from django.test import override_settings
from rest_framework.test import APIClient

from gnu_jango.api import shop_payments
from gnu_jango.api.v1_shop import order_payload
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_payments_api import (
    BANK_ACCOUNT,
    CONFIG_URL,
    FAKE_TOSS,
    ORDER_FIELDS,
    PaymentTestBase,
)
from gnu_jango.shop.models import ShopOrder

ORDERS_URL = "/api/v1/shop/orders"
PHONE = "010-1234-5678"
BUSINESS_NO = "123-45-67890"
TAX_FIELDS = {
    "od_tax_invoice_request": 1,
    "od_tax_company": "  주식회사 예시  ",
    "od_tax_business_no": BUSINESS_NO,
    "od_tax_email": "tax@example.test",
}


@override_settings(**FAKE_TOSS)
class TaxInvoiceRequestTests(PaymentTestBase):
    def test_a_member_tax_invoice_request_is_stored_with_its_recipient(self):
        order = self.prepared_order(**TAX_FIELDS)

        self.assertTrue(order.od_tax_invoice_request)
        self.assertEqual(order.od_tax_company, "주식회사 예시")
        self.assertEqual(order.od_tax_business_no, "1234567890")
        self.assertEqual(order.od_tax_email, "tax@example.test")

    def test_an_invalid_business_number_or_email_is_refused_before_an_order_exists(self):
        for override in ({"od_tax_business_no": "123-45"}, {"od_tax_email": "not-an-email"}, {"od_tax_company": " "}):
            with self.subTest(override=override):
                response = self.prepare(**{**TAX_FIELDS, **override})
                self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(ShopOrder.objects.exists())

    def test_recipient_fields_are_dropped_when_no_invoice_is_requested(self):
        order = self.prepared_order(**{**TAX_FIELDS, "od_tax_invoice_request": 0})

        self.assertEqual((order.od_tax_company, order.od_tax_business_no, order.od_tax_email), ("", "", ""))

    def test_guests_cannot_request_receipts(self):
        guest = APIClient()
        for fields in (TAX_FIELDS, {"od_cash_request": 1, "od_settle_case": "iche"}):
            with self.subTest(fields=fields):
                response = self.prepare(client=guest, od_pwd="guest-pass-1", **fields)
                self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(ShopOrder.objects.exists())


@override_settings(**FAKE_TOSS)
class TransferCashReceiptTests(PaymentTestBase):
    def cash_request(self, **fields):
        values = {
            "od_settle_case": "iche",
            "od_cash_request": 1,
            "od_cash_type": "income",
            "cash_receipt_registration_number": PHONE,
            **fields,
        }
        return self.prepare(**values)

    def test_the_identification_number_goes_back_to_the_browser_but_is_not_stored(self):
        response = self.cash_request()

        self.assertEqual(response.status_code, 200, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["cash_receipt_request"])
        self.assertEqual(data["cash_receipt_type"], "income")
        self.assertEqual(data["cash_receipt_registration_number"], "01012345678")
        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertTrue(order.od_cash_request)
        self.assertEqual(order.od_cash_type, "income")
        stored = " ".join(str(value) for value in ShopOrder.objects.filter(pk=order.pk).values().first().values())
        self.assertNotIn("01012345678", stored.replace("-", ""))

    def test_identification_numbers_are_checked_for_the_receipt_type(self):
        cases = (
            {"cash_receipt_registration_number": ""},
            {"cash_receipt_registration_number": "1234"},
            {"od_cash_type": "expense", "cash_receipt_registration_number": PHONE},
            {"od_cash_type": "gift"},
        )
        for override in cases:
            with self.subTest(override=override):
                self.assertEqual(self.cash_request(**override).status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    def test_a_business_expense_receipt_takes_a_business_number(self):
        response = self.cash_request(od_cash_type="expense", cash_receipt_registration_number=BUSINESS_NO)

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["cash_receipt_registration_number"], "1234567890")

    def test_admin_settings_switch_receipts_off_per_method(self):
        Config.objects.update_or_create(name="de_taxsave_types", defaults={"value": "account,vbank"})
        self.assertEqual(self.cash_request().status_code, 400)

        Config.objects.update_or_create(name="de_taxsave_types", defaults={"value": "account,vbank,transfer"})
        Config.objects.update_or_create(name="de_taxsave_use", defaults={"value": "0"})
        self.assertEqual(self.cash_request().status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    def test_payment_config_tells_the_checkout_which_methods_allow_receipts(self):
        Config.objects.update_or_create(name="de_taxsave_types", defaults={"value": "account,transfer"})

        data = self.client.get(CONFIG_URL).json()["data"]

        self.assertEqual(data["cash_receipt"], {"enabled": True, "methods": {"bank": True, "vbank": False, "iche": True}})


class BankCashReceiptTests(PaymentTestBase):
    def test_a_bank_deposit_receipt_request_needs_no_number_and_is_recorded_for_the_admin(self):
        self.add_to_cart()
        body = {
            **ORDER_FIELDS,
            "od_settle_case": "bank",
            "od_bank_account": BANK_ACCOUNT,
            "od_deposit_name": "Pay Member",
            "od_cash_request": 1,
            "od_cash_type": "expense",
        }

        response = self.post(ORDERS_URL, body)

        self.assertIn(response.status_code, (200, 201), response.content[:300])
        order = ShopOrder.objects.get(user=self.member)
        self.assertTrue(order.od_cash_request)
        self.assertEqual(order.od_cash_type, "expense")


@override_settings(**FAKE_TOSS)
class TossCashReceiptConfirmTests(PaymentTestBase):
    def transfer_order(self):
        return self.prepared_order(
            od_settle_case="iche", od_cash_request=1, cash_receipt_registration_number=PHONE
        )

    def test_the_issued_receipt_number_and_url_are_saved_on_confirm(self):
        order = self.transfer_order()
        payment = self.toss_payment(
            order,
            method="TRANSFER",
            cashReceipt={"issueNumber": "CR-0001", "receiptUrl": "https://dashboard.tosspayments.com/receipt/cr1"},
        )

        response, _ = self.confirm_toss(order, payment=payment)

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_cash_no, "CR-0001")
        self.assertEqual(order.od_cash_res, "https://dashboard.tosspayments.com/receipt/cr1")

    def test_a_cancelled_receipt_or_a_non_web_address_is_not_saved(self):
        order = self.transfer_order()
        payment = self.toss_payment(
            order,
            method="TRANSFER",
            cashReceipts=[
                {"transactionType": "CANCEL", "issueNumber": "CR-OLD", "receiptUrl": "https://example.test/old"},
                {"issueNumber": "CR-0002", "receiptUrl": "javascript:alert(1)"},
            ],
        )

        self.confirm_toss(order, payment=payment)

        order.refresh_from_db()
        self.assertEqual(order.od_cash_no, "CR-0002")
        self.assertEqual(order.od_cash_res, "")


class ReceiptLinkAndLogTests(PaymentTestBase):
    def test_only_a_web_address_is_offered_as_the_receipt_link(self):
        # migrate_gnuboard5 copies Gnuboard's od_cash_info (PG response text) into od_cash_res.
        legacy = ShopOrder(od_id="LEGACY-1", od_cash_res='a:1:{s:6:"result";s:4:"0000";}')
        issued = ShopOrder(od_id="ISSUED-1", od_cash_no="CR-1", od_cash_res="https://example.test/receipt")

        self.assertEqual(order_payload(legacy)["cash_receipt_url"], "")
        self.assertEqual(order_payload(issued)["cash_receipt_url"], "https://example.test/receipt")

    def test_payment_logs_mask_receipt_and_customer_identifiers(self):
        redacted = shop_payments.redact_payment_data(
            {
                "cashReceipt": {"registrationNumber": "01012345678", "type": "소득공제"},
                "customerEmail": "pay@example.test",
                "od_tax_business_no": "1234567890",
                "od_tax_company": "주식회사 예시",
                "orderId": "OD-1",
            }
        )

        self.assertEqual(redacted["cashReceipt"]["registrationNumber"], "***redacted***")
        self.assertEqual(redacted["cashReceipt"]["type"], "소득공제")
        self.assertEqual(redacted["customerEmail"], "***redacted***")
        self.assertEqual(redacted["od_tax_business_no"], "***redacted***")
        self.assertEqual(redacted["od_tax_company"], "***redacted***")
        self.assertEqual(redacted["orderId"], "OD-1")
