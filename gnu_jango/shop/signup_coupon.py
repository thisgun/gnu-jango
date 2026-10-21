"""youngcart 신규회원 쿠폰: an order coupon for a member who just signed up
(bbs/register_form_update.php, de_member_reg_coupon_*)."""

import logging

from django.db import transaction
from django.utils import timezone

from gnu_jango.shop.coupon_dates import coupon_end_date
from gnu_jango.shop.models import ShopCoupon
from gnu_jango.shop.shop_options import shop_options

logger = logging.getLogger(__name__)

SIGNUP_COUPON_SUBJECT = "신규 회원가입 축하 쿠폰"
COUPON_METHOD_ORDER = 2  # a discount on the whole order
COUPON_TYPE_AMOUNT = 0  # a fixed amount, not a percentage


def issue_signup_coupon(user):
    """Give ``user`` the new-member coupon when the shop offers one; returns it or None.

    Runs in its own savepoint: a failure is logged and never stops the signup."""
    try:
        with transaction.atomic():
            options = shop_options(
                "de_member_reg_coupon_use",
                "de_member_reg_coupon_price",
                "de_member_reg_coupon_minimum",
                "de_member_reg_coupon_term",
            )
            price = int(options["de_member_reg_coupon_price"] or 0)
            term = int(options["de_member_reg_coupon_term"] or 0)
            if not options["de_member_reg_coupon_use"] or price <= 0 or term <= 0:
                return None
            today = timezone.localdate()
            return ShopCoupon.objects.create(
                user=user,
                cp_subject=SIGNUP_COUPON_SUBJECT,
                cp_method=COUPON_METHOD_ORDER,
                cp_target="",
                cp_type=COUPON_TYPE_AMOUNT,
                cp_price=price,
                cp_trunc=1,
                cp_minimum=max(0, int(options["de_member_reg_coupon_minimum"] or 0)),
                cp_maximum=0,
                cp_start=today,
                # valid from today through the term-th day, like a coupon zone's period
                cp_end=coupon_end_date(today, term),
            )
    except Exception:  # noqa: BLE001 - the coupon is a bonus; the signup must go through
        logger.exception("Could not issue the new-member coupon for user %s", getattr(user, "pk", None))
        return None
