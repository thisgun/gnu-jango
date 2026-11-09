import unicodedata
from datetime import timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from gnu_jango.shop import abuse_signals
from gnu_jango.shop.models import ShopCoupon, ShopCouponLog, ShopOrder, ShopOrderItem, ShopProduct, ShopReview
from gnu_jango.shop.shipping import current_shipping_policy
from gnu_jango.shop.signup_coupon import SIGNUP_COUPON_SUBJECT
from gnu_jango.shop.text_similarity import clusters, jaccard, normalise, shingles, similar_pairs

NOW = timezone.now()
_ids = count(1)
LONG = "배송이 빨라서 좋았고 품질도 기대 이상이라 가족에게도 추천하고 싶은 상품입니다"


def member(name):
    return get_user_model().objects.create_user(name, f"{name}@example.test", "pw")


def product(it_id="P1", name="상품"):
    return ShopProduct.objects.create(it_id=it_id, it_name=name)


def review(item, user, *, hours_ago=1, score=5, content="", subject="후기"):
    return ShopReview.objects.create(
        product=item, user=user, mb_id=user.username, is_name=user.username, is_score=score,
        is_subject=subject, is_content=content, is_time=NOW - timedelta(hours=hours_ago),
    )


def order(user, ip, *, hours_ago=1, coupon=0):
    return ShopOrder.objects.create(
        od_id=f"{20261100000000 + next(_ids)}", user=user, od_ip=ip, od_status="입금", od_coupon=coupon,
        od_datetime=NOW - timedelta(hours=hours_ago),
    )


def findings(rule, days=30):
    report = abuse_signals.build_report(days, now=NOW)
    return next(result.findings for result in report["results"] if result.rule.code == rule)


def test_shingles_ignore_case_spacing_and_punctuation():
    assert normalise("Hello,  World!") == "helloworld"
    assert shingles("abcd") == {"abc", "bcd"}
    assert shingles("ab") == frozenset()
    assert jaccard(shingles("abcdef"), shingles("abcdef")) == 1.0
    assert jaccard(frozenset(), shingles("abc")) == 0.0


def test_similar_pairs_finds_near_copies_and_skips_short_or_different_texts():
    base = "이 제품은 정말 튼튼하고 오래 쓸 수 있어서 만족합니다 강력 추천합니다 배송도 빠르고 포장도 꼼꼼해서 가족 모두가 아주 마음에 들어 합니다"
    texts = [base, base.replace("정말", "진짜"), "전혀 다른 내용의 긴 문장이 여기에 들어 있습니다 날씨가 좋네요", "짧은 글", base]
    result = similar_pairs(texts, threshold=0.8, min_length=20)
    assert {(p.left, p.right) for p in result.pairs} == {(0, 1), (0, 4), (1, 4)}
    assert clusters(result.pairs) == [(0, 1, 4)]


def test_similar_pairs_index_avoids_comparing_all_pairs_and_honours_the_veto():
    texts = [
        f"{n:04d} 번째 사람이 남긴 서로 전혀 다른 후기이며 {chr(0xAC00 + n * 7)}{chr(0xAC00 + n * 13)}{chr(0xAC00 + n * 17)} 로 끝납니다"
        for n in range(120)
    ]
    result = similar_pairs(texts)
    assert result.pairs == ()
    assert result.candidates < 120 * 119 // 2 // 10
    twins = ["같은 문장을 그대로 복사해서 올린 후기 입니다 정말 좋아요"] * 2
    assert len(similar_pairs(twins).pairs) == 1
    assert similar_pairs(twins, allow_pair=lambda i, j: False).pairs == ()


def test_the_threshold_is_exact_at_the_boundary():
    left = "abcdefghijklmnopqrstuvwxyz"
    right = left[:-1] + "!?"
    exact = jaccard(shingles(left), shingles(right))
    assert similar_pairs([left, right], threshold=exact - 0.001, min_length=5).pairs
    assert not similar_pairs([left, right], threshold=exact + 0.001, min_length=5).pairs


@pytest.mark.django_db
def test_burst_flags_five_star_reviews_from_several_authors_on_a_quiet_product():
    item = product()
    for n in range(5):
        review(item, member(f"b{n}"), hours_ago=2 + n)
    [found] = findings("review_burst")
    assert "5점 후기 5건" in found.title and found.severity == "medium"
    assert found.links and "id__in" in found.links[0].url


