"""주문 알림: order hooks -> queued notices -> Discord/Slack/Telegram requests, retries and the admin."""

import json
from datetime import timedelta
from http import client as http_client
from urllib import error as urllib_error

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

from gnu_jango.plugins import hooks, state
from gnu_jango.testing.factories import AdminFactory, ShopOrderFactory, ShopProductFactory

from . import channels, messages, services
from .models import OrderNotice

pytestmark = pytest.mark.django_db

DISCORD_URL = "https://discord.com/api/webhooks/123/abc-token"
SLACK_URL = "https://hooks.slack.com/services/T000/B000/xyz"
TELEGRAM_TOKEN = "123456789:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll"
DISCORD_ONLY = {"ORDER_NOTIFY_DISCORD_WEBHOOK_URL": DISCORD_URL}
ALL_CHANNELS = {
    "ORDER_NOTIFY_DISCORD_WEBHOOK_URL": DISCORD_URL,
    "ORDER_NOTIFY_SLACK_WEBHOOK_URL": SLACK_URL,
    "ORDER_NOTIFY_TELEGRAM_BOT_TOKEN": TELEGRAM_TOKEN,
    "ORDER_NOTIFY_TELEGRAM_CHAT_ID": "-1001234567890",
}


@pytest.fixture
def sent(monkeypatch):
    """The requests the plugin made, as (url, payload); nothing leaves the test."""
    requests = []

    def fake_open(request):
        requests.append((request.full_url, json.loads(request.data)))

    monkeypatch.setattr(channels, "_open", fake_open)
    return requests


@pytest.fixture
def order():
    product = ShopProductFactory(it_name="유기농 사과 5kg", it_price=39000)
    return ShopOrderFactory(od_name="홍길동", od_settle_case="신용카드", items=[(product, 1)])


def emit(django_capture_on_commit_callbacks, name, **payload):
    with django_capture_on_commit_callbacks(execute=True):
        hooks.emit(name, **payload)


@override_settings(**ALL_CHANNELS)
def test_a_new_order_is_posted_to_every_configured_channel(order, sent, django_capture_on_commit_callbacks):
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    urls = [url for url, _payload in sent]
    assert urls[0] == DISCORD_URL and urls[1] == SLACK_URL
    assert urls[2] == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    discord = sent[0][1]
    assert discord["allowed_mentions"] == {"parse": []}
    text = discord["content"]
    assert text.startswith(f"🛒 새 주문 · {order.od_id}")
    assert "39,000원 · 신용카드 · 홍*동" in text
    assert "유기농 사과 5kg" in text
    assert sent[2][1]["chat_id"] == "-1001234567890" and "parse_mode" not in sent[2][1]
    assert set(OrderNotice.objects.values_list("status", flat=True)) == {OrderNotice.SENT}


@override_settings(ORDER_NOTIFY_SLACK_WEBHOOK_URL=SLACK_URL)
def test_slack_text_is_escaped(sent):
    channels.send("slack", "a <b> & c")

    assert sent[0][1]["text"] == "a &lt;b&gt; &amp; c"


@override_settings(ORDER_NOTIFY_FULL_NAME=True, **DISCORD_ONLY)
def test_a_customer_typed_name_cannot_forge_lines_links_or_markup(sent, django_capture_on_commit_callbacks):
    order = ShopOrderFactory(od_name="홍길동\n💳 결제 완료 · 999 [무료](https://phish.example) <@&1> **굵게**")

    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    lines = sent[0][1]["content"].split("\n")
    assert lines[0].startswith("🛒 새 주문") and not any(line.startswith("💳") for line in lines)
    assert not any(char in lines[1] for char in "[]()<>*@")


