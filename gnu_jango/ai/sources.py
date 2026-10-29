"""What gets embedded: handbook chapters and on-sale products.

Secret posts and products that are not on sale are never sent to the endpoint. Read levels are
not decided here; search checks the live board permissions of the person asking.
"""
from gnu_jango.api.shop_common import on_sale_products
from gnu_jango.bbs.models import Post
from gnu_jango.docs_search.service import _book_label, docs_group_id
from gnu_jango.site_search.indexing import plain_text

from . import conf
from .models import Embedding


def _trim(parts):
    text = "\n".join(part for part in (" ".join(str(item or "").split()) for item in parts) if part)
    return text[:conf.max_chars()]


def docs_posts():
    """The chapters handbook search reads: thread roots of searchable boards in the docs group."""
    group = docs_group_id()
    if not group:
        return Post.objects.none()
    return (
        Post.objects.filter(board__group__gr_id=group, board__bo_use_search=True, wr_reply="")
        .exclude(wr_option__contains="secret")
        .select_related("board")
    )


def docs_text(post):
    return _trim((
        _book_label(post.board.bo_subject, post.board.bo_table),
        post.ca_name,
        post.wr_subject,
        plain_text(post.wr_content),
    ))


def products():
    return on_sale_products().select_related("category")


def product_text(product):
    category = getattr(product, "category", None)
    return _trim((
        product.it_name,
        " ".join(filter(None, (product.it_brand, product.it_maker, product.it_model))),
        category.ca_name if category else "",
        plain_text(product.it_basic),
        plain_text(product.it_explan),
    ))


def eligible(kind):
    """Yield ``(object_id, text, board_id)`` for every row that should have an embedding."""
    if kind == Embedding.KIND_DOCS:
        posts = docs_posts().only(
            "pk", "board_id", "ca_name", "wr_subject", "wr_content", "board__bo_subject", "board__bo_table",
        )
        for post in posts.order_by("pk").iterator(chunk_size=200):
            text = docs_text(post)
            if text:
                yield str(post.pk), text, post.board_id
        return
    if kind == Embedding.KIND_PRODUCT:
        for product in products().order_by("pk").iterator(chunk_size=200):
            text = product_text(product)
            if text:
                yield str(product.pk), text, None
        return
    raise ValueError(f"Unknown embedding kind: {kind}")