@pytest.mark.django_db
def test_burst_ignores_two_authors_low_scores_slow_pace_and_busy_history():
    item = product()
    a, b = member("a"), member("b")
    for n in range(6):
        review(item, a if n % 2 else b, hours_ago=1 + n)
    assert not findings("review_burst")
    other = product("P2")
    for n in range(5):
        review(other, member(f"c{n}"), hours_ago=1 + n, score=4)
    assert not findings("review_burst")
    spread = product("P3")
    for n in range(5):
        review(spread, member(f"d{n}"), hours_ago=1 + n * 30)
    assert not findings("review_burst")
    busy = product("P4")
    veteran = member("veteran")
    for n in range(60):
        review(busy, veteran, hours_ago=24 * 31 + n)
    for n in range(5):
        review(busy, member(f"e{n}"), hours_ago=1 + n)
    assert not findings("review_burst")


@pytest.mark.django_db
def test_burst_with_many_authors_is_high():
    item = product()
    for n in range(6):
        review(item, member(f"h{n}"), hours_ago=1 + n)
    assert findings("review_burst")[0].severity == "high"


@pytest.mark.django_db
def test_similar_reviews_group_copies_by_different_authors_only():
    item = product()
    review(item, member("x1"), content=f"<p>{LONG}</p>")
    review(item, member("x2"), content=LONG.replace("좋았고", "좋았고,"))
    review(item, member("x3"), content="  " + LONG)
    review(item, member("other"), content="완전히 다른 내용으로 쓴 충분히 긴 후기입니다 사용감이 아주 좋아요 감사합니다")
    review(item, member("short"), content="좋아요")
    [found] = findings("similar_review")
    assert found.severity == "high" and "3건 (작성자 3명)" in found.title
    assert "x1" in found.evidence[2]
    assert "other" not in found.evidence[2] and "short" not in found.evidence[2]


@pytest.mark.django_db
def test_one_author_repeating_themselves_is_not_flagged():
    item = product()
    user = member("solo")
    review(item, user, content=LONG)
    review(item, user, content=LONG, hours_ago=3)
    assert not findings("similar_review")


@pytest.mark.django_db
def test_similar_reviews_respect_the_window_and_cap(monkeypatch):
    item = product()
    review(item, member("w1"), content=LONG, hours_ago=24 * 40)
    review(item, member("w2"), content=LONG)
    assert not findings("similar_review")
    assert len(findings("similar_review", days=90)) == 1
    monkeypatch.setattr(abuse_signals, "SIMILARITY_REVIEW_CAP", 1)
    assert not findings("similar_review", days=90)


@pytest.mark.django_db
def test_only_a_received_order_line_counts_as_a_purchase():
    item = product()
    statuses = {"buyer": "완료", "canceled": "canceled", "returned": "returned", "취소": "취소", "unpaid": "주문", "shipping": "배송"}
    for name, status in statuses.items():
        user = member(name)
        review(item, user)
        placed = order(user, "10.0.0.1")
        ShopOrderItem.objects.create(order=placed, product=item, ct_id=f"c{user.pk}", it_id=item.it_id, it_name="x", ct_status=status)
    review(item, member("stranger"))
    names = sorted(found.title.split(":")[0] for found in findings("no_purchase_review"))
    assert names == sorted(set(statuses) - {"buyer"} | {"stranger"})


@pytest.mark.django_db
def test_the_review_gate_and_the_report_share_one_received_predicate():
    from gnu_jango.api.shop_reviews import _has_received_product

    item = product()
    user = member("gate")
    placed = order(user, "10.0.0.2")
    line = ShopOrderItem.objects.create(order=placed, product=item, ct_id="g1", it_id=item.it_id, it_name="x", ct_status="완료")
    assert _has_received_product(user, item)
    ShopOrderItem.objects.filter(pk=line.pk).update(ct_status="반품")
    assert not _has_received_product(user, item)


@pytest.mark.django_db
def test_hidden_reviews_are_left_out_of_every_review_rule():
    item = product()
    for n in range(6):
        review(item, member(f"hb{n}"), hours_ago=1 + n, content=LONG)
    ShopReview.objects.update(is_confirm="0")
    assert not findings("review_burst") and not findings("similar_review") and not findings("no_purchase_review")


