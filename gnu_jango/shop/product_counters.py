"""The counters a product row keeps for listing and sorting (youngcart g5_shop_item).

- it_use_cnt / it_use_avg: the number and the average score of the product's published reviews
  (youngcart lib/shop.lib.php update_use_cnt / update_use_avg, ``is_confirm = 1``), behind the
  후기많은순 / 평점높은순 sorts.
- it_sum_qty: the quantity sold, the sum of the product's 완료 order lines (youngcart
  orderlistupdate.php), behind 판매많은순.

Each recount works from the source rows, so calling it again (or after any change: a review
written, edited, approved, hidden or deleted; a line completed, cancelled or returned) is safe.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count, Sum

from .models import ShopOrderItem, ShopProduct, ShopReview

REVIEW_PUBLISHED = "1"
STATUS_COMPLETED = "완료"
AVERAGE_STEP = Decimal("0.1")  # it_use_avg is DECIMAL(2,1)


def _product_ids(it_ids):
    """The distinct non-empty product ids in ``it_ids`` (None: every product)."""
    if it_ids is None:
        return list(ShopProduct.objects.values_list("pk", flat=True))
    return sorted({str(it_id) for it_id in it_ids if it_id})


def _review_average(value):
    if not value:
        return Decimal("0.0")
    return Decimal(str(value)).quantize(AVERAGE_STEP, rounding=ROUND_HALF_UP)


def recount_product_reviews(it_ids=None):
    """Store it_use_cnt and it_use_avg of the products ``it_ids`` (None: all); returns how many
    product rows were updated."""
    ids = _product_ids(it_ids)
    if not ids:
        return 0
    stats = {
        row["product_id"]: row
        for row in ShopReview.objects.filter(product_id__in=ids, is_confirm=REVIEW_PUBLISHED)
        .values("product_id")
        .annotate(count=Count("pk"), average=Avg("is_score"))
    }
    updated = 0
    for product_id in ids:
        row = stats.get(product_id, {})
        updated += ShopProduct.objects.filter(pk=product_id).update(
            it_use_cnt=row.get("count") or 0,
            it_use_avg=_review_average(row.get("average")),
        )
    return updated


def recount_product_sales(it_ids=None):
    """Store it_sum_qty, the quantity of the 완료 order lines, of the products ``it_ids`` (None:
    all); returns how many product rows were updated. A line leaving 완료 (cancelled or returned)
    drops out of the count the next time this runs for its product."""
    ids = _product_ids(it_ids)
    if not ids:
        return 0
    sold = dict(
        ShopOrderItem.objects.filter(product_id__in=ids, ct_status=STATUS_COMPLETED)
        .values("product_id")
        .annotate(qty=Sum("ct_qty"))
        .values_list("product_id", "qty")
    )
    updated = 0
    for product_id in ids:
        updated += ShopProduct.objects.filter(pk=product_id).update(it_sum_qty=max(0, sold.get(product_id) or 0))
    return updated
