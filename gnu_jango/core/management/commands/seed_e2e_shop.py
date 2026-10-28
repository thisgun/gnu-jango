"""Seed a disposable database with what the Playwright checkout E2E (nextjs/tests/e2e-checkout.spec.ts) needs.

    python manage.py seed_e2e_shop [--i-know-this-is-disposable]

Creates (or brings back to the same state, so it can run again before every E2E run):

* a member whose id and password come from E2E_MEMBER_ID / E2E_MEMBER_PASSWORD (test-only defaults),
  with points topped up to E2E_MEMBER_POINTS and one unused whole-order coupon;
* a category with two simple in-stock products, their stock reset to E2E_PRODUCT_STOCK;
* bank transfer (무통장입금) with one account, a 3,000 won shipping fee below 50,000 and point
  rules (min 1,000, unit 100).

It prints the ids as JSON. The member's password is published in this file, so the command refuses
to run unless DEBUG is on or --i-know-this-is-disposable is given, and it also refuses a database that
already holds more than a handful of other members or orders (a real shop, not a CI database).
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCoupon, ShopOrder, ShopProduct, ShopShippingPolicy
from gnu_jango.testing.factories import (
    MemberFactory,
    ShopCategoryFactory,
    ShopCouponFactory,
    ShopProductFactory,
    give_points,
)
from gnu_jango.users.models import Profile

DEFAULT_MEMBER_ID = "e2e_buyer"
DEFAULT_MEMBER_PASSWORD = "e2e-Checkout-Pass-2026"
# Orders and members the E2E itself creates carry this address domain, so they never count as "real".
E2E_EMAIL_DOMAIN = "e2e.example.test"
# A CI database holds only what this command and the E2E runs create; more than this is a real shop.
MAX_OTHER_MEMBERS = 3
MAX_OTHER_ORDERS = 3

CATEGORY_ID = "e2"
CATEGORY_NAME = "E2E 테스트 상품"
# Product A is above the coupon minimum on its own; product B is the cheap add-on.
PRODUCT_A = {"it_id": "E2E0000001", "it_name": "E2E 머그컵", "it_price": 25000}
PRODUCT_B = {"it_id": "E2E0000002", "it_name": "E2E 티코스터", "it_price": 8000}
COUPON_SUBJECT = "E2E 주문할인 3,000원"
COUPON_PRICE = 3000
COUPON_MINIMUM = 20000
BANK_ACCOUNT = "E2E은행 000-0000-0000 그누장고"
SHIPPING = {
    "de_send_cost_case": "차등",
    "de_send_cost_limit": "50000",
    "de_send_cost_list": "3000",
    "de_delivery_company": "E2E택배",
    "de_settle_min_point": 1000,
    "de_settle_max_point": 100000,
    "de_settle_point_unit": 100,
}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError as exc:
        raise CommandError(f"{name} must be an integer.") from exc


class Command(BaseCommand):
    help = "Seed a disposable database for the Playwright checkout E2E (refuses real databases)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--i-know-this-is-disposable",
            action="store_true",
            dest="disposable",
            help="Run with DEBUG off (CI). The database must still be an empty/test one.",
        )

    def handle(self, *args, **options):
        member_id = os.environ.get("E2E_MEMBER_ID") or DEFAULT_MEMBER_ID
        password = os.environ.get("E2E_MEMBER_PASSWORD") or DEFAULT_MEMBER_PASSWORD
        points = env_int("E2E_MEMBER_POINTS", 5000)
        stock = env_int("E2E_PRODUCT_STOCK", 50)

        if not settings.DEBUG and not options["disposable"]:
            raise CommandError(
                "seed_e2e_shop creates an account with a published password. It runs only with DEBUG on "
                "or with --i-know-this-is-disposable on a throwaway database."
            )
        self.refuse_real_database(member_id)

        with transaction.atomic():
            member = self.member(member_id, password)
            category = ShopCategoryFactory(ca_id=CATEGORY_ID, ca_name=CATEGORY_NAME)
            products = [self.product(spec, category, stock) for spec in (PRODUCT_A, PRODUCT_B)]
            self.shop_settings()
            balance = self.top_up_points(member, points)
            coupon = self.unused_coupon(member)

        self.stdout.write(json.dumps({
            "member": {"mb_id": member.username, "points": balance},
            "category": category.ca_id,
            "products": [
                {"it_id": product.it_id, "it_name": product.it_name, "it_price": product.it_price,
                 "it_stock_qty": product.it_stock_qty}
                for product in products
            ],
            "coupon": {"cp_id": coupon.cp_id, "cp_subject": coupon.cp_subject, "cp_price": coupon.cp_price,
                       "cp_minimum": coupon.cp_minimum},
            "bank_account": BANK_ACCOUNT,
            "shipping": {"fee": int(SHIPPING["de_send_cost_list"]), "free_from": int(SHIPPING["de_send_cost_limit"])},
        }, ensure_ascii=False))

    def refuse_real_database(self, member_id):
        user_model = get_user_model()
        other_members = (
            user_model.objects.exclude(username=member_id).exclude(email__endswith=f"@{E2E_EMAIL_DOMAIN}").count()
        )
        other_orders = (
            ShopOrder.objects.exclude(user__username=member_id).exclude(od_email__endswith=f"@{E2E_EMAIL_DOMAIN}").count()
        )
        if other_members > MAX_OTHER_MEMBERS or other_orders > MAX_OTHER_ORDERS:
            raise CommandError(
                f"Refusing to seed: this database already has {other_members} other member(s) and "
                f"{other_orders} other order(s). seed_e2e_shop is for an empty, disposable database."
            )

    def member(self, member_id, password):
        user = get_user_model().objects.filter(username=member_id).first()
        if user is None:
            return MemberFactory(
                username=member_id,
                email=f"{member_id}@{E2E_EMAIL_DOMAIN}",
                first_name="E2E 구매자",
                password=password,
            )
        # a rerun keeps the account but makes sure the documented password still logs in
        user.set_password(password)
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        return user

    def product(self, spec, category, stock):
        product = ShopProductFactory(it_id=spec["it_id"], it_name=spec["it_name"], category=category,
                                     it_price=spec["it_price"], it_stock_qty=stock)
        # get_or_create keeps an existing row as it was: put price, stock and sale state back
        ShopProduct.objects.filter(pk=product.pk).update(
            it_name=spec["it_name"], category=category, it_price=spec["it_price"], it_stock_qty=stock,
            it_use="1", it_soldout="", it_tel_inq="",
        )
        product.refresh_from_db()
        return product

    def shop_settings(self):
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults=SHIPPING)
        for name, value in (("de_bank_use", "1"), ("de_bank_account", BANK_ACCOUNT), ("cf_use_point", "1")):
            Config.objects.update_or_create(name=name, defaults={"value": value})

    def top_up_points(self, member, target):
        profile, _ = Profile.objects.get_or_create(user=member)
        if profile.user_point < target:
            give_points(member, target - profile.user_point, "E2E 테스트 포인트")
        profile.refresh_from_db()
        return profile.user_point

    def unused_coupon(self, member):
        today = timezone.localdate()
        coupon = (
            ShopCoupon.objects.filter(user=member, cp_subject=COUPON_SUBJECT, cp_used="", cp_end__gte=today)
            .order_by("created_at")
            .first()
        )
        if coupon is None:
            # the previous one was spent by an E2E order: issue a fresh one rather than un-using it
            coupon = ShopCouponFactory(user=member, cp_subject=COUPON_SUBJECT, cp_method=2,
                                       cp_price=COUPON_PRICE, cp_minimum=COUPON_MINIMUM,
                                       cp_end=today + timedelta(days=30))
        return coupon
