"""Related products (youngcart g5_shop_item_relation)."""

import logging

from django.db import transaction
from django.db.models import Max

from gnu_jango.shop.models import ShopProductRelation

logger = logging.getLogger(__name__)


def related_product_ids(it_id):
    """The related product ids of a product in ir_no order."""
    return list(
        ShopProductRelation.objects.filter(product_id=it_id).order_by("ir_no", "pk").values_list("related_id", flat=True)
    )


@transaction.atomic
def mirror_product_relations(product):
    """Keep the reverse direction in step with ``product``'s own list, like itemformupdate.php.

    Every product listed on ``product`` lists it back (added after its own related products), and a
    product no longer listed stops listing it."""
    listed = set(ShopProductRelation.objects.filter(product=product).values_list("related_id", flat=True))
    stale = ShopProductRelation.objects.filter(related=product).exclude(product_id__in=listed)
    dropped = sorted(stale.values_list("product_id", flat=True))
    if dropped:
        stale.delete()
        logger.info("Related products of %s: %s no longer list it (mirrored)", product.pk, ", ".join(dropped))
    present = set(ShopProductRelation.objects.filter(related=product).values_list("product_id", flat=True))
    missing = sorted(listed - present)
    if not missing:
        return
    last_numbers = dict(
        ShopProductRelation.objects.filter(product_id__in=missing)
        .values("product_id")
        .annotate(last=Max("ir_no"))
        .values_list("product_id", "last")
    )
    ShopProductRelation.objects.bulk_create(
        [
            ShopProductRelation(product_id=other, related=product, ir_no=(last_numbers.get(other) or 0) + 1)
            for other in missing
        ],
        ignore_conflicts=True,
    )


def replace_product_relations(product, related_ids):
    """Set ``product``'s own related list (one direction), skipping itself, repeats and unknown ids."""
    from gnu_jango.shop.models import ShopProduct

    wanted = []
    for it_id in related_ids:
        it_id = str(it_id or "").strip()
        if it_id and it_id != product.it_id and it_id not in wanted:
            wanted.append(it_id)
    known = set(ShopProduct.objects.filter(pk__in=wanted).values_list("it_id", flat=True))
    with transaction.atomic():
        ShopProductRelation.objects.filter(product=product).delete()
        ShopProductRelation.objects.bulk_create(
            [
                ShopProductRelation(product=product, related_id=it_id, ir_no=number)
                for number, it_id in enumerate((it_id for it_id in wanted if it_id in known), 1)
            ]
        )
