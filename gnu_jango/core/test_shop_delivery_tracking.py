"""Shipment tracking through Delivery Tracker (shop/delivery_tracking.py and its client).

The client module is the only network path; every test here mocks it (or its opener), so no
test reaches tracker.delivery."""

import importlib
import io
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib import error as urllib_error

import pytest
from django.contrib.admin.models import LogEntry
from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from gnu_jango.config.models import Config
from gnu_jango.core import scheduled_jobs
from gnu_jango.core.contract_testing import response_validator
from gnu_jango.shop import delivery_tracker_client as client
from gnu_jango.shop import delivery_tracking
from gnu_jango.shop.delivery import DELIVERY_COMPANIES, DELIVERY_TRACKER_CARRIERS, tracker_carrier_id
from gnu_jango.shop.delivery_tracking_settings import (
    KEY_ROWS,
    seal_key,
    tracking_config,
    webhook_callback_url,
    webhook_token,
)
from gnu_jango.shop.models import ShopShipmentTracking
from gnu_jango.testing.factories import ShopOrderFactory, ShopProductFactory

CLIENT_ID = "dt-client-id-ab12"
CLIENT_SECRET = "dt-client-secret-9876zyx"
TRACK = "gnu_jango.shop.delivery_tracker_client.track"
REGISTER = "gnu_jango.shop.delivery_tracker_client.register_webhook"
OPEN = "gnu_jango.shop.delivery_tracker_client._OPENER.open"

