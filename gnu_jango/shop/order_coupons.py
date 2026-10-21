"""The coupon discounts of an order, worked out once for every screen that shows its total.

YoungCart keeps three amounts on the order: od_cart_coupon (product and category coupons),
od_coupon (the order coupon) and od_send_coupon (the shipping coupon). This shop has no
od_cart_coupon column: the product coupons are read from the order's coupon logs, one log per coupon
with the discount it gave (orderformupdate.php writes the same logs).
"""

from dataclasses import dataclass

CART_COUPON_METHODS = frozenset({0, 1})  # product and category coupons
ORDER_COUPON_METHOD = 2
SEND_COUPON_METHOD = 3


@dataclass(frozen=True)
class OrderCouponTotals:
    cart: int = 0
    order: int = 0
    send: int = 0

    @property
    def total(self):
        return self.cart + self.order + self.send


def order_coupon_totals(order, logs=None):
    """The product, order and shipping coupon discounts of ``order``.

    od_coupon and od_send_coupon are the stored amounts (the logs of those methods stand in only
    when nothing is stored). A log whose coupon row is gone (deleted after use, or not in the
    imported data) cannot tell its method; the part of such logs that od_coupon / od_send_coupon do
    not already account for is a product coupon. That keeps a deleted product coupon in the total
    without counting a deleted order or shipping coupon twice.
    """
    if logs is None:
        logs = list(order.coupon_logs.select_related("coupon").all()) if order.pk else []
    by_method = {}
    unclassified = 0
    for log in logs:
        price = max(0, int(log.cp_price or 0))
        coupon = log.coupon if log.coupon_id else None
        if coupon is None:
            unclassified += price
            continue
        method = int(coupon.cp_method or 0)
        key = "cart" if method in CART_COUPON_METHODS else method
        by_method[key] = by_method.get(key, 0) + price
    order_logged = by_method.get(ORDER_COUPON_METHOD, 0)
    send_logged = by_method.get(SEND_COUPON_METHOD, 0)
    order_coupon = int(order.od_coupon or 0) or order_logged
    send_coupon = int(order.od_send_coupon or 0) or send_logged
    unexplained = unclassified - max(0, order_coupon - order_logged) - max(0, send_coupon - send_logged)
    return OrderCouponTotals(
        cart=by_method.get("cart", 0) + max(0, unexplained),
        order=order_coupon,
        send=send_coupon,
    )
