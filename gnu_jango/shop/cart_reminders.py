"""장바구니 알림 메일: a member who put products in the cart and did not order them hears about it once,
optionally with a coupon. It is advertising mail (정보통신망법 제50조), so it only goes to members who
agreed to information mail (Profile.mailing) at a certified address, only between 08:00 and 21:00 (night
advertising needs a consent of its own, 제50조 제3항), its subject starts with (광고), and it says how to stop it.

A member cart is one Config row (gnu_jango/api/shop_cart.py) whose lines carry ct_time; the newest
ct_time identifies "this cart", so a reminder row per (member, newest ct_time) keeps each cart to one mail.
"""

import json
import logging
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from gnu_jango.api.shop_cart_keep import CART_TIME_KEY, cart_now, prune_cart_rows
from gnu_jango.api.shop_common import AUTH_CART_CONFIG_PREFIX
from gnu_jango.config.models import Config
from gnu_jango.shop.coupon_dates import coupon_end_date
from gnu_jango.shop.models import ShopCartReminder, ShopCoupon, ShopOrder
from gnu_jango.shop.shop_options import shop_options

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT = 100
# Local hours (TIME_ZONE) in which reminders go out: from 08:00 up to, not including, 21:00.
SENDING_HOURS = range(8, 21)
# A member gets at most one cart reminder in this many days, however often the cart changes.
REMIND_AT_MOST_EVERY = timedelta(days=7)
COUPON_SUBJECT = "장바구니 알림 쿠폰"
COUPON_METHOD_ORDER = 2  # a discount on the whole order
COUPON_TYPE_AMOUNT = 0  # a fixed amount


def reminder_options():
    options = shop_options(
        "de_cart_reminder_use",
        "de_cart_reminder_hours",
        "de_cart_reminder_coupon_price",
        "de_cart_reminder_coupon_minimum",
        "de_cart_reminder_coupon_term",
        "de_cart_keep_term",
    )
    return {
        "enabled": bool(options["de_cart_reminder_use"]),
        "wait_seconds": max(1, int(options["de_cart_reminder_hours"] or 24)) * 3600,
        "coupon_price": max(0, int(options["de_cart_reminder_coupon_price"] or 0)),
        "coupon_minimum": max(0, int(options["de_cart_reminder_coupon_minimum"] or 0)),
        "coupon_term": max(1, int(options["de_cart_reminder_coupon_term"] or 7)),
        "keep_term": max(1, int(options["de_cart_keep_term"] or 15)),
    }


def _cart_lines(value, keep_term, now):
    """The lines a reminder is about: kept (not past de_cart_keep_term) and not a 바로구매 line."""
    try:
        rows = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    kept, _ = prune_cart_rows(rows, keep_term, now=now)
    return [row for row in kept if not row.get("ct_direct")]


def _reachable_member_ids(now_dt):
    """Members a reminder may go to: active, not left, agreed to information mail at a certified
    address, and not reminded in the last REMIND_AT_MOST_EVERY. One query for all of them."""
    reminded = ShopCartReminder.objects.filter(created_at__gte=now_dt - REMIND_AT_MOST_EVERY).values("user_id")
    return set(
        get_user_model().objects.filter(
            is_active=True,
            profile__mailing=True,
            profile__email_certify__isnull=False,
            profile__leave_date__isnull=True,
        )
        .exclude(email="")
        .exclude(pk__in=reminded)
        .values_list("pk", flat=True)
    )


def _waiting_carts(options, now, member_ids):
    """(user id, lines, newest ct_time) of the given members' carts left alone for the waiting time."""
    cutoff = now - options["wait_seconds"]
    names = [f"{AUTH_CART_CONFIG_PREFIX}{member_id}"[:50] for member_id in sorted(member_ids)]
    for start in range(0, len(names), 500):
        rows = Config.objects.filter(name__in=names[start:start + 500]).values_list("name", "value")
        for name, value in rows:
            lines = _cart_lines(value, options["keep_term"], now)
            if not lines:
                continue
            newest = max(int(line[CART_TIME_KEY]) for line in lines)
            if newest <= cutoff:
                yield int(name[len(AUTH_CART_CONFIG_PREFIX):]), lines, newest


