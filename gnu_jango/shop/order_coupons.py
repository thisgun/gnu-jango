"""The coupon discounts of an order, worked out once for every screen that shows its total.

YoungCart keeps three amounts on the order: od_cart_coupon (product and category coupons),
od_coupon (the order coupon) and od_send_coupon (the shipping coupon). This shop has no
od_cart_coupon column: the product coupons are read from the order's coupon logs, one log per coupon
with the discount it gave (orderformupdate.php writes the same logs).

youngcart stores a product coupon's discount on the product's first cart line (``order by ct_id asc
limit 1``, mirrored by api.shop_coupons.items_with_product_coupon_prices) and get_order_info sums
cp_price over the 주문~완료 lines only, so a product coupon stops counting once that line is
cancelled, returned or sold out. The logs here do not name the line, so each product coupon is put
back on the first line of the product it applied to (cart_coupon_lines).
"""

from dataclasses import dataclass, field

from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES

CART_COUPON_METHODS = frozenset({0, 1})  # product and category coupons
ORDER_COUPON_METHOD = 2
SEND_COUPON_METHOD = 3
PRODUCT_COUPON_METHOD = 0


@dataclass(frozen=True)
class OrderCouponTotals:
    cart: int = 0
    order: int = 0
    send: int = 0
    # the product coupon discount carried by each active line (line pk -> amount), for tax splits
    cart_by_line: dict = field(default_factory=dict, compare=False)

    @property
    def total(self):
        return self.cart + self.order + self.send


def _line_status(item):
    return item.ct_status


def cart_coupon_lines(logs, items):
    """The order line each product (0) or category (1) coupon log discounts: {log pk: line or None}.

    A coupon goes on the first line (lowest pk, the cart order) of its product. A product coupon
    names its product; a category coupon goes to the first product of its category that no other
    coupon took (one product coupon per product, api.shop_coupons.product_coupon_entries). None
    when no line of the order matches (an imported record)."""
    first_lines = {}
    for item in sorted(items, key=lambda item: item.pk):
        first_lines.setdefault(str(item.it_id), item)
    cart_logs = [
        log for log in logs if log.coupon_id and log.coupon and int(log.coupon.cp_method or 0) in CART_COUPON_METHODS
    ]
    claimed = set()
    placed = {}
    for log in sorted(cart_logs, key=lambda log: (int(log.coupon.cp_method or 0), log.pk)):
        coupon = log.coupon
        target = str(coupon.cp_target or "")
        if int(coupon.cp_method or 0) == PRODUCT_COUPON_METHOD:
            it_id = target if target in first_lines else None
        else:
            candidates = [
                it_id
                for it_id, line in first_lines.items()
                if line.product_id and line.product and target in line.product.category_ids
            ]
            it_id = next((it_id for it_id in candidates if it_id not in claimed), candidates[0] if candidates else None)
        if it_id is not None:
            claimed.add(it_id)
        placed[log.pk] = first_lines.get(it_id) if it_id is not None else None
    return placed


def order_coupon_totals(order, logs=None, *, items=None, status_of=None):
    """The product, order and shipping coupon discounts of ``order``.

    od_coupon and od_send_coupon are the stored amounts (the logs of those methods stand in only
    when nothing is stored). A log whose coupon row is gone (deleted after use, or not in the
    imported data) cannot tell its method; the part of such logs that od_coupon / od_send_coupon do
    not already account for is a product coupon. That keeps a deleted product coupon in the total
    without counting a deleted order or shipping coupon twice.

    A product coupon counts while the line it sits on is active (not 취소/반품/품절); one that
    cannot be placed on a line counts while the order has an active line (or has no lines at all,
    as some imported orders). ``items`` may be passed when loaded already (with their products);
    ``status_of(line)`` gives a line's status, for working out a change before saving it.
    """
    if logs is None:
        logs = list(order.coupon_logs.select_related("coupon").all()) if order.pk else []
    status_of = status_of or _line_status
    by_method = {}
    unclassified = 0
    cart_logs = []
    for log in logs:
        price = max(0, int(log.cp_price or 0))
        coupon = log.coupon if log.coupon_id else None
        if coupon is None:
            unclassified += price
            continue
        method = int(coupon.cp_method or 0)
        if method in CART_COUPON_METHODS:
            cart_logs.append(log)
            continue
        by_method[method] = by_method.get(method, 0) + price
    order_logged = by_method.get(ORDER_COUPON_METHOD, 0)
    send_logged = by_method.get(SEND_COUPON_METHOD, 0)
    order_coupon = int(order.od_coupon or 0) or order_logged
    send_coupon = int(order.od_send_coupon or 0) or send_logged
    unexplained = max(0, unclassified - max(0, order_coupon - order_logged) - max(0, send_coupon - send_logged))

    cart = 0
    cart_by_line = {}
    if cart_logs or unexplained:
        if items is None:
            items = list(order.items.select_related("product")) if order.pk else []
        has_active = any(str(status_of(item) or "") not in INACTIVE_LINE_STATUSES for item in items)
        counts_unplaced = has_active or not items
        placed = cart_coupon_lines(cart_logs, items)
        for log in cart_logs:
            price = max(0, int(log.cp_price or 0))
            line = placed.get(log.pk)
            if line is None:
                cart += price if counts_unplaced else 0
            elif str(status_of(line) or "") not in INACTIVE_LINE_STATUSES:
                cart += price
                cart_by_line[line.pk] = cart_by_line.get(line.pk, 0) + price
        if counts_unplaced:
            cart += unexplained
    return OrderCouponTotals(cart=cart, order=order_coupon, send=send_coupon, cart_by_line=cart_by_line)
