"""Coupon rules of the shop: validity, matching and discount amounts."""


from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopProduct,
)


from .shop_common import (
    safe_int,
)


def coupon_raw_discount(coupon, amount, *, minimum_base=None):
    """YoungCart's coupon amount on ``amount`` before it is held to ``amount``: 0 below cp_minimum,
    else the rate (floored to cp_trunc) or the fixed price, capped by cp_maximum.

    ``minimum_base`` (default: ``amount``) is what cp_minimum is compared with - a shipping coupon
    discounts the shipping fee but its minimum is the order amount."""
    amount = max(0, safe_int(amount, 0))
    base = amount if minimum_base is None else max(0, safe_int(minimum_base, 0))
    if amount <= 0 or base < coupon.cp_minimum:
        return 0
    if coupon.cp_type == 1:
        discount = (amount * coupon.cp_price) // 100
        if coupon.cp_trunc > 1:
            discount = (discount // coupon.cp_trunc) * coupon.cp_trunc
    else:
        discount = coupon.cp_price
    if coupon.cp_maximum > 0:
        discount = min(discount, coupon.cp_maximum)
    return max(0, discount)


def coupon_discount(coupon, amount, *, minimum_base=None):
    """The discount on ``amount``, never more than ``amount`` (how YoungCart treats a shipping
    coupon); see coupon_raw_discount."""
    amount = max(0, safe_int(amount, 0))
    return min(amount, coupon_raw_discount(coupon, amount, minimum_base=minimum_base))


def coupon_exceeds_base(coupon, base):
    """True when the coupon would discount more than ``base``. YoungCart refuses such a product or
    order coupon (orderformupdate.php ``if($item_price < $dc) continue`` / ``die('Order coupon
    error.')``) instead of shrinking it to the amount."""
    return coupon_raw_discount(coupon, base) > max(0, safe_int(base, 0))


def product_line_totals(items):
    """Sum of line_total per it_id: the amount a product coupon is judged on.

    YoungCart orderformupdate.php / orderitemcoupon.php add up every cart line of the product,
    ``IF(io_type = 1, io_price * ct_qty, (ct_price + io_price) * ct_qty)``, which is line_total."""
    totals = {}
    for item in items:
        it_id = str(item.get("it_id") or "")
        totals[it_id] = totals.get(it_id, 0) + max(0, safe_int(item.get("line_total"), 0))
    return totals


def product_coupon_entries(user, items):
    """``(it_id, coupon, discount)`` for the product and category coupons in the cart that are still
    valid at order time.

    The cart only remembers which coupon was picked and the discount it showed then; the coupon may
    have expired, been used elsewhere or never matched the item, and one coupon counts once. Like
    YoungCart orderformupdate.php a product takes one coupon, judged on the total of all its lines,
    and a coupon worth more than that total is dropped.
    """
    if not user:
        return []
    totals = product_line_totals(items)
    entries = []
    seen = set()
    couponed_products = set()
    for item in items:
        cp_id = str(item.get("cp_id") or "")
        it_id = str(item.get("it_id") or "")
        if not cp_id or cp_id in seen or it_id in couponed_products:
            continue
        coupon = valid_coupons_queryset(user).filter(pk=cp_id, cp_method__in=(0, 1)).first()
        if not coupon or not coupon_matches_cart_item(coupon, item):
            continue
        base = totals.get(it_id, 0)
        if coupon_exceeds_base(coupon, base):
            continue
        discount = coupon_raw_discount(coupon, base)
        if discount > 0:
            entries.append((it_id, coupon, discount))
            seen.add(cp_id)
            couponed_products.add(it_id)
    return entries


def validated_item_coupons(user, items):
    """``(coupon, discount)`` of the valid product and category coupons; see product_coupon_entries."""
    return [(coupon, discount) for _, coupon, discount in product_coupon_entries(user, items)]


def items_with_product_coupon_prices(items, entries):
    """Copies of the cart lines carrying the validated product coupons.

    YoungCart orderformupdate.php writes the product's discount on its first cart line (``order by
    ct_id asc limit 1``) and nothing on its other lines, so the lines add up to the order's item
    coupon total."""
    by_product = {it_id: (coupon, discount) for it_id, coupon, discount in entries}
    placed = set()
    lines = []
    for item in items:
        it_id = str(item.get("it_id") or "")
        if it_id in by_product and it_id not in placed:
            coupon, discount = by_product[it_id]
            lines.append({**item, "cp_id": coupon.cp_id, "cp_price": discount})
            placed.add(it_id)
        else:
            lines.append({**item, "cp_id": "", "cp_price": 0})
    return lines


def coupon_payload(coupon, *, amount=0):
    discount = coupon_discount(coupon, amount)
    used = coupon.cp_used
    if coupon.cp_all_members:
        # a shared coupon is "used" for the member who used it, from the annotation of the list
        used = "1" if getattr(coupon, "used_by_member", False) else ""
    return {
        "cp_id": coupon.cp_id,
        "cp_subject": coupon.cp_subject,
        "cp_method": coupon.cp_method,
        "cp_target": coupon.cp_target,
        "cp_type": coupon.cp_type,
        "cp_price": coupon.cp_price,
        "cp_minimum": coupon.cp_minimum,
        "cp_maximum": coupon.cp_maximum,
        "cp_trunc": coupon.cp_trunc,
        "cp_start": coupon.cp_start.isoformat() if coupon.cp_start else "",
        "cp_end": coupon.cp_end.isoformat() if coupon.cp_end else "",
        "cp_used": used,
        "cp_all_members": coupon.cp_all_members,
        "discount": discount,
    }


def coupon_zone_payload(zone, *, user=None):
    target_label = "Shipping discount" if zone.cp_method == 3 else "Order discount"
    target_name = ""
    target_href = ""
    if zone.cp_method == 0 and zone.cp_target:
        product = ShopProduct.objects.filter(pk=zone.cp_target).first()
        target_name = product.it_name if product else zone.cp_target
        target_href = f"/shop/products/{zone.cp_target}"
        target_label = "\uac1c\ubcc4\uc0c1\ud488\ud560\uc778"
    elif zone.cp_method == 1 and zone.cp_target:
        category = ShopCategory.objects.filter(pk=zone.cp_target).first()
        target_name = category.ca_name if category else zone.cp_target
        target_href = f"/shop/categories/{zone.cp_target}"
        target_label = "Category coupon"
    downloaded = False
    if user and user.is_authenticated:
        # YoungCart is_coupon_downloaded: a used coupon still counts as downloaded
        downloaded = ShopCoupon.objects.filter(user=user, coupon_zone=zone).exists()
    return {
        "cz_id": zone.pk,
        "cz_type": zone.cz_type,
        "cz_point": zone.cz_point,
        "cz_subject": zone.cz_subject,
        "cz_start": zone.cz_start.isoformat() if zone.cz_start else "",
        "cz_end": zone.cz_end.isoformat() if zone.cz_end else "",
        "cz_file": zone.cz_file,
        "cz_period": zone.cz_period,
        "cz_download": zone.cz_download,
        "cp_method": zone.cp_method,
        "cp_target": zone.cp_target,
        "cp_type": zone.cp_type,
        "cp_price": zone.cp_price,
        "cp_minimum": zone.cp_minimum,
        "cp_maximum": zone.cp_maximum,
        "cp_trunc": zone.cp_trunc,
        "image_url": zone.image_url,
        "target_label": target_label,
        "target_name": target_name,
        "target_href": target_href,
        "downloaded": downloaded,
    }


def member_coupons_queryset(user):
    """The member's own coupons and the all-member coupons, marked with the member's own use."""
    return ShopCoupon.objects.filter(Q(user=user) | Q(cp_all_members=True)).annotate(
        used_by_member=Exists(ShopCouponLog.objects.filter(coupon=OuterRef("pk"), user=user))
    )


def valid_coupons_queryset(user):
    today = timezone.localdate()
    return (
        member_coupons_queryset(user)
        .filter(Q(user=user, cp_used="") | Q(cp_all_members=True, used_by_member=False))
        .filter(cp_start__lte=today)
        .filter(Q(cp_end__isnull=True) | Q(cp_end__gte=today))
    )


def coupon_matches_cart_item(coupon, item):
    product = ShopProduct.objects.filter(pk=item.get("it_id")).select_related("category").first()
    if coupon.cp_method == 0:
        return str(coupon.cp_target) == str(item.get("it_id"))
    if coupon.cp_method == 1:
        return bool(product and str(coupon.cp_target) in product.category_ids)
    return coupon.cp_method in {2, 3}
