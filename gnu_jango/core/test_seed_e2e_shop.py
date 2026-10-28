"""seed_e2e_shop: the data behind the Playwright checkout E2E (nextjs/tests/e2e-checkout.spec.ts).

It must converge to the same state on every run (the E2E reseeds before each CI run) and must never
touch a database that looks like a real shop.
"""

import json
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import configured_bank_accounts
from gnu_jango.config.models import Config
from gnu_jango.core.management.commands import seed_e2e_shop as seed
from gnu_jango.shop.models import ShopCoupon, ShopOrder, ShopProduct, ShopShippingPolicy
from gnu_jango.testing.factories import MemberFactory, ShopOrderFactory
from gnu_jango.users.models import User_Point


def run_seed(*args, **env):
    out = StringIO()
    with mock.patch.dict("os.environ", env):
        call_command("seed_e2e_shop", *args, stdout=out)
    return json.loads(out.getvalue())


class SeedE2EShopTests(TestCase):
    def test_refuses_without_debug_or_the_disposable_flag(self):
        with self.assertRaisesMessage(CommandError, "--i-know-this-is-disposable"):
            run_seed()
        self.assertFalse(get_user_model().objects.exists())

    @override_settings(DEBUG=True)
    def test_runs_under_debug_without_the_flag(self):
        self.assertEqual(run_seed()["member"]["mb_id"], seed.DEFAULT_MEMBER_ID)

    def test_creates_what_the_checkout_needs(self):
        data = run_seed("--i-know-this-is-disposable")

        member = get_user_model().objects.get(username=seed.DEFAULT_MEMBER_ID)
        self.assertTrue(member.check_password(seed.DEFAULT_MEMBER_PASSWORD))
        self.assertEqual(member.profile.user_point, 5000)
        self.assertEqual(data["member"], {"mb_id": member.username, "points": 5000})
        products = ShopProduct.objects.filter(category_id=data["category"]).order_by("it_id")
        self.assertEqual([(p.it_id, p.it_price, p.it_stock_qty, p.it_use) for p in products], [
            ("E2E0000001", 25000, 50, "1"),
            ("E2E0000002", 8000, 50, "1"),
        ])
        coupon = ShopCoupon.objects.get(pk=data["coupon"]["cp_id"])
        self.assertEqual((coupon.user, coupon.cp_method, coupon.cp_price, coupon.cp_used), (member, 2, 3000, ""))
        self.assertEqual(configured_bank_accounts(), [seed.BANK_ACCOUNT])
        policy = ShopShippingPolicy.objects.get(pk=1)
        self.assertEqual((policy.de_send_cost_case, policy.de_send_cost_list, policy.de_settle_point_unit), ("차등", "3000", 100))

    def test_seeded_member_can_order_by_bank_transfer_with_coupon_and_points(self):
        data = run_seed("--i-know-this-is-disposable")
        client = APIClient()
        login = client.post("/api/v1/auth/login", {"mb_id": seed.DEFAULT_MEMBER_ID, "mb_password": seed.DEFAULT_MEMBER_PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200, login.content[:300])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['data']['token']}")
        self.assertEqual(client.post("/api/v1/shop/cart", {"it_id": "E2E0000001", "ct_qty": 1}, format="json").status_code, 201)

        response = client.post("/api/v1/shop/orders", {
            "od_name": "E2E", "od_hp": "010-1234-5678", "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
            "od_settle_case": "무통장", "od_bank_account": seed.BANK_ACCOUNT, "od_deposit_name": "E2E",
            "cp_id": data["coupon"]["cp_id"], "point_use": 1000,
        }, format="json")

        self.assertEqual(response.status_code, 201, response.content[:400])
        order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
        self.assertEqual((order.od_status, order.od_cart_price, order.od_send_cost, order.od_coupon, order.od_receipt_point, order.od_misu),
                         ("주문", 25000, 3000, 3000, 1000, 24000))

    def test_rerun_is_idempotent(self):
        first = run_seed("--i-know-this-is-disposable")
        second = run_seed("--i-know-this-is-disposable")

        self.assertEqual(first, second)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(ShopProduct.objects.count(), 2)
        self.assertEqual(ShopCoupon.objects.count(), 1)
        self.assertEqual(User_Point.objects.count(), 1)
        self.assertEqual(Config.objects.filter(name="de_bank_account").count(), 1)

    def test_rerun_restores_stock_points_coupon_and_password_after_an_e2e_run(self):
        first = run_seed("--i-know-this-is-disposable")
        member = get_user_model().objects.get(username=seed.DEFAULT_MEMBER_ID)
        ShopProduct.objects.filter(pk="E2E0000001").update(it_stock_qty=3, it_soldout="1")
        ShopCoupon.objects.filter(pk=first["coupon"]["cp_id"]).update(cp_used="1")
        member.profile.user_point = 1200
        member.profile.save(update_fields=["user_point"])
        member.set_password("changed")
        member.save()

        second = run_seed("--i-know-this-is-disposable")

        member.refresh_from_db()
        self.assertTrue(member.check_password(seed.DEFAULT_MEMBER_PASSWORD))
        self.assertEqual(member.profile.user_point, 5000)
        product = ShopProduct.objects.get(pk="E2E0000001")
        self.assertEqual((product.it_stock_qty, product.it_soldout), (50, ""))
        self.assertNotEqual(second["coupon"]["cp_id"], first["coupon"]["cp_id"])
        self.assertEqual(ShopCoupon.objects.filter(user=member, cp_used="").count(), 1)

    def test_credentials_come_from_the_environment(self):
        data = run_seed("--i-know-this-is-disposable", E2E_MEMBER_ID="ci_buyer", E2E_MEMBER_PASSWORD="ci-pass-123", E2E_MEMBER_POINTS="2500")

        member = get_user_model().objects.get(username="ci_buyer")
        self.assertTrue(member.check_password("ci-pass-123"))
        self.assertEqual(data["member"], {"mb_id": "ci_buyer", "points": 2500})

    def test_refuses_a_database_with_real_members(self):
        for _ in range(seed.MAX_OTHER_MEMBERS + 1):
            MemberFactory()

        with self.assertRaisesMessage(CommandError, "Refusing to seed"):
            run_seed("--i-know-this-is-disposable")
        self.assertFalse(ShopProduct.objects.exists())

    def test_refuses_a_database_with_real_orders(self):
        for _ in range(seed.MAX_OTHER_ORDERS + 1):
            ShopOrderFactory()

        with self.assertRaisesMessage(CommandError, "Refusing to seed"):
            run_seed("--i-know-this-is-disposable")

    def test_orders_and_members_made_by_the_e2e_do_not_count_as_real(self):
        run_seed("--i-know-this-is-disposable")
        member = get_user_model().objects.get(username=seed.DEFAULT_MEMBER_ID)
        for _ in range(seed.MAX_OTHER_ORDERS + 2):
            ShopOrderFactory(user=member)
            ShopOrderFactory(od_email=f"guest@{seed.E2E_EMAIL_DOMAIN}")

        run_seed("--i-know-this-is-disposable")
