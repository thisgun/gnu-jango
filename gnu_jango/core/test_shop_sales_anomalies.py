from datetime import date, datetime, timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from gnu_jango.ai.client import ChatError, chat_provider_override
from gnu_jango.ai.testing import FakeChatProvider
from gnu_jango.shop.admin.reports import _month_param
from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.sales_anomalies import month_report

TODAY = date(2026, 10, 20)
BASELINE = (date(2026, 7, 1), date(2026, 9, 30))
_ids = count(1)


def orders_on(day, number=1, amount=10_000, status="입금", method="무통장", refund=0):
    moment = timezone.make_aware(datetime(day.year, day.month, day.day, 12))
    ShopOrder.objects.bulk_create([
        ShopOrder(od_id=f"{20261000000000 + next(_ids)}", od_name="홍길동", od_email="buyer@example.test",
                  od_hp="010-0000-0000", od_datetime=moment, od_status=status, od_settle_case=method,
                  od_cart_price=amount, od_receipt_price=amount, od_refund_price=refund)
        for _ in range(number)
    ])


def every_day(start, end, **kwargs):
    day = start
    while day <= end:
        orders_on(day, **kwargs)
        day += timedelta(days=1)


def keys(report):
    return [finding["key"] for finding in report["findings"]]


@pytest.fixture
def steady(db):
    """Two 10,000 won orders a day for three months, one by bank transfer and one by card."""
    every_day(*BASELINE, method="무통장")
    every_day(*BASELINE, method="신용카드")


def test_too_little_history_is_said_instead_of_compared(db):
    orders_on(date(2026, 10, 3), number=4)
    report = month_report(TODAY, TODAY)
    assert keys(report) == ["history"] and report["enough_history"] is False


def test_an_ordinary_month_has_nothing_to_report(steady):
    every_day(date(2026, 10, 1), TODAY, method="무통장")
    every_day(date(2026, 10, 1), TODAY, method="신용카드")
    assert keys(month_report(TODAY, TODAY)) == ["normal"]


def test_a_payment_method_that_went_quiet_for_a_week_is_flagged_first(steady):
    every_day(date(2026, 10, 1), TODAY, method="무통장", number=2)
    every_day(date(2026, 10, 1), date(2026, 10, 13), method="신용카드")
    report = month_report(TODAY, TODAY)
    first = report["findings"][0]
    assert first["key"] == "method_silent" and first["severity"] == "high"
    assert first["numbers"]["method"] == "카드" and first["numbers"]["baseline_share_percent"] == 50


def test_a_slow_month_is_flagged_by_its_pace(steady):
    every_day(date(2026, 10, 1), TODAY, method="무통장", amount=4_000)
    every_day(date(2026, 10, 1), TODAY, method="신용카드", amount=4_000)
    pace = next(f for f in month_report(TODAY, TODAY)["findings"] if f["key"] == "pace")
    assert pace["numbers"]["change_percent"] == -60 and pace["severity"] == "high"
    assert "적습니다" in pace["title"]


def test_a_huge_jump_is_written_as_a_ratio(steady):
    orders_on(date(2026, 10, 2), amount=50_000_000)
    pace = next(f for f in month_report(TODAY, TODAY)["findings"] if f["key"] == "pace")
    assert "배입니다" in pace["title"] and "%" not in pace["title"]


def test_a_day_without_orders_is_flagged_but_not_today(db):
    every_day(*BASELINE, number=3)
    every_day(date(2026, 10, 1), date(2026, 10, 9), number=3)
    every_day(date(2026, 10, 11), TODAY - timedelta(days=1), number=3)
    quiet = [f["numbers"]["date"] for f in month_report(TODAY, TODAY)["findings"] if f["key"] == "quiet_day"]
    assert quiet == ["2026-10-10"]


def test_a_day_above_the_busiest_baseline_day_is_a_spike(steady):
    every_day(date(2026, 10, 1), TODAY, method="무통장")
    every_day(date(2026, 10, 1), TODAY, method="신용카드")
    orders_on(date(2026, 10, 5), amount=300_000)
    spikes = [f for f in month_report(TODAY, TODAY)["findings"] if f["key"] == "day_spike"]
    assert [f["numbers"]["date"] for f in spikes] == ["2026-10-05"]
    assert spikes[0]["numbers"]["baseline_busiest"] == 20_000