@pytest.mark.django_db
def test_a_steadily_busy_new_product_is_not_a_burst():
    item = product()
    for day in range(6):
        for n in range(6):
            review(item, member(f"s{day}-{n}"), hours_ago=2 + day * 24 + n)
    assert not findings("review_burst")


@pytest.mark.django_db
def test_a_decomposed_copy_of_a_review_is_still_similar():
    item = product()
    review(item, member("nfc"), content=LONG)
    review(item, member("nfd"), content=unicodedata.normalize("NFD", LONG))
    [found] = findings("similar_review")
    assert "100%" in found.evidence[0]


@pytest.mark.django_db
def test_a_busy_shared_ip_does_not_starve_the_members_of_another_ip():
    busy = member("busy")
    for _ in range(25):
        order(busy, "100.0.0.1", hours_ago=1)
    for n in range(3):
        order(member(f"nat{n}"), "100.0.0.1", hours_ago=1)
    for n in range(3):
        order(member(f"old{n}"), "100.0.0.2", hours_ago=24 * 5, coupon=1000 if n == 0 else 0)
    by_ip = {found.title.split(":")[0]: found for found in findings("shared_ip")}
    quiet = by_ip["IP 100.0.0.2"]
    assert quiet.severity == "high"
    assert all(name in quiet.evidence[1] for name in ("old0", "old1", "old2"))
    assert "쿠폰 사용 주문 1건" in quiet.evidence[2]
    assert "nat0" in by_ip["IP 100.0.0.1"].evidence[1]


@pytest.mark.django_db
def test_capped_rules_say_how_many_they_found_and_how_many_they_show(monkeypatch):
    monkeypatch.setattr(abuse_signals, "NO_PURCHASE_DISPLAY_CAP", 2)
    monkeypatch.setattr(abuse_signals, "SHARED_IP_CAP", 1)
    item = product()
    for n in range(4):
        review(item, member(f"np{n}"), content=LONG)
    for ip in ("1.1.1.1", "2.2.2.2"):
        for n in range(3):
            order(member(f"{ip}-{n}"), ip)
    report = abuse_signals.build_report(30, now=NOW)
    results = {result.rule.code: result for result in report["results"]}
    assert (len(results["no_purchase_review"].findings), results["no_purchase_review"].total) == (2, 4)
    assert (len(results["shared_ip"].findings), results["shared_ip"].total) == (1, 2)
    assert report["is_trimmed"]
    monkeypatch.setattr(abuse_signals, "SIMILARITY_REVIEW_CAP", 2)
    review_rows = abuse_signals.build_report(30, now=NOW)["results"][1]
    assert "최신 2건만 검사" in review_rows.note


@pytest.mark.django_db
def test_without_the_review_permission_review_content_stays_out_of_the_page(client):
    item = product(name="가려질 상품")
    for n in range(6):
        review(item, member(f"rp{n}"), hours_ago=1 + n, content=LONG)
    for n in range(3):
        order(member(f"ip{n}"), "12.12.12.12")
    client.force_login(staff_with("view_shoporder"))
    html = client.get(reverse("admin:shop_shoporder_abuse_signals")).content.decode()
    assert html.count("후기 보기 권한이 필요합니다") == 3
    assert "가려질 상품" not in html and "rp0" not in html and "12.12.12.12" in html
    assert abuse_signals.build_report(30, can_view_reviews=False)["total"] == 1


@pytest.mark.django_db
def test_no_purchase_severity_follows_the_shop_write_setting_and_skips_superusers():
    item = product()
    review(item, member("walker"))
    admin = get_user_model().objects.create_superuser("boss", "b@example.test", "pw")
    review(item, admin)
    [found] = findings("no_purchase_review")
    assert found.severity == "info" and "꺼짐" in found.evidence[1]
    policy = current_shipping_policy()
    policy.de_item_use_write = 1
    policy.save()
    [found] = findings("no_purchase_review")
    assert found.severity == "medium" and "우회" in found.evidence[1]


@pytest.mark.django_db
def test_shared_ip_needs_three_members_and_is_medium_without_coupons():
    for n in range(2):
        order(member(f"two{n}"), "1.1.1.1")
    assert not findings("shared_ip")
    order(member("two2"), "1.1.1.1")
    order(member("one"), "2.2.2.2")
    [found] = findings("shared_ip")
    assert found.severity == "medium" and "1.1.1.1" in found.title
    assert found.links[0].url.endswith("?od_ip=1.1.1.1")


