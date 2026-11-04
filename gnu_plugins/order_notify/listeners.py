"""The plugin's hook listeners, registered by OrderNotifyConfig.ready(). The shop sends these hooks
after the order change commits (gnu_jango.shop.order_hooks)."""

from gnu_jango.api.shop_common import ORDER_STATUS_PAID
from gnu_jango.plugins import hooks

from . import conf, services


@hooks.on("shop.order.placed")
def notify_placed(order, **kwargs):
    if conf.value("ORDER_NOTIFY_PLACED"):
        services.notify(order, "placed")


@hooks.on("shop.order.paid")
def notify_paid(order, **kwargs):
    if conf.value("ORDER_NOTIFY_PAID"):
        services.notify(order, "paid")


@hooks.on("shop.order.status_changed")
def notify_status_changed(order, old_status, new_status, source="", **kwargs):
    if source == "cancel":
        if conf.value("ORDER_NOTIFY_CANCELLED"):
            services.notify(order, "cancelled", old_status=old_status, new_status=new_status)
        return
    if new_status == ORDER_STATUS_PAID:
        return  # shop.order.paid follows and tells this one
    if conf.value("ORDER_NOTIFY_OTHER_STATUS"):
        services.notify(order, "status", old_status=old_status, new_status=new_status)
