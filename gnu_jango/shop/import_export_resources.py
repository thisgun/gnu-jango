"""Admin import/export resources for products and orders.

The existing shop tools handle the youngcart-shaped product and delivery sheets. These resources
add the standard django-import-export workflow for operators: CSV/XLSX import with preview, plus
CSV/XLSX export of the current admin selection. Keep the same safety rules as the domain tools:

* product stock is only changed through the stock adjustment screen after a product exists;
* order money, status, payment, and shipping fields are never written by an import;
* unknown order ids are rejected instead of creating incomplete orders.
"""

from decimal import Decimal, InvalidOperation

from import_export import fields, resources

from .models import ShopOrder, ShopProduct


def _text(value):
    return str(value or "").strip()


def _integer(value, *, default=None, minimum=None):
    text = _text(value).replace(",", "")
    if not text:
        return default
    try:
        number = int(Decimal(text))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not an integer: {value!r}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"Must be at least {minimum}: {value!r}")
    return number


def _flag(value, *, default=""):
    text = _text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return "1"
    if text in {"0", "false", "no", "n", "off"}:
        return ""
    return default


class ShopProductResource(resources.ModelResource):
    """Product catalogue import/export without counters, images, options, or stock updates."""

    created_at = fields.Field(attribute="created_at", readonly=True)
    updated_at = fields.Field(attribute="updated_at", readonly=True)

    class Meta:
        model = ShopProduct
        fields = (
            "it_id",
            "it_name",
            "category",
            "category2",
            "category3",
            "it_seo_title",
            "it_brand",
            "it_maker",
            "it_origin",
            "it_model",
            "it_price",
            "it_basic_price",
            "it_cust_price",
            "it_point",
            "it_stock_qty",
            "it_buy_min_qty",
            "it_buy_max_qty",
            "it_soldout",
            "it_use",
            "it_stock_sms",
            "it_sc_type",
            "it_sc_method",
            "it_sc_price",
            "it_sc_minimum",
            "it_sc_qty",
            "it_notax",
            "it_nocoupon",
            "it_info_gubun",
            "created_at",
            "updated_at",
        )
        export_order = fields
        import_id_fields = ("it_id",)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        it_id = _text(row.get("it_id"))
        if not it_id:
            raise ValueError("it_id is required.")
        if len(it_id) > 40:
            raise ValueError("it_id must be at most 40 characters.")
        row["it_id"] = it_id
        existing = ShopProduct.objects.filter(pk=it_id).first()

        it_name = _text(row.get("it_name"))
        if not it_name:
            if existing is None:
                raise ValueError("it_name is required.")
            it_name = existing.it_name
        row["it_name"] = it_name

        for field_name in ("category", "category2", "category3"):
            if not _text(row.get(field_name)):
                row[field_name] = getattr(existing, f"{field_name}_id") if existing else None

        stock_text = _text(row.get("it_stock_qty")).replace(",", "")
        if existing is not None:
            if stock_text and _integer(stock_text, minimum=0) != existing.it_stock_qty:
                raise ValueError(
                    "Existing product stock cannot be changed by import; use the stock adjustment tool."
                )
            row["it_stock_qty"] = existing.it_stock_qty
        else:
            row["it_stock_qty"] = _integer(stock_text, default=9999, minimum=0)

        for field_name, default in (
            ("it_price", 0),
            ("it_basic_price", 0),
            ("it_cust_price", 0),
            ("it_point", 0),
            ("it_buy_min_qty", 1),
            ("it_buy_max_qty", 0),
            ("it_sc_type", 0),
            ("it_sc_method", 0),
            ("it_sc_price", 3000),
            ("it_sc_minimum", 50000),
            ("it_sc_qty", 0),
            ("it_notax", 0),
        ):
            default = getattr(existing, field_name, default) if existing is not None else default
            row[field_name] = _integer(row.get(field_name), default=default, minimum=0)

        row["it_use"] = _flag(row.get("it_use"), default=existing.it_use if existing else "1")
        row["it_soldout"] = _flag(row.get("it_soldout"), default=existing.it_soldout if existing else "")
        row["it_stock_sms"] = _flag(
            row.get("it_stock_sms"), default=existing.it_stock_sms if existing else ""
        )