def due_reminders(options=None, *, now=None):
    """(user, lines, newest ct_time) of the members who are due a reminder, without changing data."""
    options = options or reminder_options()
    now = cart_now() if now is None else now
    zone = timezone.get_current_timezone()
    now_dt = datetime.fromtimestamp(now, tz=zone)
    users = get_user_model().objects.select_related("profile")
    for user_id, lines, newest in _waiting_carts(options, now, _reachable_member_ids(now_dt)):
        if ShopCartReminder.objects.filter(user_id=user_id, cart_time=newest).exists():
            continue
        if ShopOrder.objects.filter(user_id=user_id, od_datetime__gte=datetime.fromtimestamp(newest, tz=zone)).exists():
            continue  # ordered since: the cart is what is left over, not forgotten
        user = users.filter(pk=user_id).first()
        if user is not None:
            yield user, lines, newest


def _open_reminder_coupon(user):
    """The member's reminder coupon that can still be used, if any."""
    today = timezone.localdate()
    return ShopCoupon.objects.filter(
        user=user, cp_subject=COUPON_SUBJECT, cp_used="", cp_start__lte=today, cp_end__gte=today,
    ).first()


def _issue_coupon(user, options):
    if options["coupon_price"] <= 0 or _open_reminder_coupon(user):
        return None
    today = timezone.localdate()
    return ShopCoupon.objects.create(
        user=user,
        cp_subject=COUPON_SUBJECT,
        cp_method=COUPON_METHOD_ORDER,
        cp_target="",
        cp_type=COUPON_TYPE_AMOUNT,
        cp_price=options["coupon_price"],
        cp_trunc=1,
        cp_minimum=options["coupon_minimum"],
        cp_maximum=0,
        cp_start=today,
        cp_end=coupon_end_date(today, options["coupon_term"]),
    )


def _record(user, lines, newest, options):
    """The reminder row (and its coupon) for one cart, or None when another run recorded it first."""
    try:
        with transaction.atomic():
            reminder = ShopCartReminder.objects.create(user=user, cart_time=newest, line_count=len(lines))
            coupon = _issue_coupon(user, options)
            if coupon is not None:
                reminder.coupon = coupon
                reminder.save(update_fields=["coupon"])
    except IntegrityError:
        return None
    return reminder


def _mail_lines(lines):
    return [
        {
            "it_name": str(line.get("it_name") or line.get("it_id") or ""),
            "option": str(line.get("ct_option") or "") if line.get("ct_option") != line.get("it_name") else "",
            "qty": max(1, int(line["ct_qty"])) if str(line.get("ct_qty", "")).isdigit() else 1,
        }
        for line in lines
    ]


def _send_mail(user, lines, coupon):
    from gnu_jango.shop.notifications import send_shop_mail, site_link, site_title

    profile = user.profile
    context = {
        "member_name": profile.nickname or profile.realname or user.get_username(),
        "lines": _mail_lines(lines),
        "coupon": coupon,
        "cart_url": site_link("/shop/cart"),
        "profile_url": site_link("/mypage/profile"),
        "agreed_on": timezone.localtime(profile.mailing_date).strftime("%Y-%m-%d") if profile.mailing_date else "",
    }
    return send_shop_mail(
        f"(광고) [{site_title()}] 장바구니에 담아 두신 상품이 기다리고 있어요",
        "cart_reminder",
        context,
        [user.email],
    )


def _forget(reminder):
    """Undo a reminder whose mail did not go out, so the cart is tried again on a later run."""
    with transaction.atomic():
        if reminder.coupon_id:
            ShopCoupon.objects.filter(pk=reminder.coupon_id, cp_used="").delete()
        ShopCartReminder.objects.filter(pk=reminder.pk).delete()


def send_due_cart_reminders(*, dry_run=False, limit=DEFAULT_BATCH_LIMIT, now=None):
    from gnu_jango.shop.notifications import mail_enabled

    options = reminder_options()
    summary = {"due": 0, "sent": 0, "coupons": 0}
    if not options["enabled"]:
        return summary
    now = cart_now() if now is None else now
    if datetime.fromtimestamp(now, tz=timezone.get_current_timezone()).hour not in SENDING_HOURS:
        return {**summary, "reason": "night"}
    if not dry_run and not mail_enabled():
        return {**summary, "reason": "mail_disabled"}
    for user, lines, newest in due_reminders(options, now=now):
        if summary["due"] >= limit:
            break
        summary["due"] += 1
        if dry_run:
            continue
        reminder = _record(user, lines, newest, options)
        if reminder is None:
            continue
        try:
            sent = _send_mail(user, lines, reminder.coupon)
        except Exception:  # noqa: BLE001 - one broken cart must not stop the other reminders
            logger.exception("Cart reminder for member %s could not be sent", user.pk)
            sent = False
        if not sent:
            _forget(reminder)
            continue
        ShopCartReminder.objects.filter(pk=reminder.pk).update(sent=True)
        summary["sent"] += 1
        summary["coupons"] += 1 if reminder.coupon_id else 0
    return summary
