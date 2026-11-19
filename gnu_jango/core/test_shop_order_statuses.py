from datetime import datetime
from itertools import count

import pytest
from django.utils import timezone

from gnu_jango.shop.models import ShopOrder, ShopOrderItem
from gnu_jango.shop.order_statuses import sold_line_q

_ids = count(1)


def line(status, qty):
    order = ShopOrder.objects.create(
        od_id=f"{20261109000000 + next(_ids)}", od_name="홍길동", od_email="b@example.test", od_hp="010-0000-0000",
        od_datetime=timezone.make_aware(datetime(2026, 11, 8, 12)), od_status=status,
    )
    ShopOrderItem.objects.create(order=order, ct_id=str(next(_ids)), it_id="Q1", it_name="상품", ct_qty=qty, ct_status=status)


@pytest.mark.django_db
def test_sold_lines_leave_out_every_spelling_of_cancelled_returned_and_sold_out():
    for status in ("취소", "cancel", "cancelled", "canceled", "반품", "return", "returned", "품절"):
        line(status, 5)
    line("paid", 2)
    line("완료", 3)
    assert sorted(ShopOrderItem.objects.filter(sold_line_q()).values_list("ct_qty", flat=True)) == [2, 3]


@pytest.mark.django_db
def test_order_totals_leave_out_every_spelling_the_sales_reports_leave_out():
    from gnu_jango.shop.order_lines import active_line_ids

    order = ShopOrder.objects.create(
        od_id=f"{20261109000000 + next(_ids)}", od_name="홍길동", od_email="b@example.test", od_hp="010-0000-0000",
        od_datetime=timezone.make_aware(datetime(2026, 11, 8, 12)), od_status="입금",
    )
    for status in ("canceled", "return", "returned", "취소", "입금"):
        ShopOrderItem.objects.create(order=order, ct_id=str(next(_ids)), it_id="Q1", it_name=status, ct_qty=1, ct_status=status)

    kept = ShopOrderItem.objects.filter(pk__in=active_line_ids(order)).values_list("it_name", flat=True)
    sold = ShopOrderItem.objects.filter(order=order).filter(sold_line_q()).values_list("it_name", flat=True)
    assert list(kept) == ["입금"]
    assert sorted(kept) == sorted(sold)
