"""factory_boy factories for the models tests build most often.

They replace the hand-written ``Model.objects.create(...)`` blocks repeated across the suite
(products in 40 test modules, orders in 31, members in 57). Every factory produces a row that the
real code accepts with no further setup; pass only what the test is about::

    member = MemberFactory(level=3)
    product = ShopProductFactory(it_price=12000, it_stock_qty=2)
    order = ShopOrderFactory(user=member, items=[(product, 2)])
    post = PostFactory(board__bo_read_level=2)

Points go through the ledger (``give_points``) so the member's balance matches the history rows,
the same as the application code. Works from Django ``TestCase`` classes and from pytest tests
(``conftest.py`` exposes fixtures built on these factories).
"""

from datetime import timedelta

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopOrder, ShopOrderItem, ShopProduct


class MemberFactory(factory.django.DjangoModelFactory):
    """A member with a usable password ``"password"`` and a profile at ``level`` (default 2)."""

    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"member{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.test")
    first_name = factory.LazyAttribute(lambda user: user.username)
    password = factory.django.Password("password")

    @factory.post_generation
    def level(user, create, extracted, **kwargs):
        # the profile row is made by users.models.create_user_profile on save
        if create:
            user.profile.user_level = 2 if extracted is None else extracted
            user.profile.save(update_fields=["user_level"])


class AdminFactory(MemberFactory):
    username = factory.Sequence(lambda n: f"admin{n}")
    is_staff = True
    is_superuser = True
    level = 10


def give_points(user, point, content="Test points"):
    """Grant (or take, if negative) points through the ledger, as the application does."""
    from gnu_jango.users.point_ledger import insert_point

    return insert_point(user, point, content, force=True)


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group
        django_get_or_create = ("gr_id",)

    gr_id = factory.Sequence(lambda n: f"group{n}")
    gr_subject = factory.LazyAttribute(lambda group: group.gr_id.title())
    gr_admin = ""


class BoardFactory(factory.django.DjangoModelFactory):
    """An open board: anyone may list, read, write and comment (levels 1)."""

    class Meta:
        model = Board
        django_get_or_create = ("bo_table",)

    group = factory.SubFactory(GroupFactory)
    bo_table = factory.Sequence(lambda n: f"board{n}")
    bo_subject = factory.LazyAttribute(lambda board: board.bo_table.title())
    bo_skin = "basic"
    bo_mobile_skin = "basic"
    bo_list_level = 1
    bo_read_level = 1
    bo_write_level = 1
    bo_reply_level = 1
    bo_comment_level = 1
    bo_page_rows = 15


class PostFactory(factory.django.DjangoModelFactory):
    """A thread root by a guest unless ``user`` is given; ``wr_num`` keeps Gnuboard ordering."""

    class Meta:
        model = Post
        skip_postgeneration_save = True

    board = factory.SubFactory(BoardFactory)
    user = None
    wr_num = factory.Sequence(lambda n: -(n + 1))
    wr_subject = factory.Sequence(lambda n: f"Post {n}")
    wr_content = "<p>Body</p>"
    wr_slug = factory.Sequence(lambda n: f"post-{n}")
    wr_name = factory.LazyAttribute(lambda post: post.user.username if post.user else "guest")
    wr_ip = "203.0.113.7"
    wr_datetime = factory.LazyFunction(timezone.now)
    wr_last = factory.LazyAttribute(lambda post: post.wr_datetime)

    @factory.post_generation
    def thread(post, create, extracted, **kwargs):
        # a thread root is its own parent (bbs list ordering and replies rely on it)
        if create and not post.wr_parent:
            post.wr_parent = post.pk
            post.save(update_fields=["wr_parent"])


class CommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Comment

    post = factory.SubFactory(PostFactory)
    board = factory.LazyAttribute(lambda comment: comment.post.board)
    user = None
    wr_content = "Comment"
    wr_name = factory.LazyAttribute(lambda comment: comment.user.username if comment.user else "guest")
    wr_ip = "203.0.113.7"
    wr_datetime = factory.LazyFunction(timezone.now)
    wr_last = factory.LazyAttribute(lambda comment: comment.wr_datetime)


class ShopCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShopCategory
        django_get_or_create = ("ca_id",)

    ca_id = factory.Sequence(lambda n: f"{10 + n % 90:02d}")
    ca_name = factory.LazyAttribute(lambda category: f"Category {category.ca_id}")


class ShopProductFactory(factory.django.DjangoModelFactory):
    """An on-sale product in stock, priced 10,000, without options."""

    class Meta:
        model = ShopProduct
        django_get_or_create = ("it_id",)

    it_id = factory.Sequence(lambda n: f"P{n:05d}")
    it_name = factory.Sequence(lambda n: f"Product {n}")
    category = factory.SubFactory(ShopCategoryFactory)
    it_price = 10000
    it_use = "1"
    it_stock_qty = 100


class ShopOrderFactory(factory.django.DjangoModelFactory):
    """An unpaid bank-transfer order.

    ``items=[(product, qty), ...]`` adds lines priced from each product and sets the order totals
    (``od_cart_price``/``od_misu``) to match, so the order is consistent for payment code.
    """

    class Meta:
        model = ShopOrder
        django_get_or_create = ("od_id",)
        skip_postgeneration_save = True

    od_id = factory.Sequence(lambda n: f"{2026102800000000 + n}")
    user = None
    od_name = factory.LazyAttribute(lambda order: order.user.username if order.user else "Guest buyer")
    od_email = factory.LazyAttribute(lambda order: order.user.email if order.user else "guest@example.test")
    od_hp = "010-0000-0000"
    od_settle_case = "무통장"

    @factory.post_generation
    def items(order, create, extracted, **kwargs):
        if not create or not extracted:
            return
        total = 0
        for index, (product, qty) in enumerate(extracted, start=1):
            ShopOrderItemFactory(order=order, product=product, ct_qty=qty, ct_id=f"{order.od_id}-{index}")
            total += product.it_price * qty
        order.od_cart_price = total
        order.od_misu = total
        order.save(update_fields=["od_cart_price", "od_misu"])


class ShopOrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ShopOrderItem

    order = factory.SubFactory(ShopOrderFactory)
    product = factory.SubFactory(ShopProductFactory)
    ct_id = factory.Sequence(lambda n: f"CT{n:06d}")
    it_id = factory.LazyAttribute(lambda item: item.product.it_id)
    it_name = factory.LazyAttribute(lambda item: item.product.it_name)
    ct_price = factory.LazyAttribute(lambda item: item.product.it_price)
    ct_qty = 1
    ct_status = factory.LazyAttribute(lambda item: item.order.od_status)


class ShopCouponFactory(factory.django.DjangoModelFactory):
    """A 3,000 won whole-order coupon (cp_method 2), valid from yesterday for ten days."""

    class Meta:
        model = ShopCoupon

    user = None
    cp_subject = "Test coupon"
    cp_method = 2
    cp_type = 0
    cp_price = 3000
    cp_minimum = 0
    cp_start = factory.LazyFunction(lambda: timezone.localdate() - timedelta(days=1))
    cp_end = factory.LazyFunction(lambda: timezone.localdate() + timedelta(days=10))