def test_without_a_configured_channel_nothing_is_saved(order, sent, django_capture_on_commit_callbacks):
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    assert not OrderNotice.objects.exists()
    assert sent == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/api/webhooks/1/x",
        "http://discord.com/api/webhooks/1/x",
        "https://discord.com:8443/api/webhooks/1/x",
        "https://discord.com/other/1/x",
        "https://user@discord.com/api/webhooks/1/x",
    ],
)
def test_a_discord_value_for_another_address_is_ignored(url):
    with override_settings(ORDER_NOTIFY_DISCORD_WEBHOOK_URL=url):
        assert channels.configured() == ()
        assert channels.misconfigured() == ("discord",)


@override_settings(ORDER_NOTIFY_TELEGRAM_BOT_TOKEN=TELEGRAM_TOKEN, ORDER_NOTIFY_TELEGRAM_CHAT_ID="")
def test_telegram_needs_both_the_token_and_the_chat():
    assert channels.configured() == ()
    assert channels.misconfigured() == ("telegram",)


@override_settings(**DISCORD_ONLY)
def test_a_repeated_hook_posts_once(order, sent, django_capture_on_commit_callbacks):
    emit(django_capture_on_commit_callbacks, "shop.order.paid", order=order, source="payment")
    emit(django_capture_on_commit_callbacks, "shop.order.paid", order=order, source="payment")

    assert len(sent) == 1
    assert OrderNotice.objects.get().event == "paid"


@override_settings(**DISCORD_ONLY)
def test_a_send_that_times_out_stays_pending_and_the_retry_job_sends_it(
    order, monkeypatch, django_capture_on_commit_callbacks
):
    def timeout(request):
        raise urllib_error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(channels, "_open", timeout)
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)
    notice = OrderNotice.objects.get()
    assert (notice.status, notice.attempts) == (OrderNotice.PENDING, 1)
    assert "timed out" in notice.last_error

    calls = []
    monkeypatch.setattr(channels, "_open", calls.append)
    report = services.retry(apply=True, now=notice.created_at + timedelta(minutes=2))

    notice.refresh_from_db()
    assert report["sent"] == 1 and len(calls) == 1
    assert (notice.status, notice.attempts, notice.last_error) == (OrderNotice.SENT, 2, "")


@override_settings(**DISCORD_ONLY)
def test_after_a_channel_fails_request_time_sends_leave_it_to_the_job(
    order, monkeypatch, django_capture_on_commit_callbacks
):
    calls = []

    def timeout(request):
        calls.append(request)
        raise urllib_error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(channels, "_open", timeout)
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)
    other = ShopOrderFactory()
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=other)

    assert len(calls) == 1  # the second order did not wait for the dead channel
    assert OrderNotice.objects.get(od_id=other.pk).status == OrderNotice.PENDING

    monkeypatch.setattr(channels, "_open", calls.append)
    report = services.retry(apply=True, now=timezone.now() + timedelta(minutes=2))
    assert report["sent"] == 2


@override_settings(**DISCORD_ONLY)
def test_a_cut_off_answer_is_retried_like_a_timeout(order, monkeypatch, django_capture_on_commit_callbacks):
    def cut_off(request):
        raise http_client.IncompleteRead(b"")

    monkeypatch.setattr(channels, "_open", cut_off)
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    notice = OrderNotice.objects.get()
    assert (notice.status, notice.attempts) == (OrderNotice.PENDING, 1)
    assert notice.last_error.startswith("IncompleteRead")


@override_settings(**DISCORD_ONLY)
def test_a_notice_another_sender_holds_is_not_posted_again(order, sent):
    notice = OrderNotice.objects.create(od_id=order.pk, event="placed", key="placed", channel="discord", text="x")
    assert services._claim(notice)  # e.g. the request is posting it right now

    assert services.send_pending([notice.pk]) == {"sent": 0, "failed": 0, "skipped": 0}
    assert services.send_notice(notice) == services.SKIPPED
    assert sent == []


@override_settings(**DISCORD_ONLY)
def test_the_retry_job_releases_a_claim_left_by_a_crashed_worker(order, sent):
    now = timezone.now()
    notice = OrderNotice.objects.create(
        od_id=order.pk, event="placed", key="placed", channel="discord", text="x",
        status=OrderNotice.SENDING,
    )
    OrderNotice.objects.filter(pk=notice.pk).update(
        created_at=now - timedelta(minutes=30), claimed_at=now - services.LEASE - timedelta(minutes=1)
    )

    report = services.retry(apply=True, now=now)

    notice.refresh_from_db()
    assert (report["released"], report["sent"], notice.status) == (1, 1, OrderNotice.SENT)


