"""The member order list loads its related rows once, however many orders the page holds."""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from gnu_jango.shop.models import ShopReturnRequest
from gnu_jango.testing.factories import ShopOrderFactory, ShopProductFactory


def order_list_queries(member_client):
    with CaptureQueriesContext(connection) as queries:
        response = member_client.get("/api/v1/shop/orders", {"limit": 20})
    assert response.status_code == 200
    return len(response.json()["data"]), len(queries.captured_queries)


def test_the_order_list_query_count_does_not_grow_with_the_orders(member_client, member):
    product = ShopProductFactory()

    def add_order(index):
        order = ShopOrderFactory(user=member, od_id=f"QL-{index}", items=[(product, 2)])
        ShopReturnRequest.objects.create(order=order, user=member, kind="return", reason="defective")

    add_order(0)
    add_order(1)
    two, few_queries = order_list_queries(member_client)
    for index in range(2, 8):
        add_order(index)
    eight, many_queries = order_list_queries(member_client)

    assert (two, eight) == (2, 8)
    assert many_queries == few_queries
