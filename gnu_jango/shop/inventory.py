from django.db import transaction
from django.utils import timezone

from .models import ShopOrder, ShopProduct
from .order_points import save_order_item_status, take_back_order_points
from .order_statuses import INACTIVE_LINE_STATUSES


class StockAdjustmentError(Exception):
    def __init__(self, message, *, code="stock_unavailable", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def reserve_product_stock(product_id, quantity, option_id="", io_type=0):
    quantity = int(quantity or 0)
    if quantity < 1:
        raise StockAdjustmentError(
            "Order quantity must be greater than zero.",
            code="invalid_quantity",
            details={"ct_qty": "Order quantity must be greater than zero."},
        )

    product = ShopProduct.objects.select_for_update().filter(pk=product_id).first()
    if not product:
        raise StockAdjustmentError(
            "Product not found.",
            code="product_not_found",
            details={"it_id": product_id},
        )
    if product.it_use != "1" or product.it_soldout == "1":
        raise StockAdjustmentError(
            "Product is not available for order.",
            code="product_unavailable",
            details={"it_id": product.it_id},
        )
    if option_id:
        options = list(product.options or [])
        matched = None
        for option in options:
            if str(option.get("io_id")) == str(option_id) and int(option.get("io_type") or 0) == int(io_type or 0):
                matched = option
                break
        if matched is None:
            raise StockAdjustmentError(
                "Selected option was not found.",
                code="option_not_found",
                details={"it_id": product.it_id, "io_id": option_id},
            )
        if int(matched.get("io_use") if matched.get("io_use") is not None else 1) != 1:
            raise StockAdjustmentError(
                "Selected option is not available.",
                code="option_unavailable",
                details={"it_id": product.it_id, "io_id": option_id},
            )
        option_stock = int(matched.get("io_stock_qty") or 0)
        if option_stock < quantity:
            raise StockAdjustmentError(
                "재고수량이 부족합니다.",
                code="insufficient_stock",
                details={"it_id": product.it_id, "io_id": option_id, "it_stock_qty": option_stock, "requested_qty": quantity},
            )
        matched["io_stock_qty"] = option_stock - quantity
        product.options = options
        product.save(update_fields=["options", "updated_at"])
        return product
    if product.it_stock_qty < quantity:
        raise StockAdjustmentError(
            "재고수량이 부족합니다.",
            code="insufficient_stock",
            details={"it_id": product.it_id, "it_stock_qty": product.it_stock_qty, "requested_qty": quantity},
        )

    product.it_stock_qty -= quantity
    update_fields = ["it_stock_qty", "updated_at"]
    if product.it_stock_qty <= 0:
        product.it_soldout = "1"
        update_fields.append("it_soldout")
    product.save(update_fields=update_fields)
    return product


def append_order_history(history, line):
    """youngcart od_mod_history: one line per admin change, oldest first."""
    line = str(line or "").strip()
    if not line:
        return history or ""
    return f"{history or ''}{line}\n"


def order_history_line(text, actor=""):
    return f"{timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')} {actor or '-'} {text}"


def restore_line_stock(item):
    """Put the stock an order line reserved back on its product (or option); returns the quantity
    put back. The caller clears ``item.stock_adjusted``; a product set 품절 because its stock ran
    out comes off 품절, one set by hand stays."""
    if not item.stock_adjusted or not item.product_id:
        return 0
    product = ShopProduct.objects.select_for_update().filter(pk=item.product_id).first()
    if not product:
        return 0
    update_fields = ["updated_at"]
    if item.ct_option:
        options = list(product.options or [])
        for option in options:
            if str(option.get("io_id")) == str(item.ct_option) and int(option.get("io_type") or 0) == int(item.io_type or 0):
                option["io_stock_qty"] = int(option.get("io_stock_qty") or 0) + item.ct_qty
                break
        product.options = options
        update_fields.append("options")
    else:
        ran_out = product.it_stock_qty <= 0
        product.it_stock_qty += item.ct_qty
        update_fields.append("it_stock_qty")
        if product.it_soldout == "1" and ran_out and product.it_stock_qty > 0:
            product.it_soldout = ""
            update_fields.append("it_soldout")
    product.save(update_fields=update_fields)
    return item.ct_qty


def cancel_order_with_stock_restore(order, reason="", *, refund_price=0, history="", status="취소"):
    """Cancel the whole order and put the reserved stock back.

    ``status`` is what the order and its remaining lines become: 취소, or 반품 for an order
    returned after it shipped (lines already 취소/반품/품절 keep their status).

    ``reason`` comes from the customer (or a system job) and is appended to the order memo;
    ``history`` is the admin log line written to od_mod_history instead (an admin reason never
    reaches the customer's memo). ``refund_price`` is what was paid and is being paid back: the
    order keeps od_receipt_price as the record of the payment and od_refund_price shows the
    refund. An unpaid order (refund_price 0) owes and keeps nothing."""
    with transaction.atomic():
        locked_order = ShopOrder.objects.select_for_update().get(pk=order.pk)
        restored_count = 0
        for item in locked_order.items.select_for_update().filter(stock_adjusted=True):
            restored_count += restore_line_stock(item)
            item.stock_adjusted = False
            fields = ["stock_adjusted"]
            if item.ct_status not in INACTIVE_LINE_STATUSES:
                item.ct_status = status
                fields.append("ct_status")
            item.save(update_fields=fields)

        # a line already 취소/반품/품절 (a partial change) keeps what it became
        save_order_item_status(
            locked_order.items.exclude(ct_status__in=INACTIVE_LINE_STATUSES),
            status,
            reason=history or reason or "order cancelled",
        )
        # a line that already earned its purchase point gives it back
        take_back_order_points(locked_order)

        update_fields = ["od_status", "od_mod_history"]
        locked_order.od_status = status
        if reason:
            locked_order.od_memo = (locked_order.od_memo + "\n" + str(reason)).strip()
            update_fields.append("od_memo")
        locked_order.od_mod_history = append_order_history(
            locked_order.od_mod_history,
            history or order_history_line(f"주문취소 처리{f' - {reason}' if reason else ''}"),
        )
        locked_order._change_reason = (history or reason or "order cancelled")[:100]
        refund_price = max(0, int(refund_price or 0))
        # youngcart get_order_info: the cancelled goods amount; nothing is owed any more
        locked_order.od_cancel_price = locked_order.od_cart_price
        if refund_price:
            locked_order.od_refund_price = refund_price
        else:
            locked_order.od_receipt_price = 0
        locked_order.od_receipt_point = 0
        locked_order.od_misu = 0
        locked_order.od_send_cost = 0
        locked_order.od_send_cost2 = 0
        locked_order.od_coupon = 0
        locked_order.od_send_coupon = 0
        update_fields.extend(
            [
                "od_cancel_price",
                "od_receipt_price",
                "od_refund_price",
                "od_receipt_point",
                "od_misu",
                "od_send_cost",
                "od_send_cost2",
                "od_coupon",
                "od_send_coupon",
            ]
        )
        locked_order.save(update_fields=update_fields)
        return locked_order, restored_count
