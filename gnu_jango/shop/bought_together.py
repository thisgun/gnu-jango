"""함께 구매한 상품: the products most often in the same orders as a product, from order history."""
import logging
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Max, Subquery
from django.utils import timezone

from gnu_jango.shop.models import ShopOrderItem
from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES
from gnu_jango.utils.date_ranges import local_days

logger = logging.getLogger(__name__)
BOUGHT_TOGETHER_LIMIT = 4
WINDOW_DAYS = 365
MIN_SHARED_ORDERS = 2
PARTNER_POOL = 30
PARTNER_CACHE_SECONDS = 60 * 60


def bought_together(product, base, *, exclude=(), limit=BOUGHT_TOGETHER_LIMIT):
    """Up to ``limit`` products of ``base`` bought with ``product``, most shared orders first."""
    skip = {str(product.pk), *(str(item) for item in exclude)}
    ranked = [it_id for it_id in _partner_ids(str(product.pk)) if it_id not in skip]
    if not ranked or limit <= 0:
        return []
    allowed = {item.pk: item for item in base.filter(pk__in=ranked)}
    return [allowed[it_id] for it_id in ranked if it_id in allowed][:limit]


def ranked_partner_ids(it_id):
    """Product ids sharing MIN_SHARED_ORDERS+ counted orders with ``it_id`` in WINDOW_DAYS local days."""
    today = timezone.localdate()
    window = local_days("order__od_datetime", today - timedelta(days=WINDOW_DAYS - 1), today)
    counted = ShopOrderItem.objects.filter(window).exclude(ct_status__in=INACTIVE_LINE_STATUSES)
    orders = counted.filter(it_id=it_id).values("order_id")
    rows = (
        counted.filter(order_id__in=Subquery(orders))
        .exclude(it_id=it_id)
        .values("it_id")
        .annotate(shared=Count("order_id", distinct=True), latest=Max("order__od_datetime"))
        .filter(shared__gte=MIN_SHARED_ORDERS)
        .order_by("-shared", "-latest", "it_id")
        .values_list("it_id", flat=True)
    )
    return list(rows[:PARTNER_POOL])


def _partner_ids(it_id):
    key = f"shop:bought-together:v1:{it_id}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    partners = ranked_partner_ids(it_id)
    try:
        cache.set(key, partners, PARTNER_CACHE_SECONDS)
    except Exception:
        logger.warning("Bought-together products not cached.", exc_info=True)
    return partners
