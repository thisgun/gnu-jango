import io
from datetime import date, datetime, timedelta
from itertools import count

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from gnu_jango.shop.customer_segments import (
    SEGMENT_GRID,
    SEGMENTS,
    Customer,
    band_score,
    m_scores,
    F_BANDS,
    F_DEFAULT,
    R_BANDS,
    R_DEFAULT,
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


@pytest.mark.parametrize(
    ("days", "score"), [(0, 5), (30, 5), (31, 4), (60, 4), (61, 3), (90, 3), (91, 2), (180, 2), (181, 1), (729, 1)]
)
def test_recency_is_scored_by_fixed_bands(days, score):
    assert band_score(days, R_BANDS, R_DEFAULT) == score


@pytest.mark.parametrize(
    ("orders", "score"), [(1, 1), (2, 2), (3, 3), (4, 4), (5, 4), (6, 5), (40, 5)]
)
def test_frequency_is_scored_by_fixed_bands(orders, score):
    assert band_score(orders, F_BANDS, F_DEFAULT) == score


def test_amount_scores_follow_rank_and_ties_share_the_higher_band():
    assert m_scores(list(range(1, 11))) == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert m_scores([5, 5, 5, 9, 1]) == [4, 4, 4, 5, 1]
    assert m_scores([7, 7, 7]) == [5, 5, 5]
    assert m_scores([7]) == [5]
    assert m_scores([]) == []


def segments_of(*people):
    return {c.user_id: c.segment for c in score_customers(list(people))}


def test_a_lone_customer_who_bought_today_is_a_champion_not_lost():
    assert segments_of(customer(1, days=0, orders=5, amount=500_000)) == {1: "champions"}


def test_a_shop_whose_customers_all_bought_this_week_has_no_lapsed_label():
    found = segments_of(
        customer(1, days=5, orders=5, amount=900_000),
        customer(2, days=2, orders=1, amount=10_000),
        customer(3, days=1, orders=2, amount=20_000),
        customer(4, days=0, orders=1, amount=30_000),
    )
    assert found[1] == "champions"
    assert not {"lost", "hibernating", "at_risk", "cant_lose"} & set(found.values())


def test_everyone_tied_keeps_their_own_labels_by_the_bands():
    found = segments_of(*(customer(i, days=100, orders=1, amount=5_000) for i in range(1, 4)))
    assert set(found.values()) == {"hibernating"}


@pytest.mark.parametrize("orders", range(1, 12))
def test_someone_who_bought_today_is_never_hibernating_or_lost(orders):
    assert segments_of(customer(1, days=0, orders=orders, amount=1))[1] not in {"hibernating", "lost", "at_risk", "cant_lose"}


def test_one_order_yesterday_is_new_and_six_orders_this_month_is_a_champion():
    assert segments_of(customer(1, days=1, orders=1, amount=1))[1] == "new"
    assert segments_of(customer(1, days=20, orders=6, amount=1))[1] == "champions"


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
    assert report.lapsed_count == sum(1 for c in people if c.recency_days > 90)


def test_an_empty_window_gives_an_empty_report_not_an_error():
    report = summarize([], 365, TODAY, TODAY)
    assert report.customers == () and report.median_amount == 0 and report.lapsed_count == 0
    assert all(row.count == 0 and row.share == 0 for row in segment_rows(()))


def place(user, days_ago, amount=10_000, status="입금", refund=0, point=0, at=timedelta(hours=12)):
    day = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    ShopOrder.objects.create(
        od_id=f"{20261100000000 + next(_ids)}", user=user, od_name="홍길동",
        od_datetime=timezone.make_aware(day) + at, od_status=status,
        od_cart_price=amount + point, od_receipt_price=amount, od_receipt_point=point, od_refund_price=refund,
    )


def member(name, mailing=False, certified=True):
    user = get_user_model().objects.create_user(name, f"{name}@example.test", "pw")
    user.profile.nickname = f"닉-{name}"
    user.profile.mailing = mailing
    if not certified:
        user.profile.email_certify = None
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
    dave = member("dave", mailing=True, certified=False)
    for status in ("주문", "취소", "반품", "품절", "cancelled", "canceled", "return", "returned"):
        place(dave, 3, status=status)
    place(None, 1, amount=88_000)


def test_report_counts_members_with_the_shops_rules(shop):
    report = segment_report(365)
    people = {c.username: c for c in report.customers}
    assert set(people) == {"alice", "bob"}, "unpaid, cancelled and returned orders do not count"
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
    assert "이 기간에 결제한 회원이 없습니다" in client.get(reverse(URL_NAME)).content.decode()


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
    assert isinstance(by_name["alice"][3], datetime)
    assert by_name["alice"][4] == 3 and by_name["alice"][5] == 150_000
    assert "customer segments (RFM): 2 rows" in LogEntry.objects.get().object_repr


def test_a_member_who_agreed_to_mail_at_an_uncertified_address_is_not_exported(client, db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    place(member("erin", mailing=True, certified=False), 2)
    client.force_login(staff_with("view_shoporder", "export_shoporder"))
    rows = list(load_workbook(io.BytesIO(client.get(reverse(URL_NAME), {"export": "xlsx"}).content)).active.iter_rows(values_only=True))
    assert rows[1][0] == "erin" and rows[1][2] in (None, "")


def test_the_export_filename_names_the_segment(client, shop):
    client.force_login(staff_with("view_shoporder", "export_shoporder"))
    segment = {c.username: c.segment for c in segment_report(365).customers}["alice"]
    name = client.get(reverse(URL_NAME), {"export": "xlsx", "segment": segment})["Content-Disposition"]
    assert f"-365d-{segment}.xlsx" in name


def segments_by_name(window=365):
    return {c.username: c.segment for c in segment_report(window).customers}


def test_a_fully_refunded_order_counts_for_nothing_and_a_partly_refunded_one_counts_once(db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    refunded = member("refunded")
    for days in (5, 20, 40, 60, 80, 100):
        place(refunded, days, amount=30_000, refund=30_000)
    mixed = member("mixed")
    place(mixed, 5, amount=30_000, refund=30_000)
    place(mixed, 10, amount=30_000, refund=10_000)
    place(member("points"), 3, amount=0, point=15_000)
    place(member("cash_back"), 4, amount=10_000, point=20_000, refund=10_000)
    people = {c.username: c for c in segment_report(365).customers}
    assert set(people) == {"mixed", "points", "cash_back"}, "a member whose orders were all refunded is not a customer"
    assert people["cash_back"].amount == 0, "M counts the cash kept, as 매출현황 does"
    assert people["mixed"].orders == 1 and people["mixed"].amount == 20_000 and people["mixed"].recency_days == 10


def test_new_means_the_first_paid_order_ever_falls_in_the_window(db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    returning = member("returning")
    place(returning, 500)
    place(returning, 5)
    first = member("first")
    place(first, 500, status="취소")
    place(first, 400, amount=30_000, refund=30_000)
    place(first, 5)
    faded = member("faded")
    place(faded, 500)
    place(faded, 200)
    kept_part = member("kept_part")
    place(kept_part, 500, amount=30_000, refund=10_000)
    place(kept_part, 5)
    found = segments_by_name()
    assert found["first"] == "new", "cancelled or refunded orders before the window do not make a customer returning"
    assert found["returning"] == found["kept_part"] == "potential"
    assert found["faded"] == "hibernating"
    assert segments_by_name(730) == {"returning": "potential", "first": "new", "faded": "hibernating", "kept_part": "potential"}


def test_the_window_starts_at_local_midnight_of_its_first_day(db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    first_day = member("first_day")
    place(first_day, 364, at=timedelta(minutes=30))
    place(first_day, 5)
    day_before = member("day_before")
    place(day_before, 365, at=timedelta(hours=23, minutes=30))
    place(day_before, 5)
    found = {c.username: c for c in segment_report(365).customers}
    assert found["first_day"].orders == 2 and found["first_day"].segment == "potential"
    assert found["day_before"].orders == 1 and found["day_before"].segment == "potential"
    assert not found["first_day"].returning and found["day_before"].returning


def test_the_customer_card_and_the_subtitle_both_count_paying_members(client, shop):
    client.force_login(staff_with("view_shoporder"))
    page = client.get(reverse(URL_NAME)).content.decode()
    assert "최근 365일 결제한 회원" in page and "결제한 회원을" in page
    assert "주문 회원" not in page and "구매 간격" not in page


def test_the_report_query_count_does_not_grow_with_customers(db, monkeypatch):
    monkeypatch.setattr("gnu_jango.shop.customer_segments.timezone.localdate", lambda *args: TODAY)
    place(member("solo"), 5)
    with CaptureQueriesContext(connection) as one:
        segment_report(365)
    for index in range(5):
        buyer = member(f"buyer{index}")
        place(buyer, 400)
        place(buyer, 3)
    with CaptureQueriesContext(connection) as many:
        assert len(segment_report(365).customers) == 6
    assert len(many) == len(one)
