"""YoungCart-compatible order tax calculations."""


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cart_line_total(item):
    quantity = max(0, _int(item.get("ct_qty"), 0))
    option_type = _int(item.get("io_type"), 0)
    option_price = _int(item.get("io_price"), 0)
    if option_type == 1:
        return max(0, option_price) * quantity
    return max(0, _int(item.get("ct_price"), 0) + option_price) * quantity


def _rounded_tax_base(amount):
    """Match PHP round(amount / 1.1) for non-negative integer KRW amounts."""
    return (max(0, amount) * 20 + 11) // 22


def calculate_order_tax_amounts(
    cart_items,
    *,
    send_cost=0,
    send_cost2=0,
    order_coupon=0,
    send_coupon=0,
    receipt_point=0,
    payable_amount=0,
    mixed_tax_enabled=False,
):
    """Return the Gnuboard od_tax_* fields for an order."""
    payable_amount = max(0, _int(payable_amount))
    if not mixed_tax_enabled:
        tax_base = _rounded_tax_base(payable_amount)
        return {
            "od_tax_flag": 0,
            "od_tax_mny": tax_base,
            "od_vat_mny": payable_amount - tax_base,
            "od_free_mny": 0,
        }

    taxable_total = 0
    free_total = 0
    for item in cart_items:
        line_total = max(0, _cart_line_total(item) - max(0, _int(item.get("cp_price"))))
        if _int(item.get("ct_notax")) == 1:
            free_total += line_total
        else:
            taxable_total += line_total

    taxable_total += (
        _int(send_cost)
        + _int(send_cost2)
        - _int(order_coupon)
        - _int(send_coupon)
        - _int(receipt_point)
    )
    if taxable_total < 0:
        free_total += taxable_total
        taxable_total = 0

    tax_base = _rounded_tax_base(taxable_total)
    return {
        "od_tax_flag": 1,
        "od_tax_mny": tax_base,
        "od_vat_mny": taxable_total - tax_base,
        "od_free_mny": free_total,
    }
