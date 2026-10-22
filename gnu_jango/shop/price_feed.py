"""가격비교 상품목록 (youngcart adm/shop_admin/price.php, shop/price/naver.php).

A Naver Shopping EP 3.0 feed: one tab-separated line per product with youngcart's columns (id,
title, price_pc, link, image_link, category_name1-4, brand, maker, origin, point, review_count,
shipping, class, update_time). As in naver.php only products on sale (it_use 1), not 품절, not
전화문의 and with a price are listed; a product whose stock ran out is left out too, so a
comparison site never sends a buyer to something that cannot be ordered.

The feed is off until the admin turns it on (Config row ``de_price_compare_use``) and is cached:
it covers every product and a comparison site fetches it often. Saving or deleting a product or a
category starts a new cache generation; one request rebuilds it under a short build lock while
the others are served the previous text, and each address may fetch the feed only so often.
"""

import time
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from gnu_jango.config.models import Config
from gnu_jango.utils.lib import get_client_ip

from .models import ShopCategory, ShopProduct
from .order_points import item_purchase_point
from .payment_options import config_flag
from .shipping import SC_METHOD_ON_DELIVERY, base_shipping_cost, current_shipping_policy

ENABLED_CONFIG = "de_price_compare_use"
CACHE_KEY = "shop:price-feed:naver:v1:{generation}:{base}"
# the last text built for a host, served while a new generation is being built
STALE_KEY = "shop:price-feed:naver:stale:{base}"
GENERATION_KEY = "shop:price-feed:naver:generation"
LOCK_KEY = "shop:price-feed:naver:lock:{generation}:{base}"
THROTTLE_KEY = "shop:price-feed:naver:hits:{ip}:{bucket}"
CACHE_SECONDS = 30 * 60
STALE_SECONDS = 24 * 60 * 60
LOCK_SECONDS = 120
THROTTLE_WINDOW_SECONDS = 10 * 60
THROTTLE_LIMIT = 30  # fetches per address per window; comparison sites fetch a few times an hour
RETRY_AFTER_SECONDS = 30
CATEGORY_LEVEL_LENGTH = 2  # youngcart ca_id: two characters per level
COLUMNS = (
    "id", "title", "price_pc", "link", "image_link", "category_name1", "category_name2",
    "category_name3", "category_name4", "brand", "maker", "origin", "point", "review_count",
    "shipping", "class", "update_time",
)
ON_DELIVERY = -1  # EP 3.0: 착불


def feed_enabled():
    return config_flag(Config.objects.filter(name=ENABLED_CONFIG).values_list("value", flat=True).first() or "")


def set_feed_enabled(enabled):
    Config.objects.update_or_create(name=ENABLED_CONFIG, defaults={"value": "1" if enabled else "0"})
    clear_feed_cache()


