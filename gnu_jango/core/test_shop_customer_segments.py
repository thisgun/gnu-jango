import io
from datetime import date, datetime, timedelta
from itertools import count

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from gnu_jango.shop.customer_segments import (
    SEGMENT_GRID,
    SEGMENTS,
    Customer,
    rank_scores,
    score_customers,
    segment_report,
    segment_rows,
    summarize,
)
from gnu_jango.shop.models import ShopOrder

TODAY = date(2026, 11, 7)
URL_NAME = "admin:shop_shoporder_customer_segments"
_ids = count(1)


def customer(user_id, days, orders, amount):
    return Customer(
        user_id=user_id, username=f"u{user_id}", nickname="", email="", accepts_mail=False,
        last_order=TODAY - timedelta(days=days), recency_days=days, orders=orders, amount=amount,
    )


def ranked_people():
    return [customer(i, days=i * 20, orders=11 - i, amount=(11 - i) * 1000) for i in range(1, 11)]


def test_equal_values_share_a_score():
    assert rank_scores([5, 5, 5, 9, 1]) == [2, 2, 2, 5, 1]


def test_scores_follow_rank_in_either_direction():
    values = list(range(1, 11))
    assert rank_scores(values) == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert rank_scores(values, higher_is_better=False) == [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]


@pytest.mark.parametrize("size", [1, 2, 3, 4])
def test_fewer_than_five_customers_still_score_between_one_and_five(size):
    scores = rank_scores(list(range(size)))
    assert all(1 <= score <= 5 for score in scores)
    assert scores == sorted(scores) and scores[0] == 1


def test_everyone_tied_scores_one_and_nobody_is_an_error():
    assert rank_scores([7, 7, 7]) == [1, 1, 1]
    assert rank_scores([]) == []


def test_every_recency_and_frequency_cell_has_a_segment_and_every_segment_is_reachable():
    assert set(SEGMENT_GRID) == {(r, f) for r in range(1, 6) for f in range(1, 6)}
    assert set(SEGMENT_GRID.values()) == {segment.key for segment in SEGMENTS}


def test_recent_frequent_big_spenders_are_champions_and_the_long_gone_are_lost():
    scored = {c.user_id: c.segment for c in score_customers(ranked_people())}
    assert scored[1] == "champions" and scored[10] == "lost"


def test_segment_table_lists_every_segment_with_counts_averages_and_median_recency():
    people = ranked_people()
    report = summarize(people, 365, TODAY - timedelta(days=364), TODAY)
    assert [row.segment for row in report.rows] == list(SEGMENTS)
    assert sum(row.count for row in report.rows) == 10
    champions = next(row for row in report.rows if row.segment.key == "champions")
    members = [c for c in report.customers if c.segment == "champions"]
    assert champions.count == len(members) and champions.share == len(members) / 10
    assert champions.avg_amount == round(sum(c.amount for c in members) / len(members))
    assert report.lapsed_count == sum(1 for c in people if c.recency_days >= 90)


def test_an_empty_window_gives_an_empty_report_not_an_error():
    report = summarize([], 365, TODAY, TODAY)
    assert report.customers == () and report.median_amount == 0 and report.lapsed_count == 0
    assert all(row.count == 0 and row.share == 0 for row in segment_rows(()))


def place(user, days_ago, amount=10_000, status="입금", refund=0):
    day = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    ShopOrder.objects.create(
        od_id=f"{20261100000000 + next(_ids)}", user=user, od_name="홍길동",
        od_datetime=timezone.make_aware(day) + timedelta(hours=12), od_status=status,
        od_cart_price=amount, od_receipt_price=amount, od_refund_price=refund,
    )


def member(name, mailing=False):
    user = get_user_model().objects.create_user(name, f"{name}@example.test", "pw")
    user.profile.nickname = f"닉-{name}"
    user.profile.mailing = mailing
    user.profile.save()
    return user


@pytest.fixture
def shop(db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    alice, bob, carol = member("alice", mailing=True), member("bob"), member("carol")
    for days in (2, 10, 30):
        place(alice, days, amount=50_000)
    place(bob, 100, amount=20_000, refund=5_000)
    place(bob, 120, status="취소", amount=999_000)
    place(carol, 400, amount=70_000)
    place(None, 1, amount=88_000)


def test_report_counts_members_with_the_shops_rules(shop):
    report = segment_report(365)
    people = {c.username: c for c in report.customers}
    assert set(people) == {"alice", "bob"}
    assert people["alice"].orders == 3 and people["alice"].amount == 150_000 and people["alice"].recency_days == 2
    assert people["bob"].orders == 1 and people["bob"].amount == 15_000 and people["bob"].recency_days == 100
    assert report.lapsed_count == 1


def test_a_longer_window_brings_in_older_customers(shop):
    assert {c.username for c in segment_report(730).customers} == {"alice", "bob", "carol"}
    assert {c.username for c in segment_report(180).customers} == {"alice", "bob"}


def staff_with(*codenames):
    user = get_user_model().objects.create_user("staff-" + "-".join(codenames), "s@example.test", "pw", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
    return user


def test_the_page_needs_the_order_view_permission(client, db):
    client.force_login(staff_with("view_shopproduct"))
    assert client.get(reverse(URL_NAME)).status_code == 403


def test_the_page_renders_rows_and_links_each_segment_to_a_filtered_list(client, shop):
    client.force_login(staff_with("view_shoporder"))
    page = client.get(reverse(URL_NAME)).content.decode()
    assert "고객 세그먼트 (RFM)" in page and "alice" in page and "닉-bob" in page and "carol" not in page
    assert "segment=champions" in page and "엑셀(.xlsx) 내려받기" not in page
    people = {c.username: c for c in segment_report(365).customers}
    only = client.get(reverse(URL_NAME), {"segment": people["bob"].segment}).content.decode()
    assert "닉-bob" in only
    assert ("닉-alice" in only) == (people["alice"].segment == people["bob"].segment)
    assert client.get(reverse(URL_NAME), {"window": "9999", "segment": "nope", "page": "x"}).status_code == 200


def test_an_empty_shop_still_renders(client, db):
    client.force_login(staff_with("view_shoporder"))
    assert "이 기간에 주문한 회원이 없습니다" in client.get(reverse(URL_NAME)).content.decode()


def test_the_export_needs_the_export_permission(client, shop):
    client.force_login(staff_with("view_shoporder"))
    assert client.get(reverse(URL_NAME), {"export": "xlsx"}).status_code == 403
    assert LogEntry.objects.count() == 0


def test_the_export_lists_the_filtered_customers_mails_only_the_consenting_and_is_logged(client, shop):
    client.force_login(staff_with("view_shoporder", "export_shoporder"))
    assert "엑셀(.xlsx) 내려받기" in client.get(reverse(URL_NAME)).content.decode()
    response = client.get(reverse(URL_NAME), {"export": "xlsx"})
    assert response.status_code == 200 and response["Content-Disposition"].endswith('.xlsx"')
    rows = list(load_workbook(io.BytesIO(response.content)).active.iter_rows(values_only=True))
    assert rows[0][0] == "아이디" and rows[0][6:9] == ("R", "F", "M")
    by_name = {row[0]: row for row in rows[1:]}
    assert set(by_name) == {"alice", "bob"}
    assert by_name["alice"][2] == "alice@example.test" and by_name["bob"][2] in (None, "")
    assert by_name["alice"][4] == 3 and by_name["alice"][5] == 150_000
    assert "customer segments (RFM): 2 rows" in LogEntry.objects.get().object_repr
