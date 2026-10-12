from django.db import transaction

from .models import ShopOrder, ShopProduct


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


def cancel_order_with_stock_restore(order, reason=""):
    with transaction.atomic():
        locked_order = ShopOrder.objects.select_for_update().get(pk=order.pk)
        restored_count = 0
        for item in locked_order.items.select_for_update().filter(stock_adjusted=True):
            if item.product_id:
                product = ShopProduct.objects.select_for_update().filter(pk=item.product_id).first()
                if product:
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
                        # only the 품절 set when the stock ran out comes off; one set by hand stays
                        if product.it_soldout == "1" and ran_out and product.it_stock_qty > 0:
                            product.it_soldout = ""
                            update_fields.append("it_soldout")
                    product.save(update_fields=update_fields)
                    restored_count += item.ct_qty
            item.stock_adjusted = False
            item.ct_status = "취소"
            item.save(update_fields=["stock_adjusted", "ct_status"])

        locked_order.items.exclude(ct_status="취소").update(ct_status="취소")

        update_fields = ["od_status"]
        locked_order.od_status = "취소"
        if reason:
            locked_order.od_memo = (locked_order.od_memo + "\n" + str(reason)).strip()
            update_fields.append("od_memo")
        locked_order.od_cancel_price = locked_order.od_cart_price
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