@pytest.mark.django_db
def test_shared_ip_with_coupon_use_or_signup_coupon_is_high():
    for n in range(3):
        order(member(f"c{n}"), "3.3.3.3", coupon=1000 if n == 0 else 0)
    [found] = findings("shared_ip")
    assert found.severity == "high" and "쿠폰 사용 주문 1건" in found.evidence[2]


@pytest.mark.django_db
def test_shared_ip_counts_signup_coupon_use_from_the_coupon_log():
    users = [member(f"s{n}") for n in range(3)]
    placed = [order(user, "4.4.4.4") for user in users]
    coupon = ShopCoupon.objects.create(user=users[0], cp_subject=SIGNUP_COUPON_SUBJECT, cp_price=3000)
    ShopCouponLog.objects.create(
        cl_id=1, coupon=coupon, cp_id=coupon.cp_id, user=users[0], order=placed[0], od_id=placed[0].od_id, cp_price=3000
    )
    [found] = findings("shared_ip")
    assert found.severity == "high" and "신규 회원 쿠폰 사용 회원 1명" in found.evidence[2]


@pytest.mark.django_db
def test_shared_ip_ignores_orders_outside_the_window_guests_and_missing_ips():
    for n in range(3):
        order(member(f"old{n}"), "5.5.5.5", hours_ago=24 * 40)
    for _ in range(3):
        order(None, "6.6.6.6")
    for n in range(3):
        order(member(f"noip{n}"), None)
    assert not findings("shared_ip")


def test_window_days_accepts_only_the_offered_choices():
    assert [abuse_signals.window_days(v) for v in ("7", "30", "90", "5", "x", None)] == [7, 30, 90, 30, 30, 30]


def staff_with(*codenames):
    user = get_user_model().objects.create_user("staff-" + "-".join(codenames), "s@example.test", "pw", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
    return user


@pytest.mark.django_db
def test_the_page_needs_the_order_view_permission(client):
    url = reverse("admin:shop_shoporder_abuse_signals")
    client.force_login(staff_with("view_shopproduct"))
    assert client.get(url).status_code == 403
    client.force_login(staff_with("view_shoporder"))
    response = client.get(url)
    assert response.status_code == 200
    assert "이상 활동 점검" in response.content.decode() and "걸린 기록이 없습니다" in response.content.decode()


@pytest.mark.django_db
def test_the_page_renders_every_rule_with_rows_and_working_links(client):
    item = product(name="몰린 상품")
    for n in range(6):
        review(item, member(f"p{n}"), hours_ago=1 + n, content=LONG)
    for n in range(3):
        order(member(f"q{n}"), "7.7.7.7", coupon=500)
    client.force_login(staff_with("view_shoporder", "view_shopreview"))
    response = client.get(reverse("admin:shop_shoporder_abuse_signals"), {"days": "90"})
    html = response.content.decode()
    assert response.status_code == 200
    for text in ("후기 몰림", "유사 후기", "배송 완료 이력 없는 후기", "동일 IP 다중 계정", "몰린 상품", "IP 7.7.7.7", "최근 90일"):
        assert text in html
    report = abuse_signals.build_report(90)
    assert report["counts"]["high"] >= 2 and report["total"] == sum(report["counts"].values())
    client.force_login(get_user_model().objects.create_superuser("root", "r@example.test", "pw"))
    for result in report["results"]:
        for found in result.findings:
            for link in found.links:
                assert client.get(link.url).status_code == 200, link.url


@pytest.mark.django_db
def test_the_ip_link_filters_the_order_list(client):
    keep = order(member("k1"), "8.8.8.8")
    drop = order(member("k2"), "9.9.9.9")
    client.force_login(get_user_model().objects.create_superuser("root", "r@example.test", "pw"))
    html = client.get(reverse("admin:shop_shoporder_changelist"), {"od_ip": "8.8.8.8"}).content.decode()
    assert keep.od_id in html and drop.od_id not in html


@pytest.mark.django_db
def test_the_report_runs_a_fixed_number_of_queries_however_many_rows_exist(django_assert_max_num_queries):
    item = product()
    for n in range(20):
        review(item, member(f"qq{n}"), hours_ago=1 + n % 5, content=LONG)
        order(member(f"oo{n}"), "11.11.11.11", coupon=100)
    with django_assert_max_num_queries(14):
        report = abuse_signals.build_report(30, now=NOW)
    assert report["total"] >= 3
