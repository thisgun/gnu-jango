"""The scheduled shop alerts: 가격 인하 알림, automatic 재입고 SMS and 장바구니 알림 메일."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.core.models import Notification
from gnu_jango.shop.cart_reminders import COUPON_SUBJECT, send_due_cart_reminders
from gnu_jango.shop.models import (
    ShopCartReminder,
    ShopCoupon,
    ShopPriceAlert,
    ShopStockNotification,
    ShopStockNotificationSendLog,
)
from gnu_jango.shop.price_alerts import send_due_price_alerts
from gnu_jango.shop.restock import send_due_restock_sms
from gnu_jango.shop.sms.icode import ICodeSendResult
from gnu_jango.testing.factories import MemberFactory, ShopOrderFactory, ShopProductFactory

HOUR = 3600
SEND_MESSAGE = "gnu_jango.shop.sms.service.send_message"
# Reminders go out between 08:00 and 21:00, so the cart tests run at 14:00 local time.
DAYTIME = int(timezone.make_aware(datetime(2026, 10, 30, 14, 0)).timestamp())
NIGHT = int(timezone.make_aware(datetime(2026, 10, 30, 22, 0)).timestamp())


def set_options(**values):
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": str(value)})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def alert_url(product):
    return f"/api/v1/shop/products/{product.it_id}/price-alert"


# 가격 인하 알림


@pytest.fixture
def price_alerts_on(db):
    set_options(de_price_alert_use=1)


def test_asking_for_a_price_alert_needs_a_member(db, price_alerts_on):
    product = ShopProductFactory()
    assert APIClient().post(alert_url(product)).status_code == 401


def test_a_price_alert_cannot_be_asked_for_while_the_shop_has_it_off(db, member):
    product = ShopProductFactory()
    response = client_for(member).post(alert_url(product))
    assert response.status_code == 409
    assert response.json()["code"] == "price_alert_disabled"
    assert not ShopPriceAlert.objects.exists()


def test_a_member_asks_removes_and_lists_their_price_alerts(db, member, price_alerts_on):
    product = ShopProductFactory(it_price=12000)
    other = ShopProductFactory()
    ShopPriceAlert.objects.create(user=MemberFactory(), product=other, pa_price=5000)
    client = client_for(member)

    created = client.post(alert_url(product))
    assert created.status_code == 201
    assert created.json()["data"]["pa_price"] == 12000
    assert client.get(alert_url(product)).json()["data"]["alerted"] is True
    assert client.get(alert_url(other)).json()["data"]["alerted"] is False  # someone else's alert
    assert [row["it_id"] for row in client.get("/api/v1/shop/price-alerts").json()["data"]] == [product.it_id]

    assert client.delete(alert_url(product)).json()["data"]["deleted"] is True
    assert not ShopPriceAlert.objects.filter(user=member).exists()
    assert ShopPriceAlert.objects.count() == 1


def test_a_price_alert_for_a_product_not_on_sale_is_refused(db, member, price_alerts_on):
    product = ShopProductFactory(it_use="0")
    assert client_for(member).post(alert_url(product)).status_code == 404


def test_the_site_settings_tell_pages_whether_price_alerts_are_offered(db):
    assert APIClient().get("/api/v1/settings").json()["data"]["price_alert_enabled"] is False
    set_options(de_price_alert_use=1)
    assert APIClient().get("/api/v1/settings").json()["data"]["price_alert_enabled"] is True


def test_a_cheaper_product_is_told_once_by_mail_and_notification(
    db, member, price_alerts_on, django_capture_on_commit_callbacks
):
    product = ShopProductFactory(it_price=10000)
    client_for(member).post(alert_url(product))
    product.it_price = 8000
    product.save(update_fields=["it_price"])

    with django_capture_on_commit_callbacks(execute=True):
        summary = send_due_price_alerts()

    assert summary == {"due": 1, "notified": 1, "mailed": 1}
    alert = ShopPriceAlert.objects.get(user=member)
    assert alert.notified_price == 8000 and alert.notified_at is not None
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [member.email]
    assert "8,000원" in mail.outbox[0].body
    notification = Notification.objects.get(user=member)
    assert notification.nt_data["href"] == f"/shop/products/{product.it_id}"
    # the next run has nothing left to tell
    assert send_due_price_alerts() == {"due": 0, "notified": 0, "mailed": 0}


def test_asking_again_after_a_notice_waits_for_a_new_drop(db, member, price_alerts_on):
    product = ShopProductFactory(it_price=10000)
    client = client_for(member)
    client.post(alert_url(product))
    product.it_price = 8000
    product.save(update_fields=["it_price"])
    send_due_price_alerts()

    client.post(alert_url(product))
    alert = ShopPriceAlert.objects.get(user=member)
    assert (alert.pa_price, alert.notified_at) == (8000, None)
    assert send_due_price_alerts()["due"] == 0


@pytest.mark.parametrize("change", [
    {"it_price": 10000},  # not cheaper
    {"it_price": 12000},  # dearer
    {"it_price": 8000, "it_soldout": "1"},
    {"it_price": 8000, "it_stock_qty": 0},
    {"it_price": 8000, "it_use": "0"},
])
def test_no_notice_unless_the_product_can_be_bought_for_less(db, member, change):
    product = ShopProductFactory(it_price=10000)
    ShopPriceAlert.objects.create(user=member, product=product, pa_price=10000)
    for name, value in change.items():
        setattr(product, name, value)
    product.save()
    assert send_due_price_alerts()["due"] == 0


def test_a_withdrawn_or_blocked_member_is_not_told(db):
    blocked = MemberFactory(is_active=False)
    left = MemberFactory()
    left.profile.leave_date = timezone.localdate()
    left.profile.save(update_fields=["leave_date"])
    product = ShopProductFactory(it_price=8000)
    for user in (blocked, left):
        ShopPriceAlert.objects.create(user=user, product=product, pa_price=10000)
    assert send_due_price_alerts()["due"] == 0


def test_a_dry_run_counts_without_telling(db, member):
    product = ShopProductFactory(it_price=8000)
    ShopPriceAlert.objects.create(user=member, product=product, pa_price=10000)
    assert send_due_price_alerts(dry_run=True) == {"due": 1, "notified": 0, "mailed": 0}
    assert ShopPriceAlert.objects.get().notified_at is None


# 재입고 SMS (automatic)


@pytest.fixture
def sms_ready(db):
    from gnu_jango.shop.models import ShopShippingPolicy

    set_options(cf_sms_use="icode")
    ShopShippingPolicy.objects.update_or_create(
        pk=1, defaults={"de_admin_company_name": "Demo Shop", "de_admin_company_tel": "02-123-4567"}
    )


def subscription(product, hp="010-1234-5678"):
    return ShopStockNotification.objects.create(product=product, it_id=product.it_id, ss_hp=hp)


def test_an_untried_subscription_of_a_product_back_in_stock_gets_its_sms(db, sms_ready):
    notification = subscription(ShopProductFactory(it_stock_sms="1", it_stock_qty=3))
    with patch(SEND_MESSAGE, return_value=ICodeSendResult("accepted")) as send:
        counts = send_due_restock_sms()
    assert counts["accepted"] == 1
    send.assert_called_once()
    notification.refresh_from_db()
    assert notification.ss_send is True
    assert ShopStockNotificationSendLog.objects.get().status == "accepted"


def test_the_automatic_send_never_retries_or_sends_out_of_stock(db, sms_ready):
    tried = subscription(ShopProductFactory(it_stock_sms="1"))
    ShopStockNotificationSendLog.objects.create(notification=tried, product_it_id=tried.it_id, status="rejected")
    subscription(ShopProductFactory(it_stock_sms="1", it_stock_qty=0))
    subscription(ShopProductFactory(it_stock_sms="1", it_soldout="1"))
    subscription(ShopProductFactory(it_stock_sms="0"))
    with patch(SEND_MESSAGE) as send:
        assert send_due_restock_sms()["due"] == 0
    send.assert_not_called()


def test_the_automatic_send_waits_for_the_sms_settings(db):
    subscription(ShopProductFactory(it_stock_sms="1"))
    with patch(SEND_MESSAGE) as send:
        counts = send_due_restock_sms()
    assert counts["reason"] == "sms_not_configured"
    send.assert_not_called()
    assert not ShopStockNotificationSendLog.objects.exists()


# 장바구니 알림 메일


@pytest.fixture(autouse=True)
def at_daytime():
    with patch("gnu_jango.shop.cart_reminders.cart_now", return_value=DAYTIME):
        yield


@pytest.fixture
def reminders_on(db):
    set_options(de_cart_reminder_use=1, de_cart_reminder_hours=24)


def agreeing_member(**kwargs):
    member = MemberFactory(**kwargs)
    member.profile.mailing = True
    member.profile.mailing_date = timezone.now()
    member.profile.save(update_fields=["mailing", "mailing_date"])
    return member


def put_in_cart(member, product, *, hours_ago, **row):
    lines = [{
        "ct_id": "100000000001", "it_id": product.it_id, "it_name": product.it_name, "ct_price": product.it_price,
        "ct_qty": 2, "ct_option": "", "io_type": 0, "io_price": 0, "ct_time": DAYTIME - hours_ago * HOUR, **row,
    }]
    Config.objects.update_or_create(name=auth_cart_config_name(member), defaults={"value": json.dumps(lines)})


def test_a_cart_left_for_the_waiting_time_is_reminded_once_as_advertising(db, reminders_on):
    member = agreeing_member()
    product = ShopProductFactory()
    put_in_cart(member, product, hours_ago=30)

    assert send_due_cart_reminders() == {"due": 1, "sent": 1, "coupons": 0}
    message = mail.outbox[0]
    assert message.subject.startswith("(광고) ")
    assert product.it_name in message.body and "정보 메일 수신" in message.body
    assert ShopCartReminder.objects.get(user=member).sent is True
    # the same cart is not reminded again
    assert send_due_cart_reminders()["due"] == 0


def test_a_reminder_can_bring_one_coupon_at_a_time(db, reminders_on):
    set_options(de_cart_reminder_coupon_price=3000, de_cart_reminder_coupon_minimum=20000)
    member = agreeing_member()
    put_in_cart(member, ShopProductFactory(), hours_ago=30)

    assert send_due_cart_reminders()["coupons"] == 1
    coupon = ShopCoupon.objects.get(user=member, cp_subject=COUPON_SUBJECT)
    assert (coupon.cp_price, coupon.cp_minimum) == (3000, 20000)
    assert "3,000원" in mail.outbox[0].body

    # a week later, another forgotten cart: no second coupon while the first is unused
    ShopCartReminder.objects.update(created_at=timezone.now() - timedelta(days=8))
    put_in_cart(member, ShopProductFactory(), hours_ago=25)
    assert send_due_cart_reminders() == {"due": 1, "sent": 1, "coupons": 0}


@pytest.mark.parametrize("case", ["no_consent", "recent_cart", "ordered_since", "buy_now_line", "left", "inactive"])
def test_no_reminder_for(db, reminders_on, case):
    member = MemberFactory() if case == "no_consent" else agreeing_member(is_active=case != "inactive")
    if case == "left":
        member.profile.leave_date = timezone.localdate()
        member.profile.save(update_fields=["leave_date"])
    product = ShopProductFactory()
    put_in_cart(
        member, product,
        hours_ago=2 if case == "recent_cart" else 30,
        ct_direct=1 if case == "buy_now_line" else 0,
    )
    if case == "ordered_since":
        ShopOrderFactory(user=member)
    assert send_due_cart_reminders()["due"] == 0
    assert not mail.outbox


def test_at_most_one_reminder_a_week(db, reminders_on):
    member = agreeing_member()
    put_in_cart(member, ShopProductFactory(), hours_ago=30)
    send_due_cart_reminders()
    put_in_cart(member, ShopProductFactory(), hours_ago=25)  # a new cart the next day
    assert send_due_cart_reminders()["due"] == 0


def test_no_reminder_at_night(db, reminders_on):
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30)
    with patch("gnu_jango.shop.cart_reminders.cart_now", return_value=NIGHT):
        assert send_due_cart_reminders()["reason"] == "night"
    assert not mail.outbox and not ShopCartReminder.objects.exists()


def test_no_reminder_to_an_address_that_was_never_certified(db, reminders_on):
    member = agreeing_member()
    member.profile.email_certify = None
    member.profile.save(update_fields=["email_certify"])
    put_in_cart(member, ShopProductFactory(), hours_ago=30)
    assert send_due_cart_reminders()["due"] == 0


def test_a_reminder_that_could_not_be_mailed_is_undone_and_tried_again(db, reminders_on):
    set_options(de_cart_reminder_coupon_price=3000)
    member = agreeing_member()
    put_in_cart(member, ShopProductFactory(), hours_ago=30)
    with patch("gnu_jango.shop.notifications.send_shop_mail", return_value=False):
        assert send_due_cart_reminders() == {"due": 1, "sent": 0, "coupons": 0}
    assert not ShopCartReminder.objects.exists()
    assert not ShopCoupon.objects.filter(user=member).exists()

    assert send_due_cart_reminders() == {"due": 1, "sent": 1, "coupons": 1}


def test_a_broken_cart_line_does_not_stop_the_run(db, reminders_on):
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30, ct_qty="many")
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30)
    with patch("gnu_jango.shop.cart_reminders._send_mail", side_effect=[RuntimeError("boom"), True]):
        assert send_due_cart_reminders()["sent"] == 1


def test_no_cart_reminders_while_mail_is_off(db, reminders_on):
    set_options(cf_email_use=0)
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30)
    assert send_due_cart_reminders()["reason"] == "mail_disabled"
    assert not ShopCartReminder.objects.exists()


def test_no_cart_reminders_while_the_shop_has_them_off(db):
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30)
    assert send_due_cart_reminders() == {"due": 0, "sent": 0, "coupons": 0}


# the scheduled command


def run_alerts(*args):
    from io import StringIO

    out = StringIO()
    call_command("send_shop_alerts", "--json", *args, stdout=out)
    return json.loads(out.getvalue())


def test_the_command_does_nothing_until_a_kind_is_turned_on(db):
    assert run_alerts("--apply") == {
        "dry_run": False, "price_alerts": None, "restock_sms": None, "cart_reminders": None,
    }


def test_the_command_dry_run_counts_every_kind_that_is_on(db, member):
    set_options(de_price_alert_use=1, de_stock_sms_auto=1, de_cart_reminder_use=1)
    ShopPriceAlert.objects.create(user=member, product=ShopProductFactory(it_price=8000), pa_price=10000)
    subscription(ShopProductFactory(it_stock_sms="1"))
    put_in_cart(agreeing_member(), ShopProductFactory(), hours_ago=30)

    summary = run_alerts()
    assert summary["dry_run"] is True
    assert (summary["price_alerts"]["due"], summary["restock_sms"]["due"], summary["cart_reminders"]["due"]) == (1, 1, 1)
    assert not mail.outbox and not ShopCartReminder.objects.exists()
