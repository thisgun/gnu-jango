import math
from datetime import date, datetime, timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder, ShopOrderItem, ShopProduct
from gnu_jango.shop.stock_forecast import (
    NO_SALES,
    STATUS_RULES,
    Settings,
    forecast_all,
    forecast_product,
    parse_settings,
    sales_series,
    status_counts,
    urgency_key,
)

SETTINGS = Settings(window=28, lead_days=7, cover_days=14)
TODAY = date(2026, 11, 7)
_ids = count(1)
NOISY = [2, 6] * 14


def forecast(stock, series, settings=SETTINGS):
    return forecast_product("A1", "상품", stock, series, settings)


def test_a_product_without_sales_has_no_days_left_and_no_order():
    result = forecast(50, [0] * 28)
    assert result.status == NO_SALES
    assert result.days_left is None and result.reorder_point is None and result.suggested == 0


def test_steady_sales_follow_the_formulas():
    result = forecast(100, [4] * 28)
    assert result.daily == 4 and result.days_left == 25
    assert result.reorder_point == 4 * 7
    assert result.suggested == max(0, math.ceil(4 * 21 - 100))
    assert result.status == "여유" and result.trend == "flat"


def test_a_steady_product_below_its_reorder_point_needs_an_order():
    result = forecast(30, NOISY)
    assert result.status == "발주 필요"
    assert result.suggested == math.ceil(84 + 1.65 * _sample_stdev(NOISY) * math.sqrt(7) - 30)


def test_stock_for_less_than_the_lead_time_is_about_to_run_out():
    result = forecast(20, [4] * 28)
    assert result.days_left == 5 and result.status == "품절 임박"


def test_a_sold_out_product_with_recent_sales_is_out_of_stock_and_asks_for_the_full_cover():
    result = forecast(0, [4] * 28)
    assert result.status == "품절" and result.days_left == 0 and result.suggested == 84
    assert forecast(-3, [4] * 28).days_left == 0


def test_a_burst_raises_the_safety_stock_and_shows_as_a_rising_trend():
    series = [0] * 21 + [10] * 7
    result = forecast(10, series)
    assert result.trend == "up" and result.recent_units == 70
    steady = forecast(10, [2.5] * 28)
    assert result.reorder_point > steady.reorder_point
    assert result.reorder_point == pytest.approx(2.5 * 7 + 1.65 * _sample_stdev(series) * math.sqrt(7))


def test_falling_sales_are_flagged_as_a_falling_trend():
    assert forecast(500, [6] * 21 + [1] * 7).trend == "down"


def test_lead_and_cover_days_change_the_suggestion():
    short = forecast(0, [2] * 28, Settings(28, 2, 3))
    long = forecast(0, [2] * 28, Settings(28, 10, 30))
    assert (short.suggested, long.suggested) == (10, 80)


def test_each_status_rule_is_reachable_and_ordered_by_urgency():
    labels = [rule.label for rule in STATUS_RULES]
    assert labels == ["품절", "품절 임박", "발주 필요", "여유"]
    rows = [forecast(stock, NOISY) for stock in (500, 30, 20, 0)] + [forecast(5, [0] * 28)]
    assert [row.status for row in sorted(rows, key=urgency_key)] == [*labels, NO_SALES]
    assert status_counts(rows) == {"품절": 1, "품절 임박": 1, "발주 필요": 1, "여유": 1, NO_SALES: 1}


def test_parse_settings_clamps_and_falls_back():
    assert parse_settings({}) == Settings(28, 7, 14)
    assert parse_settings({"window": "56", "lead": "999", "cover": "0"}) == Settings(56, 60, 1)
    assert parse_settings({"window": "30", "lead": "x", "cover": ""}) == Settings(28, 7, 14)


def _sample_stdev(series):
    average = sum(series) / len(series)
    return math.sqrt(sum((value - average) ** 2 for value in series) / (len(series) - 1))


def make_product(it_id, stock, name="상품", use="1"):
    return ShopProduct.objects.create(it_id=it_id, it_name=name, it_stock_qty=stock, it_use=use)


def sell(product, day, qty, status="완료"):
    moment = timezone.make_aware(datetime(day.year, day.month, day.day, 12))
    order = ShopOrder.objects.create(
        od_id=f"{20261100000000 + next(_ids)}", od_name="홍길동", od_email="b@example.test", od_hp="010-0000-0000",
        od_datetime=moment, od_status=status,
    )
    ShopOrderItem.objects.create(
        order=order, product=product, ct_id=str(next(_ids)), it_id=product.it_id, it_name=product.it_name,
        ct_qty=qty, ct_status=status,
    )


@pytest.mark.django_db
def test_sales_series_counts_finished_local_days_and_skips_inactive_lines():
    product = make_product("S1", 10)
    sell(product, TODAY - timedelta(days=1), 3)
    sell(product, TODAY - timedelta(days=1), 2, status="입금")
    sell(product, TODAY - timedelta(days=2), 9, status="취소")
    sell(product, TODAY, 7)
    sell(product, TODAY - timedelta(days=29), 5)
    series = sales_series(TODAY, 28)["S1"]
    assert len(series) == 28 and series[-1] == 5 and sum(series) == 5


@pytest.mark.django_db
def test_forecast_all_lists_products_on_sale_most_urgent_first():
    out = make_product("F1", 0, "품절품")
    fine = make_product("F2", 900, "넉넉")
    make_product("F3", 5, "안 팔림")
    make_product("F4", 5, "판매중지", use="0")
    for offset in range(1, 15):
        sell(out, TODAY - timedelta(days=offset), 2)
        sell(fine, TODAY - timedelta(days=offset), 1)
    result = forecast_all(TODAY, SETTINGS)
    assert [(row.it_id, row.status) for row in result] == [("F1", "품절"), ("F2", "여유"), ("F3", NO_SALES)]


def staff_with(*codenames):
    user = get_user_model().objects.create_user("fc-" + "-".join(codenames), "s@example.test", "pw", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
    return user


@pytest.mark.django_db
def test_the_admin_page_renders_with_rows_filters_and_links(client):
    today = timezone.localdate()
    product = make_product("V1", 4, "곧 품절")
    make_product("V2", 40, "안 팔림")
    for offset in range(1, 15):
        sell(product, today - timedelta(days=offset), 3)
    url = reverse("admin:shop_shopproduct_stock_forecast")
    client.force_login(staff_with("view_shopproduct"))
    page = client.get(url, {"window": "14", "lead": "5", "cover": "10"})
    body = page.content.decode()
    assert page.status_code == 200 and "곧 품절" in body and "안 팔림" in body
    assert "품절 임박" in body and "판매 없음" in body
    assert reverse("admin:shop_shopproduct_stock_list") in body
    only = client.get(url, {"status": "판매 없음"}).content.decode()
    assert "안 팔림" in only and "곧 품절" not in only
    assert reverse("admin:shop_shopproduct_stock_forecast") in client.get(reverse("admin:shop_shopproduct_stock_list")).content.decode()


@pytest.mark.django_db
def test_the_admin_page_needs_the_product_view_permission(client):
    url = reverse("admin:shop_shopproduct_stock_forecast")
    client.force_login(staff_with("view_shoporder"))
    assert client.get(url).status_code == 403