def test_a_rise_in_cancellations_and_refunds_is_flagged(steady):
    every_day(date(2026, 10, 1), TODAY, method="무통장")
    every_day(date(2026, 10, 1), TODAY, method="신용카드")
    orders_on(date(2026, 10, 6), number=12, status="취소")
    orders_on(date(2026, 10, 7), amount=120_000, refund=120_000)
    found = {f["key"]: f for f in month_report(TODAY, TODAY)["findings"]}
    assert found["cancel_rate"]["numbers"]["cancels"] == 12
    assert found["refund"]["numbers"]["refund"] == 120_000


def test_the_first_days_of_a_month_raise_no_pace_alarm(steady):
    # 10 a.m. on the 2nd: yesterday was a normal day and today has barely started
    every_day(date(2026, 10, 1), date(2026, 10, 1), method="무통장")
    every_day(date(2026, 10, 1), date(2026, 10, 1), method="신용카드")
    assert "pace" not in keys(month_report(date(2026, 10, 2), date(2026, 10, 2)))


def test_today_still_coming_in_does_not_count_as_a_slump(steady):
    every_day(date(2026, 10, 1), TODAY - timedelta(days=1), method="무통장")
    every_day(date(2026, 10, 1), TODAY - timedelta(days=1), method="신용카드")
    # nothing yet today
    assert keys(month_report(TODAY, TODAY)) == ["normal"]


def test_a_past_month_compares_every_one_of_its_days(steady):
    every_day(date(2026, 9, 1), date(2026, 9, 30), method="무통장", amount=4_000)
    pace = next(f for f in month_report(date(2026, 9, 1), TODAY)["findings"] if f["key"] == "pace")
    assert pace["numbers"]["days"] == 30


def test_month_parameter_falls_back_to_this_month():
    assert _month_param("2026-07", TODAY) == date(2026, 7, 1)
    assert _month_param("2027-01", TODAY) == date(2026, 10, 1)
    assert _month_param("0001-01", TODAY) == date(2000, 1, 1)
    assert _month_param("not-a-month", TODAY) == date(2026, 10, 1)
    assert _month_param(None, TODAY) == date(2026, 10, 1)


def staff_with(*codenames):
    user = get_user_model().objects.create_user("staff-" + "-".join(codenames), "s@example.test", "pw", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
    return user


@pytest.mark.django_db
def test_the_admin_page_needs_the_order_view_permission(client):
    url = reverse("admin:shop_shoporder_sales_anomalies")
    client.force_login(staff_with("view_shopproduct"))
    assert client.get(url).status_code == 403
    client.force_login(staff_with("view_shoporder"))
    response = client.get(url)
    assert response.status_code == 200
    assert "매출 이상 징후" in response.content.decode() and "AI 설명은 꺼져 있습니다" in response.content.decode()


@pytest.mark.django_db
def test_the_admin_page_shows_the_ai_briefing_only_when_its_numbers_check_out(client, steady):
    url = reverse("admin:shop_shoporder_sales_anomalies")
    client.force_login(staff_with("view_shoporder"))
    chat = FakeChatProvider(reply="이번 달은 주문이 평소와 다를 수 있습니다. 결제대행사 상태를 확인해 보세요.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        page = client.post(url, {"month": "2026-09"}).content.decode()
        assert "결제대행사 상태를 확인해 보세요" in page and len(chat.calls) == 1
        # the customer's name never reaches the model
        assert "홍길동" not in chat.calls[0][1]
        chat.reply = "입금이 약 168만 원입니다."
        page = client.post(url, {"month": "2026-08"}).content.decode()
        assert "점검 결과에 없는 숫자" in page and "168만" not in page
        chat.error = ChatError("timeout")
        page = client.post(url, {"month": "2026-07"}).content.decode()
        assert "제한 시간 안에 답하지 않았습니다" in page
