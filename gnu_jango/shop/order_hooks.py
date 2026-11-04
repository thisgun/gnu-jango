"""Plugin hooks for orders (gnu_jango.plugins.hooks), sent once the change commits: a payment or
cancellation that is rolled back sends nothing.

- ``shop.order.placed`` (order): an order was created (checkout, subscription charge).
- ``shop.order.status_changed`` (order, old_status, new_status, source): the order's status moved.
  ``source`` is "payment" (a PG or virtual-account payment was confirmed), "admin" (a step along
  주문→입금→준비→배송→완료) or "cancel" (취소 or 반품: the customer, the admin, an expiry job,
  a failed payment or a return).
- ``shop.order.paid`` (order, source): the order became 입금, right after its status_changed.
"""

from django.db import transaction

from gnu_jango.plugins import hooks


def order_placed(order):
    transaction.on_commit(lambda: hooks.emit("shop.order.placed", order=order))


def order_status_changed(order, old_status, new_status, *, source):
    from gnu_jango.api.shop_common import ORDER_STATUS_PAID

    def send():
        hooks.emit(
            "shop.order.status_changed", order=order, old_status=old_status, new_status=new_status, source=source
        )
        if new_status == ORDER_STATUS_PAID:
            hooks.emit("shop.order.paid", order=order, source=source)

    transaction.on_commit(send)
