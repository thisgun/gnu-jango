"""The shared factories build rows the real API accepts (pytest-style; see conftest.py)."""

import pytest

from gnu_jango.testing.factories import (
    BoardFactory,
    CommentFactory,
    MemberFactory,
    PostFactory,
    ShopCouponFactory,
    ShopOrderFactory,
    ShopProductFactory,
    give_points,
)
from gnu_jango.users.point_ledger import point_balance

pytestmark = pytest.mark.django_db


def test_a_member_has_a_profile_level_and_a_usable_password(client):
    member = MemberFactory(level=5)

    assert member.profile.user_level == 5
    assert client.login(username=member.username, password="password")


def test_points_go_through_the_ledger(member):
    give_points(member, 1500)
    give_points(member, -500)

    assert point_balance(member) == 1000
    member.profile.refresh_from_db()
    assert member.profile.user_point == 1000


def test_a_post_and_comment_are_listed_and_readable(api_client):
    post = PostFactory(board__bo_table="factory-board")
    CommentFactory(post=post)

    listed = api_client.get("/api/v1/boards/factory-board/posts").json()
    detail = api_client.get(f"/api/v1/posts/factory-board/{post.pk}").json()["data"]

    assert [row["id"] for row in listed["data"]] == [post.pk]
    assert len(detail["comments"]) == 1


def test_a_board_respects_its_read_level(api_client, member_client):
    post = PostFactory(board=BoardFactory(bo_table="members-only", bo_read_level=2))
    url = f"/api/v1/posts/members-only/{post.pk}"

    # an unreadable post is not revealed to guests; a level-2 member reads it
    assert api_client.get(url).status_code == 404
    assert member_client.get(url).status_code == 200


def test_a_product_is_on_sale(api_client):
    product = ShopProductFactory(it_price=12000)

    rows = api_client.get("/api/v1/shop/products").json()["data"]

    assert [(row["it_id"], row["it_price"]) for row in rows] == [(product.it_id, 12000)]


def test_an_order_with_items_has_matching_totals_and_is_the_members(member, member_client):
    first, second = ShopProductFactory(it_price=10000), ShopProductFactory(it_price=2500)

    order = ShopOrderFactory(user=member, items=[(first, 2), (second, 1)])

    assert order.od_cart_price == order.od_misu == 22500
    assert order.items.count() == 2
    listed = member_client.get("/api/v1/shop/orders").json()["data"]
    assert [row["od_id"] for row in listed] == [order.od_id]


def test_a_coupon_is_currently_valid(member):
    coupon = ShopCouponFactory(user=member)

    assert coupon.cp_start < coupon.cp_end
    assert coupon.cp_id