# A track answer in the shape of the documented schema (TrackInfo / TrackEventConnection).
RECORDED_TRACK = {
    "data": {
        "track": {
            "lastEvent": {
                "time": "2026-10-29T14:05:00+09:00",
                "status": {"code": "DELIVERED", "name": "배달완료"},
                "location": {"name": "서울강남"},
                "description": "고객님의 상품이 배달완료 되었습니다.",
            },
            "events": {
                "edges": [
                    {"node": {"time": "2026-10-28T09:00:00+09:00", "status": {"code": "AT_PICKUP", "name": "집화처리"},
                              "location": {"name": "대전HUB"}, "description": "상품을 인수했습니다."}},
                    {"node": {"time": "2026-10-29T08:30:00+09:00", "status": {"code": "OUT_FOR_DELIVERY", "name": "배송출발"},
                              "location": {"name": "서울강남"}, "description": "배송을 시작합니다."}},
                    {"node": {"time": "2026-10-29T14:05:00+09:00", "status": {"code": "DELIVERED", "name": "배달완료"},
                              "location": {"name": "서울강남"}, "description": "고객님의 상품이 배달완료 되었습니다."}},
                ]
            },
        }
    }
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def answer(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def in_transit_info():
    return client.parse_track_info(
        {
            "track": {
                "lastEvent": {"time": "2026-10-29T08:30:00+09:00", "status": {"code": "IN_TRANSIT", "name": "간선상차"},
                              "location": {"name": "대전HUB"}, "description": "이동 중"},
                "events": {"edges": [{"node": {"time": "2026-10-29T08:30:00+09:00",
                                               "status": {"code": "IN_TRANSIT", "name": "간선상차"},
                                               "location": {"name": "대전HUB"}, "description": "이동 중"}}]},
            }
        }
    )


def delivered_info():
    return client.parse_track_info(RECORDED_TRACK["data"])


def enable_tracking(*, complete=False, keys=True):
    Config.objects.update_or_create(name="de_tracking_use", defaults={"value": "1"})
    Config.objects.update_or_create(name="de_tracking_complete_delivered", defaults={"value": "1" if complete else "0"})
    if keys:
        Config.objects.update_or_create(name=KEY_ROWS["client_id"], defaults={"value": seal_key("client_id", CLIENT_ID)})
        Config.objects.update_or_create(
            name=KEY_ROWS["client_secret"], defaults={"value": seal_key("client_secret", CLIENT_SECRET)}
        )


def shipped_order(company="CJ대한통운", invoice="6543-2100-1234", status="배송", **extra):
    product = ShopProductFactory()
    return ShopOrderFactory(
        od_status=status, od_delivery_company=company, od_invoice=invoice, od_receipt_price=product.it_price,
        items=[(product, 1)], **extra
    )


# --- carrier mapping -----------------------------------------------------------------------


def test_every_mapped_courier_is_on_the_courier_list():
    names = {name for name, _url, _tel in DELIVERY_COMPANIES}
    assert set(DELIVERY_TRACKER_CARRIERS) <= names
    assert all(carrier.count(".") >= 1 for carrier in DELIVERY_TRACKER_CARRIERS.values())


def test_carrier_ids_follow_the_courier_name_like_the_link():
    assert tracker_carrier_id("CJ대한통운") == "kr.cjlogistics"
    assert tracker_carrier_id("우체국") == "kr.epost"
    # the partial match of get_delivery_inquiry
    assert tracker_carrier_id("한진") == "kr.hanjin"
    # unmapped or not a courier: the link only
    assert tracker_carrier_id("우리택배") == ""
    assert tracker_carrier_id("자체배송") == ""
    assert tracker_carrier_id("") == ""


# --- client --------------------------------------------------------------------------------


def test_a_recorded_track_answer_is_parsed():
    info = client.parse_track_info(RECORDED_TRACK["data"])
    assert info.delivered
    assert [event.status for event in info.events] == ["AT_PICKUP", "OUT_FOR_DELIVERY", "DELIVERED"]
    assert info.last_event.name == "배달완료"
    assert info.last_event.location == "서울강남"
    assert info.last_event.time.utcoffset() == timedelta(hours=9)


def test_unknown_status_codes_and_missing_times_are_not_trusted():
    event = client.parse_event({"time": "2026-10-29T08:30:00", "status": {"code": "TELEPORTED"}})
    assert (event.status, event.time) == ("UNKNOWN", None)
    with pytest.raises(client.DeliveryTrackerError) as caught:
        client.parse_track_info({"track": None})
    assert caught.value.code == "NOT_FOUND"


def test_track_posts_the_documented_request_to_the_fixed_host():
    credentials = client.TrackerCredentials(CLIENT_ID, CLIENT_SECRET)
    with patch(OPEN, return_value=answer(RECORDED_TRACK)) as opened:
        info = client.track("kr.cjlogistics", "654321001234", credentials=credentials)
    request = opened.call_args.args[0]
    assert request.full_url == "https://apis.tracker.delivery/graphql"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"TRACKQL-API-KEY {CLIENT_ID}:{CLIENT_SECRET}"
    body = json.loads(request.data)
    assert body["variables"] == {"carrierId": "kr.cjlogistics", "trackingNumber": "654321001234", "last": 30}
    assert "track(carrierId: $carrierId, trackingNumber: $trackingNumber)" in body["query"]
    assert opened.call_args.kwargs["timeout"] == client.TIMEOUT_SECONDS
    assert info.delivered


@pytest.mark.parametrize(
    "raised, code",
    [
        (urllib_error.URLError("down"), "NETWORK"),
        (TimeoutError(), "NETWORK"),
        (urllib_error.HTTPError(client.API_URL, 429, "Too Many", {}, io.BytesIO(b"")), "RATE_LIMITED"),
        (urllib_error.HTTPError(client.API_URL, 302, "Found", {}, io.BytesIO(b"")), "HTTP_302"),
        (
            urllib_error.HTTPError(
                client.API_URL, 401, "Unauthorized", {},
                io.BytesIO(json.dumps({"errors": [{"message": "x", "extensions": {"code": "UNAUTHENTICATED"}}]}).encode()),
            ),
            "UNAUTHENTICATED",
        ),
    ],
)
def test_transport_failures_become_tracker_errors(raised, code):
    with patch(OPEN, side_effect=raised), pytest.raises(client.DeliveryTrackerError) as caught:
        client.track("kr.cjlogistics", "1", credentials=client.TrackerCredentials("a" * 8, "b" * 8))
    assert caught.value.code == code


def test_graphql_errors_with_http_200_are_read():
    payload = {"errors": [{"message": "Not found", "extensions": {"code": "NOT_FOUND"}}], "data": None}
    with patch(OPEN, return_value=answer(payload)), pytest.raises(client.DeliveryTrackerError) as caught:
        client.track("kr.cjlogistics", "1", credentials=client.TrackerCredentials("a" * 8, "b" * 8))
    assert caught.value.code == "NOT_FOUND"
    assert not caught.value.retryable


def test_no_request_is_made_without_both_keys():
    with patch(OPEN) as opened, pytest.raises(client.DeliveryTrackerError):
        client.track("kr.cjlogistics", "1", credentials=client.TrackerCredentials(CLIENT_ID, ""))
    opened.assert_not_called()


def test_redirects_are_refused():
    handler = client._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/") is None


def test_register_webhook_sends_the_documented_input():
    expires = timezone.now() + timedelta(hours=48)
    with patch(OPEN, return_value=answer({"data": {"registerTrackWebhook": True}})) as opened:
        accepted = client.register_webhook(
            "kr.cjlogistics", "1", callback_url="https://shop.example/cb", expires_at=expires,
            credentials=client.TrackerCredentials(CLIENT_ID, CLIENT_SECRET),
        )
    body = json.loads(opened.call_args.args[0].data)
    assert accepted is True
    assert "registerTrackWebhook(input: $input)" in body["query"]
    assert body["variables"]["input"] == {
        "carrierId": "kr.cjlogistics", "trackingNumber": "1", "callbackUrl": "https://shop.example/cb",
        "expirationTime": expires.isoformat(),
    }


def test_credentials_never_show_in_a_repr():
    credentials = client.TrackerCredentials(CLIENT_ID, CLIENT_SECRET)
    assert CLIENT_SECRET not in repr(credentials) and CLIENT_ID not in repr(credentials)


# --- settings ------------------------------------------------------------------------------


def test_tracking_is_off_unless_switched_on_with_both_keys(db):
    assert not tracking_config().enabled
    enable_tracking(keys=False)
    assert not tracking_config().enabled
    Config.objects.create(name=KEY_ROWS["client_id"], value=seal_key("client_id", CLIENT_ID))
    assert not tracking_config().enabled
    Config.objects.create(name=KEY_ROWS["client_secret"], value=seal_key("client_secret", CLIENT_SECRET))
    config = tracking_config()
    assert config.enabled
    assert CLIENT_SECRET not in repr(config)


def test_a_disabled_site_never_calls_the_api_and_shows_no_tracking(db, member_client, member):
    order = shipped_order(user=member)
    ShopShipmentTracking.objects.create(
        order=order, delivery_company=order.od_delivery_company, invoice=order.od_invoice, carrier_id="kr.cjlogistics",
        tracking_number="654321001234", status_code="IN_TRANSIT", status_label="이동 중",
    )
    with patch(TRACK) as track:
        result = delivery_tracking.refresh_order_tracking(order)
    track.assert_not_called()
    assert result.status == "skipped"
    data = member_client.get(f"/api/v1/shop/orders/{order.od_id}").json()["data"]
    assert data["shipment_tracking"] is None
    assert data["delivery_inquiry_url"]


# --- refresh, backoff and re-tracking --------------------------------------------------------


def test_a_lookup_records_the_events_and_schedules_the_next_one(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    with patch(TRACK, return_value=in_transit_info()) as track:
        result = delivery_tracking.refresh_order_tracking(order, now=now)
    assert result.status == "updated"
    # spaces and hyphens are dropped from the invoice
    assert track.call_args.args == ("kr.cjlogistics", "654321001234")
    row = ShopShipmentTracking.objects.get(order=order)
    assert (row.status_code, row.status_label, row.failures) == ("IN_TRANSIT", "이동 중", 0)
    assert row.next_check_at == now + delivery_tracking.POLL_INTERVAL
    assert row.events[0]["location"] == "대전HUB"


def test_errors_back_off_and_not_found_waits(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    with patch(TRACK, side_effect=client.DeliveryTrackerError("INTERNAL")):
        delays = []
        for step in range(4):
            at = now + timedelta(minutes=step)
            delivery_tracking.refresh_order_tracking(order, now=at)
            row = ShopShipmentTracking.objects.get(order=order)
            delays.append(row.next_check_at - at)
    assert delays == [timedelta(minutes=30), timedelta(hours=1), timedelta(hours=2), timedelta(hours=4)]
    assert "INTERNAL" in row.last_error
    assert delivery_tracking._error_backoff(50) == delivery_tracking.MAX_ERROR_BACKOFF
    later = now + timedelta(minutes=10)
    with patch(TRACK, side_effect=client.DeliveryTrackerError("NOT_FOUND")):
        result = delivery_tracking.refresh_order_tracking(order, now=later)
    row.refresh_from_db()
    assert result.status == "not_found"
    assert row.next_check_at == later + delivery_tracking.NOT_FOUND_INTERVAL


def test_a_lookup_is_not_repeated_within_the_cooldown(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    with patch(TRACK, return_value=in_transit_info()) as track:
        delivery_tracking.refresh_order_tracking(order, now=now)
        again = delivery_tracking.refresh_order_tracking(order, now=now + timedelta(seconds=5))
    assert again.status == "skipped"
    assert track.call_count == 1


def test_a_lookup_claimed_by_another_run_is_skipped(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    with patch(TRACK, return_value=in_transit_info()):
        delivery_tracking.refresh_order_tracking(order, now=now - timedelta(hours=4))
    stale = ShopShipmentTracking.objects.get(order=order)
    # another run stamps the row between our read and our claim
    ShopShipmentTracking.objects.filter(pk=stale.pk).update(last_checked_at=now - timedelta(minutes=5))
    assert not delivery_tracking._claim(stale, now)


def test_a_webhook_ping_during_a_lookup_is_kept(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    pinged = now - timedelta(seconds=1)

    def track(*args, **kwargs):
        ShopShipmentTracking.objects.filter(order=order).update(next_check_at=pinged)
        return in_transit_info()

    ShopShipmentTracking.objects.create(
        order=order, delivery_company=order.od_delivery_company, invoice=order.od_invoice, carrier_id="kr.cjlogistics",
        tracking_number="654321001234", next_check_at=now - timedelta(minutes=1),
    )
    with patch(TRACK, side_effect=track):
        delivery_tracking.refresh_order_tracking(order, now=now)
    assert ShopShipmentTracking.objects.get(order=order).next_check_at == pinged


def test_a_changed_invoice_starts_the_tracking_over(db):
    enable_tracking()
    order = shipped_order()
    with patch(TRACK, return_value=delivered_info()):
        delivery_tracking.refresh_order_tracking(order)
    assert ShopShipmentTracking.objects.get(order=order).delivered_at
    order.od_invoice = "999988887777"
    order.save(update_fields=["od_invoice"])
    # the old shipment is not shown for the new invoice
    assert delivery_tracking.current_tracking(order) is None
    assert order in delivery_tracking.due_orders()
    with patch(TRACK, return_value=in_transit_info()):
        delivery_tracking.refresh_order_tracking(order)
    row = ShopShipmentTracking.objects.get(order=order)
    assert (row.tracking_number, row.delivered_at, row.status_code) == ("999988887777", None, "IN_TRANSIT")
    assert len(row.events) == 1


def test_due_orders_pick_shipped_tracked_orders_that_are_due(db):
    now = timezone.now()
    new = shipped_order()
    due = shipped_order()
    later = shipped_order()
    delivered = shipped_order()
    stale = shipped_order()
    shipped_order(company="우리택배")
    shipped_order(status="준비")
    shipped_order(invoice="")

    def track(order, **fields):
        ShopShipmentTracking.objects.create(
            order=order, delivery_company=order.od_delivery_company, invoice=order.od_invoice,
            carrier_id="kr.cjlogistics", tracking_number="654321001234", **fields
        )

    track(due, next_check_at=now - timedelta(minutes=1))
    track(later, next_check_at=now + timedelta(hours=1))
    track(delivered, delivered_at=now - timedelta(days=1))
    track(stale, started_at=now - timedelta(days=delivery_tracking.MAX_TRACKING_DAYS + 1))
    assert delivery_tracking.due_orders(now=now) == [new, due]
    assert delivery_tracking.due_orders(now=now, limit=1) == [new]


# --- delivered -----------------------------------------------------------------------------


def test_delivered_is_recorded_but_the_order_stays_without_the_switch(db):
    enable_tracking(complete=False)
    order = shipped_order()
    with patch(TRACK, return_value=delivered_info()), patch(REGISTER) as register:
        result = delivery_tracking.refresh_order_tracking(order)
    order.refresh_from_db()
    row = ShopShipmentTracking.objects.get(order=order)
    assert (result.status, result.completed) == ("delivered", False)
    assert order.od_status == "배송"
    assert row.delivered_at == client.parse_time("2026-10-29T14:05:00+09:00")
    assert row.next_check_at is None
    register.assert_not_called()
    assert order not in delivery_tracking.due_orders()


def test_delivered_completes_the_order_through_the_status_flow_with_the_switch(db, django_capture_on_commit_callbacks):
    enable_tracking(complete=True)
    Config.objects.update_or_create(name="cf_email_use", defaults={"value": "1"})
    Config.objects.update_or_create(name="cf_admin_email", defaults={"value": "shop@example.test"})
    order = shipped_order()
    with patch(TRACK, return_value=delivered_info()), django_capture_on_commit_callbacks(execute=True):
        result = delivery_tracking.refresh_order_tracking(order)
    order.refresh_from_db()
    assert result.completed
    assert order.od_status == "완료"
    assert set(order.items.values_list("ct_status", flat=True)) == {"완료"}
    assert "주문상태 배송→완료 처리" in order.od_mod_history
    assert "배송조회" in order.od_mod_history
    delivered_mails = [message for message in mail.outbox if "배송완료" in message.subject]
    assert len(delivered_mails) == 1
    assert delivered_mails[0].to == [order.od_email]
    assert "서울강남" in delivered_mails[0].body
    # a second lookup of a delivered shipment changes nothing
    with patch(TRACK, return_value=delivered_info()), django_capture_on_commit_callbacks(execute=True):
        again = delivery_tracking.refresh_order_tracking(order)
    assert not again.completed
    assert len([message for message in mail.outbox if "배송완료" in message.subject]) == 1


def test_an_order_past_shipping_is_not_looked_up(db):
    enable_tracking(complete=True)
    order = shipped_order(status="완료")
    with patch(TRACK) as track:
        result = delivery_tracking.refresh_order_tracking(order)
    track.assert_not_called()
    assert result.status == "skipped"


def test_a_completion_missed_earlier_is_retried_without_a_lookup(db):
    enable_tracking(complete=False)
    order = shipped_order()
    with patch(TRACK, return_value=delivered_info()):
        delivery_tracking.refresh_order_tracking(order)
    order.refresh_from_db()
    assert order.od_status == "배송"
    assert order not in delivery_tracking.due_orders(complete_on_delivered=False)
    # the switch is turned on afterwards: the delivered order is due and completes without a call
    Config.objects.filter(name="de_tracking_complete_delivered").update(value="1")
    assert order in delivery_tracking.due_orders(complete_on_delivered=True)
    with patch(TRACK) as track:
        result = delivery_tracking.refresh_order_tracking(order)
    track.assert_not_called()
    order.refresh_from_db()
    assert result.completed and order.od_status == "완료"


# --- webhook -------------------------------------------------------------------------------


@override_settings(SOCIAL_APP_BASE_URL="https://shop.example")
def test_tracking_registers_the_webhook_with_the_tokened_callback(db):
    enable_tracking()
    order = shipped_order()
    now = timezone.now()
    with patch(TRACK, return_value=in_transit_info()), patch(REGISTER, return_value=True) as register:
        delivery_tracking.refresh_order_tracking(order, now=now)
    kwargs = register.call_args.kwargs
    assert kwargs["callback_url"] == f"https://shop.example/api/v1/shop/delivery-tracker/webhook/{webhook_token()}"
    assert kwargs["expires_at"] == now + delivery_tracking.WEBHOOK_TTL
    row = ShopShipmentTracking.objects.get(order=order)
    assert row.webhook_expires_at == now + delivery_tracking.WEBHOOK_TTL
    assert row.next_check_at == now + delivery_tracking.WEBHOOK_POLL_INTERVAL
    # not renewed while more than a day is left
    with patch(TRACK, return_value=in_transit_info()), patch(REGISTER, return_value=True) as register:
        delivery_tracking.refresh_order_tracking(order, now=now + timedelta(hours=3))
    register.assert_not_called()


@override_settings(SOCIAL_APP_BASE_URL="http://shop.example", SHOP_DELIVERY_TRACKER_CALLBACK_BASE_URL="")
def test_no_webhook_without_an_https_origin(db):
    assert webhook_callback_url() == ""
    enable_tracking()
    with patch(TRACK, return_value=in_transit_info()), patch(REGISTER) as register:
        delivery_tracking.refresh_order_tracking(shipped_order())
    register.assert_not_called()


def webhook(api_client, token, body):
    return api_client.post(f"/api/v1/shop/delivery-tracker/webhook/{token}", body, format="json")


def test_the_webhook_needs_the_site_token(db, api_client):
    enable_tracking()
    response = webhook(api_client, "not-the-token", {"carrierId": "kr.cjlogistics", "trackingNumber": "1"})
    assert response.status_code == 404
    assert api_client.get(f"/api/v1/shop/delivery-tracker/webhook/{webhook_token()}").status_code == 405


def test_the_webhook_only_marks_the_shipment_for_a_lookup(db, api_client):
    enable_tracking()
    order = shipped_order()
    later = timezone.now() + timedelta(hours=6)
    row = ShopShipmentTracking.objects.create(
        order=order, delivery_company=order.od_delivery_company, invoice=order.od_invoice, carrier_id="kr.cjlogistics",
        tracking_number="654321001234", status_code="IN_TRANSIT", next_check_at=later,
    )
    body = {"carrierId": "kr.cjlogistics", "trackingNumber": "654321001234", "status": "DELIVERED"}
    with patch(TRACK) as track:
        response = webhook(api_client, webhook_token(), body)
    assert response.status_code == 202
    assert response.json()["data"] == {"accepted": True}
    track.assert_not_called()
    row.refresh_from_db()
    assert row.status_code == "IN_TRANSIT" and row.delivered_at is None
    assert row.next_check_at <= timezone.now()
    assert order in delivery_tracking.due_orders()


def test_the_webhook_refuses_a_body_without_the_shipment(db, api_client):
    enable_tracking()
    assert webhook(api_client, webhook_token(), {"carrierId": "kr.cjlogistics"}).status_code == 400


def test_the_webhook_accepts_quietly_while_tracking_is_off(db, api_client):
    response = webhook(api_client, webhook_token(), {"carrierId": "kr.cjlogistics", "trackingNumber": "1"})
    assert response.status_code == 202
    assert response.json()["data"] == {"accepted": False}


@override_settings(SECRET_KEY="new-secret-key-for-rotation-tests-0123456789", SECRET_KEY_FALLBACKS=["old-secret-key-0123456789abcdef"])
def test_a_token_of_a_rotated_key_still_works(db, api_client):
    from gnu_jango.shop.delivery_tracking_settings import _token, webhook_token_valid

    assert webhook_token_valid(_token("old-secret-key-0123456789abcdef"))
    assert webhook_token_valid(webhook_token())
    assert not webhook_token_valid(_token("some-other-key"))
    assert not webhook_token_valid("")


# --- command and scheduler -----------------------------------------------------------------


def run_command(*args):
    out = StringIO()
    call_command("track_shipments", "--json", *args, stdout=out)
    return json.loads(out.getvalue())


def test_the_command_does_nothing_while_tracking_is_off(db):
    shipped_order()
    with patch(TRACK) as track:
        summary = run_command("--apply")
    track.assert_not_called()
    assert (summary["enabled"], summary["inspected"]) == (False, 0)


def test_the_command_dry_run_lists_and_apply_looks_up(db):
    enable_tracking(complete=True)
    order = shipped_order()
    with patch(TRACK, return_value=delivered_info()) as track:
        planned = run_command()
        track.assert_not_called()
        applied = run_command("--apply", "--limit", "5")
    assert planned["samples"] == [{"order_id": order.od_id, "action": "planned"}]
    assert (applied["inspected"], applied["delivered"], applied["completed"]) == (1, 1, 1)
    order.refresh_from_db()
    assert order.od_status == "완료"


def test_one_failing_order_does_not_stop_the_run(db):
    enable_tracking()
    shipped_order()
    shipped_order()
    with patch(TRACK, side_effect=[RuntimeError("boom"), in_transit_info()]):
        summary = run_command("--apply")
    assert (summary["failed"], summary["updated"]) == (1, 1)


def test_the_scheduled_job_is_added_only_when_switched_on():
    assert "track_shipments" not in scheduled_jobs.JOB_NAMES
    try:
        with override_settings(SHOP_DELIVERY_TRACKING_JOB=True):
            importlib.reload(scheduled_jobs)
            job = scheduled_jobs.select_jobs(["track_shipments"])[0]
        assert job.args(dry_run=False) == ("--apply", "--json", "--limit", "30")
        assert job.args(dry_run=True) == ("--json",)
    finally:
        importlib.reload(scheduled_jobs)
    assert "track_shipments" not in scheduled_jobs.JOB_NAMES


# --- customer API and admin ----------------------------------------------------------------


def test_the_order_detail_shows_the_timeline_newest_first(db, member_client, member):
    enable_tracking()
    order = shipped_order(user=member)
    with patch(TRACK, return_value=delivered_info()):
        delivery_tracking.refresh_order_tracking(order)
    response = member_client.get(f"/api/v1/shop/orders/{order.od_id}")
    body = response.json()
    tracking = body["data"]["shipment_tracking"]
    assert tracking["status"] == "DELIVERED" and tracking["delivered"] is True
    assert tracking["status_label"] == "배송 완료"
    assert [event["status"] for event in tracking["events"]] == ["DELIVERED", "OUT_FOR_DELIVERY", "AT_PICKUP"]
    assert tracking["events"][0]["status_label"] == "배달완료"
    assert body["data"]["delivery_inquiry_url"]
    errors = list(response_validator("/api/v1/shop/orders/{od_id}").iter_errors(body))
    assert errors == []
    text = response.content.decode()
    assert CLIENT_SECRET not in text and CLIENT_ID not in text
    # the order list stays as it was
    listed = member_client.get("/api/v1/shop/orders").json()["data"][0]
    assert "shipment_tracking" not in listed


@pytest.fixture
def admin_web_client(client, admin_member):
    client.force_login(admin_member)
    return client


SETTINGS_FORM = {
    "de_admin_company_name": "Demo Shop", "de_admin_company_tel": "", "de_delivery_company": "CJ대한통운",
    "de_send_cost_case": "", "de_send_cost_limit": "", "de_send_cost_list": "", "de_baesong_content": "",
    "de_change_content": "", "de_settle_min_point": "0", "de_settle_max_point": "0", "de_settle_point_unit": "1",
}


def test_the_settings_page_seals_the_keys_and_never_shows_them(db, admin_web_client):
    url = reverse("admin-shop-settings")
    response = admin_web_client.post(url, {
        **SETTINGS_FORM, "de_tracking_use": "on", KEY_ROWS["client_id"]: CLIENT_ID, KEY_ROWS["client_secret"]: CLIENT_SECRET,
    })
    assert response.status_code == 302
    stored = Config.objects.get(name=KEY_ROWS["client_secret"]).value
    assert stored.startswith("sv2:") and CLIENT_SECRET not in stored
    assert tracking_config().enabled
    page = admin_web_client.get(url).content.decode()
    assert CLIENT_SECRET not in page and CLIENT_ID not in page and stored not in page
    assert "등록됨 (****ab12)" in page
    assert "배송조회 (Delivery Tracker)" in page
    messages = " ".join(LogEntry.objects.values_list("change_message", flat=True))
    assert "배송조회 Client Secret 등록" in messages
    assert CLIENT_SECRET not in messages
    # a blank input keeps the key, the delete box removes it
    admin_web_client.post(url, {**SETTINGS_FORM, "de_tracking_use": "on", f"{KEY_ROWS['client_secret']}_delete": "on"})
    assert not Config.objects.filter(name=KEY_ROWS["client_secret"]).exists()
    assert Config.objects.filter(name=KEY_ROWS["client_id"]).exists()
    assert not tracking_config().enabled


def test_a_malformed_key_is_rejected_and_not_echoed(db, admin_web_client):
    pasted = "bad key with spaces"
    response = admin_web_client.post(reverse("admin-shop-settings"), {**SETTINGS_FORM, KEY_ROWS["client_secret"]: pasted})
    assert response.status_code == 200
    assert KEY_ROWS["client_secret"] in response.context["form"].errors
    assert pasted not in response.content.decode()


def test_the_order_page_shows_the_tracking_and_refreshes_on_post(db, admin_web_client):
    enable_tracking(complete=True)
    order = shipped_order()
    change_url = reverse("admin:shop_shoporder_change", args=[order.pk])
    refresh_url = reverse("admin:shop_shoporder_tracking_refresh", args=[order.pk])
    page = admin_web_client.get(change_url).content.decode()
    assert "지금 조회" in page and f'data-g5-post-url="{refresh_url}"' in page
    with patch(TRACK) as track:
        assert admin_web_client.get(refresh_url).status_code == 405
    track.assert_not_called()
    with patch(TRACK, return_value=delivered_info()):
        response = admin_web_client.post(refresh_url)
    assert response.status_code == 302
    order.refresh_from_db()
    assert order.od_status == "완료"
    page = admin_web_client.get(change_url).content.decode()
    assert "배달완료" in page and "kr.cjlogistics" in page


def test_the_order_page_explains_an_untracked_courier(db, admin_web_client):
    enable_tracking()
    order = shipped_order(company="우리택배")
    page = admin_web_client.get(reverse("admin:shop_shoporder_change", args=[order.pk])).content.decode()
    assert "배송조회를 지원하지 않는 배송회사" in page
    assert "data-g5-post-url" not in page