def site_base(request=None):
    """The public origin product links point to (SOCIAL_APP_BASE_URL, else the request host)."""
    base = str(getattr(settings, "SOCIAL_APP_BASE_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    return request.build_absolute_uri("/").rstrip("/") if request is not None else ""


def _generation():
    return cache.get(GENERATION_KEY) or 0


def clear_feed_cache(request=None):
    """Start a new cache generation, so every host form of the feed is rebuilt on its next fetch
    (``request`` is accepted for the callers that pass it)."""
    cache.set(GENERATION_KEY, time.time_ns(), None)


def clear_feed_cache_on_change(sender, **kwargs):
    """post_save / post_delete of a product or a category (registered in shop/apps.py)."""
    if kwargs.get("raw"):
        return
    clear_feed_cache()


def _clean(value):
    return " ".join(str(value if value is not None else "").replace("\t", " ").split())


def _absolute(url, base):
    from gnu_jango.api.shop_common import legacy_shop_asset_url

    url = legacy_shop_asset_url(str(url or "").strip())
    if not url or url.lower().startswith(("http://", "https://")):
        return url
    return f"{base}{url}" if url.startswith("/") and not url.startswith("//") else ""


def _category_names(product, names):
    """The names of the four youngcart category levels of the product's 기본분류."""
    ca_id = str(product.category_id or "")
    levels = []
    for depth in range(1, 5):
        length = depth * CATEGORY_LEVEL_LENGTH
        levels.append(names.get(ca_id[:length], "") if len(ca_id) >= length else "")
    return levels


def item_shipping(product, policy):
    """youngcart get_item_sendcost2 for one unit at the sale price; -1 when paid on delivery."""
    sc_type = int(product.it_sc_type or 0)
    price = int(product.it_price or 0)
    if sc_type == 0:
        return base_shipping_cost(price, policy)
    if sc_type == 1:
        return 0
    if int(product.it_sc_method or 0) == SC_METHOD_ON_DELIVERY:
        return ON_DELIVERY
    if sc_type == 2:
        return 0 if price >= int(product.it_sc_minimum or 0) else int(product.it_sc_price or 0)
    return int(product.it_sc_price or 0)


def _has_stock(product):
    choices = [
        option for option in (product.options if isinstance(product.options, list) else [])
        if isinstance(option, dict) and str(option.get("io_id") or "").strip() and int(option.get("io_type") or 0) == 0
    ]
    if choices:
        return any(
            int(option.get("io_use") if option.get("io_use") is not None else 1) == 1
            and int(option.get("io_stock_qty") or 0) > 0
            for option in choices
        )
    return int(product.it_stock_qty or 0) > 0


def feed_products():
    """The products the feed lists, in youngcart's order (by category)."""
    hidden_categories = set(ShopCategory.objects.filter(ca_use=False).values_list("pk", flat=True))
    products = (
        ShopProduct.objects.filter(it_use="1", it_price__gt=0)
        .exclude(it_soldout="1")
        .exclude(it_tel_inq="1")
        .order_by("category_id", "it_id")
    )
    return [
        product for product in products.iterator(chunk_size=500)
        if product.category_id not in hidden_categories and _has_stock(product)
    ]


def build_feed(base):
    names = dict(ShopCategory.objects.values_list("ca_id", "ca_name"))
    policy = current_shipping_policy()
    today = timezone.localdate()
    lines = ["\t".join(COLUMNS)]
    for product in feed_products():
        created = timezone.localtime(product.created_at).date() if product.created_at else None
        updated = product.it_update_time or product.updated_at
        values = [
            product.it_id,
            product.it_name,
            product.it_price,
            f"{base}/shop/{quote(product.it_id, safe='')}",
            _absolute(product.image_url, base),
            *_category_names(product, names),
            product.it_brand,
            product.it_maker,
            product.it_origin,
            item_purchase_point(product),
            int(product.it_use_cnt or 0),
            item_shipping(product, policy),
            "I" if created == today else "U",
            timezone.localtime(updated).strftime("%Y-%m-%d %H:%M:%S") if updated else "",
        ]
        lines.append("\t".join(_clean(value) for value in values))
    return "\n".join(lines) + "\n"


def feed_text(request=None):
    """The feed text, or None while another request builds it and no earlier text is kept."""
    base = site_base(request)
    generation = _generation()
    key = CACHE_KEY.format(generation=generation, base=base)
    text = cache.get(key)
    if text is not None:
        return text
    lock = LOCK_KEY.format(generation=generation, base=base)
    if not cache.add(lock, "1", LOCK_SECONDS):
        # another request is building this generation: hand out the previous text meanwhile
        return cache.get(STALE_KEY.format(base=base))
    try:
        text = build_feed(base)
        cache.set(key, text, CACHE_SECONDS)
        cache.set(STALE_KEY.format(base=base), text, STALE_SECONDS)
    finally:
        cache.delete(lock)
    return text


def _throttled(request):
    bucket = int(time.time() // THROTTLE_WINDOW_SECONDS)
    key = THROTTLE_KEY.format(ip=get_client_ip(request) or "-", bucket=bucket)
    cache.add(key, 0, THROTTLE_WINDOW_SECONDS + 60)
    try:
        return cache.incr(key) > THROTTLE_LIMIT
    except ValueError:  # expired between add and incr
        return False


def _retry_later(message, status):
    response = HttpResponse(message, status=status, content_type="text/plain; charset=utf-8")
    response["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return response


@require_GET
def naver_feed_view(request):
    if not feed_enabled():
        raise Http404
    if _throttled(request):
        return _retry_later("Too many requests.\n", 429)
    text = feed_text(request)
    if text is None:
        return _retry_later("The feed is being built. Retry shortly.\n", 503)
    response = HttpResponse(text, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    response["X-Robots-Tag"] = "noindex"
    return response
