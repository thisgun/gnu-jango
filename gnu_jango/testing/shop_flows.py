"""Drive shop orders through the real code paths and check the invariants that must hold after
any sequence of them (money, stock, coupons, points).

The flows go through the same entry points as the site: the cart and order API for checkout
(``place_bank_order``), the admin status change (``set_order_status``: 입금, 배송, 완료, 취소,
반품) and the admin line change (``change_order_lines``: 취소/품절/반품 of chosen lines or units).
The ``assert_*`` helpers state the invariants once, so every scenario checks the same rules::

    order = place_bank_order(client, [(shirt, 2), (cap, 1)], point_use=5000)
    pay(order)
    change_order_lines(order, [line_of(order, cap).pk], "취소")
    assert_order_money_consistent(order)
    assert_point_ledger_matches(member)
"""

from django.db.models import Sum
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopOrder, ShopProduct, ShopShippingPolicy
from gnu_jango.shop.order_flow import order_misu
from gnu_jango.shop.order_lines import line_amount
from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES
from gnu_jango.users.models import Profile, User_Point

BANK_ACCOUNT = "Invariant Bank 000-00 Holder"
SHIPPING_FEE = 3000
FREE_SHIPPING_FROM = 50000

CHECKOUT_FIELDS = {
    "od_name": "Invariant Buyer",
    "od_tel": "010-1111-2222",
    "od_hp": "010-1111-2222",
    "od_email": "buyer@example.test",
    "od_zip": "06236",
    "od_addr1": "Seoul",
    "od_addr2": "1",
    "od_b_name": "Invariant Buyer",
    "od_b_tel": "010-1111-2222",
    "od_b_hp": "010-1111-2222",
    "od_b_zip": "06236",
    "od_b_addr1": "Seoul",
    "od_b_addr2": "1",
}


def set_config(name, value):
    Config.objects.update_or_create(name=name, defaults={"value": str(value)})


def configure_shop(*, min_point=0, max_point=1_000_000, point_unit=100, point_days=0):
    """Bank transfer on, 3,000 shipping below 50,000, points usable from ``min_point``."""
    set_config("de_bank_use", "1")
    set_config("de_bank_account", BANK_ACCOUNT)
    set_config("de_point_days", point_days)
    ShopShippingPolicy.objects.update_or_create(
        pk=1,
        defaults={
            "de_delivery_company": "Courier",
            "de_send_cost_case": "차등",
            "de_send_cost_limit": str(FREE_SHIPPING_FROM),
            "de_send_cost_list": str(SHIPPING_FEE),
            "de_settle_min_point": min_point,
            "de_settle_max_point": max_point,
            "de_settle_point_unit": point_unit,
        },
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def checkout(client, items, **fields):
    """Put ``items`` ([(product, qty), ...]) in the cart and post the order; returns the response."""
    for product, qty in items:
        added = client.post("/api/v1/shop/cart", {"it_id": product.it_id, "ct_qty": qty}, format="json")
        assert added.status_code in (200, 201), added.content[:300]
    body = {
        **CHECKOUT_FIELDS,
        "od_settle_case": "bank",
        "od_bank_account": BANK_ACCOUNT,
        "od_deposit_name": "Invariant Buyer",
        **fields,
    }
    return client.post("/api/v1/shop/orders", body, format="json")


def place_bank_order(client, items, **fields):
    response = checkout(client, items, **fields)
    assert response.status_code == 201, response.content[:400]
    return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])


def admin_status(order, status, **kwargs):
    """The admin status change (orderlistupdate.php), with the carrier filled in for 배송."""
    from gnu_jango.shop.admin.orders import set_order_status

    if status == "배송":
        ShopOrder.objects.filter(pk=order.pk).update(od_delivery_company="Courier", od_invoice="INV-1")
    result = set_order_status(ShopOrder.objects.get(pk=order.pk), status, actor="invariant-admin", **kwargs)
    order.refresh_from_db()
    return result


def pay(order):
    result = admin_status(order, "입금")
    assert result, result.message
    return result


def deliver(order):
    """입금 (when still 주문) → 준비 → 배송 → 완료."""
    order.refresh_from_db()
    steps = ["입금", "준비", "배송", "완료"]
    for status in steps[steps.index(order.od_status) + 1 if order.od_status in steps else 0:]:
        result = admin_status(order, status)
        assert result, result.message


def line_of(order, product, *, active=True):
    lines = order.items.filter(product=product).order_by("pk")
    if active:
        lines = lines.exclude(ct_status__in=INACTIVE_LINE_STATUSES)
    return lines.first()


def balance(user):
    return int(Profile.objects.filter(user=user).values_list("user_point", flat=True).first() or 0)


# invariants -----------------------------------------------------------------------------------


def assert_point_ledger_matches(user):
    """The member's balance is the sum of their point history: nothing moves points off the books."""
    ledger = User_Point.objects.filter(user=user).aggregate(total=Sum("po_point"))["total"] or 0
    assert balance(user) == ledger, f"balance {balance(user)} != ledger sum {ledger}"


def assert_order_money_consistent(order):
    """What the order stores agrees with its lines and never refunds more than was paid.

    - od_cart_price is every line's amount, od_cancel_price the cancelled/returned/sold-out ones;
    - the stored od_misu is what order_misu works out from the amounts (never negative);
    - od_refund_price never exceeds od_receipt_price (cash) and is never negative;
    - the coupons never discount more than the goods still ordered.
    """
    order.refresh_from_db()
    lines = list(order.items.all())
    all_lines = sum(line_amount(line) for line in lines)
    inactive = sum(line_amount(line) for line in lines if line.ct_status in INACTIVE_LINE_STATUSES)
    assert order.od_cart_price == all_lines, (order.od_cart_price, all_lines)
    assert order.od_cancel_price == inactive, (order.od_cancel_price, inactive)
    assert order.od_misu == order_misu(order) >= 0, (order.od_misu, order_misu(order))
    assert 0 <= order.od_refund_price <= order.od_receipt_price, (order.od_refund_price, order.od_receipt_price)
    assert order.od_receipt_point >= 0
    assert 0 <= order.od_coupon <= max(0, all_lines - inactive)
    assert 0 <= order.od_send_coupon <= order.od_send_cost


def assert_fully_cancelled(order, *, paid, status="취소"):
    """A closed order: nothing owed, nothing discounted, all goods cancelled, the cash paid back."""
    order.refresh_from_db()
    assert order.od_status == status
    assert set(order.items.values_list("ct_status", flat=True)) <= set(INACTIVE_LINE_STATUSES)
    assert not order.items.filter(stock_adjusted=True).exists()
    assert (order.od_misu, order.od_coupon, order.od_send_coupon, order.od_receipt_point) == (0, 0, 0, 0)
    assert order.od_cancel_price == order.od_cart_price
    assert order.od_refund_price == paid
    assert order.od_receipt_price == paid
    assert not order.coupon_logs.exists()


def reserved_quantity(product):
    """Units of ``product`` held by order lines that took stock and have not given it back."""
    from gnu_jango.shop.models import ShopOrderItem

    total = ShopOrderItem.objects.filter(product=product, stock_adjusted=True).aggregate(qty=Sum("ct_qty"))["qty"]
    return int(total or 0)


def assert_stock_conserved(product, initial):
    """Stock on the shelf plus stock held by order lines is what the shop started with."""
    stock = ShopProduct.objects.get(pk=product.pk).it_stock_qty
    assert stock + reserved_quantity(product) == initial, (stock, reserved_quantity(product), initial)
