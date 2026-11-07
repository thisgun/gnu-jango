"""함께 구매한 상품, counted by distinct paid buyers so a product page never reveals one shopper's basket."""
import logging
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Case, CharField, Count, Max, Subquery, Value, When
from django.db.models.functions import Cast, Concat, Lower, Replace, Substr, Trim
from django.db.models.lookups import Exact
from django.utils import timezone

from gnu_jango.api.shop_common import PAID_STATUSES
from gnu_jango.shop.admin._common import sold_line_q
from gnu_jango.shop.models import ShopOrderItem
from gnu_jango.utils.date_ranges import local_days

logger = logging.getLogger(__name__)
BOUGHT_TOGETHER_LIMIT = 4
WINDOW_DAYS = 365
PRIVACY_MIN_BUYERS = 3
PHONE_SEPARATORS = ("-", " ", ".", "(", ")", "\t")
PARTNER_POOL = 60
PARTNER_CACHE_SECONDS = 60 * 60


def bought_together(product, base, *, exclude=(), limit=BOUGHT_TOGETHER_LIMIT):
    skip = {str(product.pk), *(str(item) for item in exclude)}
    ranked = [it_id for it_id in _partner_ids(str(product.pk)) if it_id not in skip]
    if not ranked or limit <= 0:
        return []
    in_stock = base.filter(pk__in=ranked, it_stock_qty__gt=0).exclude(it_soldout="1")
    allowed = {item.pk: item for item in in_stock}
    return [allowed[it_id] for it_id in ranked if it_id in allowed][:limit]


def buyer_key():
    email = Lower(Trim("order__od_email"))
    hp = _phone_key()
    return Case(
        When(order__user_id__isnull=False, then=Concat(Value("m:"), Cast("order__user_id", CharField()))),
        When(~Exact(email, Value("")), then=Concat(Value("e:"), email)),
        When(~Exact(hp, Value("")), then=Concat(Value("h:"), hp)),
        default=Value(None),
        output_field=CharField(),
    )


def _phone_key():
    digits = "order__od_hp"
    for separator in PHONE_SEPARATORS:
        digits = Replace(digits, Value(separator), Value(""))
    return Case(
        When(Exact(Substr(digits, 1, 3), Value("+82")), then=Concat(Value("0"), Substr(digits, 4))),
        default=digits,
        output_field=CharField(),
    )


def ranked_partner_ids(it_id):
    today = timezone.localdate()
    window = local_days("order__od_datetime", today - timedelta(days=WINDOW_DAYS - 1), today)
    sold = ShopOrderItem.objects.filter(window, sold_line_q(), order__od_status__in=PAID_STATUSES)
    orders = sold.filter(it_id=it_id).values("order_id")
    rows = (
        sold.filter(order_id__in=Subquery(orders))
        .exclude(it_id=it_id)
        .values("it_id")
        .annotate(buyers=Count(buyer_key(), distinct=True), latest=Max("order__od_datetime"))
        .filter(buyers__gte=PRIVACY_MIN_BUYERS)
        .order_by("-buyers", "-latest", "it_id")
        .values_list("it_id", flat=True)
    )
    return list(rows[:PARTNER_POOL])


def _partner_ids(it_id):
    key = f"shop:bought-together:v2:{it_id}"
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