class ShopOrderResource(resources.ModelResource):
    """Order reporting plus a safe update of customer-facing descriptive fields.

    Import is deliberately limited to existing orders. Status, amounts, payment keys, delivery
    registration, and history are read-only here; those must go through the order workflow or the
    delivery upload/action so stock, coupons, points, and PG refunds stay consistent.
    """

    uid = fields.Field(attribute="uid", readonly=True)
    user = fields.Field(attribute="user", readonly=True)
    od_datetime = fields.Field(attribute="od_datetime", readonly=True)
    od_status = fields.Field(attribute="od_status", readonly=True)
    od_settle_case = fields.Field(attribute="od_settle_case", readonly=True)
    od_pg = fields.Field(attribute="od_pg", readonly=True)
    od_cart_price = fields.Field(attribute="od_cart_price", readonly=True)
    od_send_cost = fields.Field(attribute="od_send_cost", readonly=True)
    od_send_cost2 = fields.Field(attribute="od_send_cost2", readonly=True)
    od_receipt_price = fields.Field(attribute="od_receipt_price", readonly=True)
    od_cancel_price = fields.Field(attribute="od_cancel_price", readonly=True)
    od_refund_price = fields.Field(attribute="od_refund_price", readonly=True)
    od_misu = fields.Field(attribute="od_misu", readonly=True)
    od_point = fields.Field(attribute="od_point", readonly=True)
    od_coupon = fields.Field(attribute="od_coupon", readonly=True)
    od_send_coupon = fields.Field(attribute="od_send_coupon", readonly=True)
    od_tno = fields.Field(attribute="od_tno", readonly=True)
    od_app_no = fields.Field(attribute="od_app_no", readonly=True)
    od_bank_account = fields.Field(attribute="od_bank_account", readonly=True)
    od_vbank_status = fields.Field(attribute="od_vbank_status", readonly=True)
    od_vbank_account = fields.Field(attribute="od_vbank_account", readonly=True)
    od_vbank_due_date = fields.Field(attribute="od_vbank_due_date", readonly=True)
    od_receipt_time = fields.Field(attribute="od_receipt_time", readonly=True)
    od_delivery_company = fields.Field(attribute="od_delivery_company", readonly=True)
    od_invoice = fields.Field(attribute="od_invoice", readonly=True)
    od_invoice_time = fields.Field(attribute="od_invoice_time", readonly=True)
    od_mod_history = fields.Field(attribute="od_mod_history", readonly=True)

    class Meta:
        model = ShopOrder
        fields = (
            "od_id",
            "uid",
            "user",
            "od_datetime",
            "od_name",
            "od_tel",
            "od_hp",
            "od_email",
            "od_zip",
            "od_addr1",
            "od_addr2",
            "od_addr3",
            "od_b_name",
            "od_b_tel",
            "od_b_hp",
            "od_b_zip",
            "od_b_addr1",
            "od_b_addr2",
            "od_b_addr3",
            "od_memo",
            "od_shop_memo",
            "od_hope_date",
            "od_status",
            "od_settle_case",
            "od_pg",
            "od_cart_price",
            "od_send_cost",
            "od_send_cost2",
            "od_receipt_price",
            "od_cancel_price",
            "od_refund_price",
            "od_misu",
            "od_point",
            "od_coupon",
            "od_send_coupon",
            "od_tno",
            "od_app_no",
            "od_bank_account",
            "od_vbank_status",
            "od_vbank_account",
            "od_vbank_due_date",
            "od_receipt_time",
            "od_delivery_company",
            "od_invoice",
            "od_invoice_time",
            "od_mod_history",
        )
        export_order = fields
        import_id_fields = ("od_id",)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        od_id = _text(row.get("od_id"))
        if not od_id:
            raise ValueError("od_id is required.")
        if not ShopOrder.objects.filter(pk=od_id).exists():
            raise ValueError("Order import only updates existing orders; create orders through checkout.")
        row["od_id"] = od_id