@override_settings(**DISCORD_ONLY)
def test_the_retry_job_sends_at_most_one_batch_oldest_first(order, sent, monkeypatch):
    monkeypatch.setattr(services, "RETRY_BATCH", 2)
    now = timezone.now()
    for minutes, key in ((5, "a"), (30, "b"), (10, "c")):
        notice = OrderNotice.objects.create(od_id=order.pk, event="status", key=key, channel="discord", text=key)
        OrderNotice.objects.filter(pk=notice.pk).update(created_at=now - timedelta(minutes=minutes))

    report = services.retry(apply=True, now=now)

    assert (report["due"], report["sent"]) == (3, 2)
    assert [payload["content"] for _url, payload in sent] == ["b", "c"]


@override_settings(**DISCORD_ONLY)
def test_the_retry_job_leaves_fresh_notices_to_the_request_that_wrote_them(order):
    OrderNotice.objects.create(od_id=order.pk, event="placed", key="placed", channel="discord", text="x")

    assert services.retry(apply=False)["due"] == 0


@override_settings(**DISCORD_ONLY)
def test_a_revoked_webhook_is_not_retried_and_the_error_has_no_secret(
    order, monkeypatch, django_capture_on_commit_callbacks
):
    def not_found(request):
        raise urllib_error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(channels, "_open", not_found)
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    notice = OrderNotice.objects.get()
    assert (notice.status, notice.last_error) == (OrderNotice.FAILED, "HTTP 404")
    assert "abc-token" not in notice.last_error


@override_settings(**DISCORD_ONLY)
def test_a_notice_is_given_up_after_the_last_attempt_or_after_a_day(order, monkeypatch):
    def unavailable(request):
        raise urllib_error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    monkeypatch.setattr(channels, "_open", unavailable)
    last_try = OrderNotice.objects.create(
        od_id=order.pk, event="placed", key="placed", channel="discord", text="x",
        attempts=services.MAX_ATTEMPTS - 1,
    )
    old = OrderNotice.objects.create(od_id=order.pk, event="paid", key="paid", channel="discord", text="x")
    now = timezone.now()
    OrderNotice.objects.filter(pk=last_try.pk).update(created_at=now - timedelta(minutes=5))
    OrderNotice.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=2))

    report = services.retry(apply=True, now=now)

    assert (report["due"], report["expired"], report["failed"]) == (1, 1, 1)
    assert set(OrderNotice.objects.values_list("status", flat=True)) == {OrderNotice.FAILED}


@override_settings(**DISCORD_ONLY)
def test_cancellations_and_other_status_changes_follow_the_settings(order, sent, django_capture_on_commit_callbacks):
    def change(old, new, source):
        emit(
            django_capture_on_commit_callbacks, "shop.order.status_changed",
            order=order, old_status=old, new_status=new, source=source,
        )

    change("입금", "취소", "cancel")
    change("준비", "배송", "admin")
    change("주문", "입금", "payment")
    with override_settings(ORDER_NOTIFY_OTHER_STATUS=True):
        change("배송", "완료", "admin")
    with override_settings(ORDER_NOTIFY_CANCELLED=False):
        change("주문", "반품", "cancel")

    assert list(OrderNotice.objects.order_by("pk").values_list("event", "key")) == [
        ("cancelled", "cancelled:입금>취소"),
        ("status", "status:배송>완료"),
    ]
    assert "입금 → 취소" in sent[0][1]["content"]


@override_settings(**DISCORD_ONLY)
def test_an_admin_marking_a_bank_order_paid_sends_one_paid_message(sent, django_capture_on_commit_callbacks):
    from gnu_jango.shop.order_flow import move_order_status

    order = ShopOrderFactory(items=[(ShopProductFactory(), 1)])  # 무통장: only these are marked paid by hand
    with django_capture_on_commit_callbacks(execute=True):
        assert move_order_status(order, "입금", send_sms=False).ok

    assert list(OrderNotice.objects.values_list("event", flat=True)) == ["paid"]
    assert sent[0][1]["content"].startswith(f"💳 결제 완료 · {order.od_id}")


@override_settings(ORDER_NOTIFY_PLACED=False, **DISCORD_ONLY)
def test_an_event_switched_off_sends_nothing(order, sent, django_capture_on_commit_callbacks):
    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    assert sent == []


@override_settings(**DISCORD_ONLY)
def test_switching_the_plugin_off_in_the_admin_stops_the_messages(order, sent, django_capture_on_commit_callbacks):
    state.set_enabled("order_notify", False)

    emit(django_capture_on_commit_callbacks, "shop.order.placed", order=order)

    assert sent == []


@pytest.mark.parametrize(
    ("name", "masked"), [("홍길동", "홍*동"), ("남궁민수", "남**수"), ("김철", "김*"), ("A", "*"), ("", "")]
)
def test_the_buyer_name_is_masked(name, masked):
    assert messages.mask_name(name) == masked


@override_settings(**ALL_CHANNELS)
def test_the_test_command_sends_to_every_channel(sent, capsys):
    call_command("order_notify_test")

    assert [payload.get("content") or payload.get("text") for _url, payload in sent] == [messages.TEST_TEXT] * 3
    assert not OrderNotice.objects.exists()


def test_the_test_command_fails_without_a_channel():
    with pytest.raises(CommandError):
        call_command("order_notify_test")


@override_settings(**DISCORD_ONLY)
def test_the_admin_lists_notices_and_sends_failed_ones_again(client, order, sent):
    failed = OrderNotice.objects.create(
        od_id=order.pk, event="placed", key="placed", channel="discord", text="다시", status=OrderNotice.FAILED
    )
    done = OrderNotice.objects.create(
        od_id=order.pk, event="paid", key="paid", channel="discord", text="끝", status=OrderNotice.SENT
    )
    client.force_login(AdminFactory())
    url = "/admin/order_notify/ordernotice/"

    assert client.get(url).status_code == 200
    assert client.get(f"{url}{failed.pk}/change/").status_code == 200
    response = client.post(url, {"action": "send_again", "_selected_action": [failed.pk, done.pk]})

    assert response.status_code == 302
    failed.refresh_from_db()
    assert failed.status == OrderNotice.SENT
    assert [payload["content"] for _url, payload in sent] == ["다시"]


@override_settings(**DISCORD_ONLY)
def test_the_admin_action_refuses_more_than_its_limit(client, order, sent, monkeypatch):
    from . import admin as notice_admin

    monkeypatch.setattr(notice_admin, "ADMIN_SEND_LIMIT", 1)
    ids = [
        OrderNotice.objects.create(
            od_id=order.pk, event="status", key=key, channel="discord", text=key, status=OrderNotice.FAILED
        ).pk
        for key in ("a", "b")
    ]
    client.force_login(AdminFactory())

    client.post("/admin/order_notify/ordernotice/", {"action": "send_again", "_selected_action": ids})

    assert sent == []
    assert set(OrderNotice.objects.values_list("status", flat=True)) == {OrderNotice.FAILED}


def test_a_staff_member_without_the_change_permission_cannot_send_again(client, order, sent):
    from gnu_jango.testing.factories import MemberFactory

    notice = OrderNotice.objects.create(
        od_id=order.pk, event="placed", key="placed", channel="discord", text="x", status=OrderNotice.FAILED
    )
    client.force_login(MemberFactory(is_staff=True))

    response = client.post("/admin/order_notify/ordernotice/", {"action": "send_again", "_selected_action": [notice.pk]})

    assert response.status_code == 403
    notice.refresh_from_db()
    assert notice.status == OrderNotice.FAILED
