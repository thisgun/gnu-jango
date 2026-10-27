"""Admin import/export resources for products and orders.

The existing shop tools handle the youngcart-shaped product and delivery sheets. These resources
add the standard django-import-export workflow for operators: CSV/XLSX import with preview, plus
CSV/XLSX export of the current admin selection. Keep the same safety rules as the domain tools:

* product stock is only changed through the stock adjustment screen after a product exists;
* order money, status, payment, and shipping fields are never written by an import;
* unknown order ids are rejected instead of creating incomplete orders.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from import_export import fields

from gnu_jango.core.import_export import SafeExportResource, UpdateOnlyResource

from .inventory import reserve_product_stock
from .models import ShopOrder, ShopOrderItem, ShopProduct
from .order_statuses import STATUS_ORDERED
from .shipping import current_shipping_policy, shipping_quote
from .taxes import calculate_order_tax_amounts

IT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _text(value):
    return str(value or "").strip()


def _integer(value, *, default=None, minimum=None):
    text = _text(value).replace(",", "")
    if not text:
        return default
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not an integer: {value!r}") from exc
    if number != number.to_integral_value():
        raise ValueError(f"Not an integer: {value!r}")
    number = int(number)
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


class ShopProductResource(UpdateOnlyResource):
    """Product catalogue import/export without counters, images, options, or stock updates."""

    created_at = fields.Field(attribute="created_at", readonly=True)
    updated_at = fields.Field(attribute="updated_at", readonly=True)
    protected_update_fields = ("it_stock_qty",)

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
            "it_tel_inq",
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
        if not IT_ID_RE.fullmatch(it_id):
            raise ValueError("it_id must contain only letters, digits, underscores, and hyphens (max 40).")
        row["it_id"] = it_id
        existing = ShopProduct.objects.select_for_update().filter(pk=it_id).first()

        it_name = _text(row.get("it_name"))
        if not it_name:
            if existing is None:
                raise ValueError("it_name is required.")
            it_name = existing.it_name
        row["it_name"] = it_name

        for field_name in ("category", "category2", "category3"):
            if not _text(row.get(field_name)):
                row[field_name] = getattr(existing, f"{field_name}_id") if existing else None
        for field_name in (
            "it_seo_title",
            "it_brand",
            "it_maker",
            "it_origin",
            "it_model",
            "it_info_gubun",
        ):
            if existing is not None and not _text(row.get(field_name)):
                row[field_name] = getattr(existing, field_name, "")
        if existing is not None and not _text(row.get("it_nocoupon")):
            row["it_nocoupon"] = existing.it_nocoupon

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
        row["it_tel_inq"] = _flag(
            row.get("it_tel_inq"), default=existing.it_tel_inq if existing else ""
        )
        if row["it_use"] == "1" and row["it_price"] == 0 and row["it_tel_inq"] != "1":
            raise ValueError(
                "A product on sale needs a price; set it_tel_inq=1 for a phone-inquiry product."
            )


class ShopOrderResource(UpdateOnlyResource):
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
        existing = ShopOrder.objects.select_for_update().filter(pk=od_id).first()
        if existing is None:
            raise ValueError(
                "This resource updates existing orders only; use the order registration resource for new orders."
            )
        row["od_id"] = od_id
        for field_name in (
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
        ):
            if not _text(row.get(field_name)):
                row[field_name] = getattr(existing, field_name)


class ShopOrderRegistrationResource(SafeExportResource):
    """Create unpaid bank-deposit orders from one CSV row per order.

    This intentionally supports one line item per row and rejects options, coupons, points, and
    online payments. It creates the order in the ``order`` state, reserves the product stock, and
    leaves payment/status movement to the normal admin actions. For multi-line orders or options,
    use the storefront order flow or the existing delivery/order tools.
    """

    username = fields.Field(column_name="username", attribute=None, readonly=True)
    it_id = fields.Field(column_name="it_id", attribute=None, readonly=True)
    ct_qty = fields.Field(column_name="ct_qty", attribute=None, readonly=True)
    ct_option = fields.Field(column_name="ct_option", attribute=None, readonly=True)

    class Meta:
        model = ShopOrder
        fields = (
            "od_id",
            "username",
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
            "od_deposit_name",
            "od_bank_account",
            "it_id",
            "ct_qty",
            "ct_option",
        )
        export_order = fields
        import_id_fields = ("od_id",)
        skip_unchanged = False
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        od_id = _text(row.get("od_id"))
        if not od_id:
            raise ValueError("od_id is required.")
        if len(od_id) > 40:
            raise ValueError("od_id must be at most 40 characters.")
        if ShopOrder.objects.filter(pk=od_id).exists():
            raise ValueError("od_id already exists; use the existing-order update resource.")
        row["od_id"] = od_id

        od_name = _text(row.get("od_name"))
        if not od_name:
            raise ValueError("od_name is required.")
        row["od_name"] = od_name

        product_id = _text(row.get("it_id"))
        product = ShopProduct.objects.filter(pk=product_id).first()
        if product is None:
            raise ValueError(f"Product not found: {product_id or '-'}")
        quantity = _integer(row.get("ct_qty"), default=1, minimum=1)
        min_qty = int(product.it_buy_min_qty or 0)
        max_qty = int(product.it_buy_max_qty or 0)
        if min_qty and quantity < min_qty:
            raise ValueError(f"ct_qty is below the product minimum ({min_qty}).")
        if max_qty and quantity > max_qty:
            raise ValueError(f"ct_qty is above the product maximum ({max_qty}).")
        if _text(row.get("ct_option")):
            raise ValueError("Options are not supported by order registration; use the storefront order flow.")
        unit_price = int(product.it_price or 0)
        if unit_price <= 0:
            raise ValueError("Order registration does not support zero-price products.")
        row["_product_id"] = product.pk
        row["_quantity"] = quantity
        row["_unit_price"] = unit_price

        username = _text(row.get("username"))
        user_id = None
        if username:
            user = get_user_model().objects.filter(username=username, is_active=True).first()
            if user is None:
                raise ValueError(f"Member not found: {username}")
            user_id = user.pk
        row["_user_id"] = user_id

        # Registration creates an unpaid bank-deposit order only. Payment is recorded later by
        # the existing order actions, so a CSV cannot claim a gateway payment.
        settle_case = _text(row.get("od_settle_case"))
        if settle_case and settle_case not in {"bank", "무통장입금"}:
            raise ValueError("Order registration supports bank-deposit orders only; use bank.")

    def before_save_instance(self, instance, row, **kwargs):
        if not instance._state.adding:
            raise ValueError("Order registration cannot update an existing order.")
        product = ShopProduct.objects.get(pk=row["_product_id"])
        quantity = row["_quantity"]
        unit_price = row["_unit_price"]
        total = unit_price * quantity
        recipient_zip = _text(row.get("od_b_zip") or row.get("od_zip"))
        shipping = shipping_quote(
            total,
            recipient_zip,
            items=[{"it_id": product.pk, "ct_qty": quantity, "ct_price": unit_price, "line_total": total}],
        )
        base, extra = shipping["base"], shipping["extra"]
        payable = total + base + extra
        tax = calculate_order_tax_amounts(
            [{"ct_price": unit_price, "ct_qty": quantity, "ct_notax": product.it_notax, "io_type": 0, "io_price": 0}],
            send_cost=base,
            send_cost2=extra,
            payable_amount=payable,
            mixed_tax_enabled=bool(current_shipping_policy().de_tax_flag_use),
        )

        instance.od_id = row["od_id"]
        instance.user_id = row["_user_id"]
        instance.od_name = row["od_name"]
        instance.od_b_name = _text(row.get("od_b_name")) or instance.od_name
        instance.od_b_zip = recipient_zip or _text(row.get("od_zip"))
        instance.od_status = STATUS_ORDERED
        instance.od_settle_case = "bank"
        instance.od_cart_price = total
        instance.od_send_cost = base
        instance.od_send_cost2 = extra
        instance.od_receipt_price = 0
        instance.od_misu = payable
        instance.od_bank_account = _text(row.get("od_bank_account"))
        instance.od_tax_flag = tax["od_tax_flag"]
        instance.od_tax_mny = tax["od_tax_mny"]
        instance.od_vat_mny = tax["od_vat_mny"]
        instance.od_free_mny = tax["od_free_mny"]
        instance.od_mod_history = "CSV order registration\n"

    def after_save_instance(self, instance, row, **kwargs):
        product = reserve_product_stock(row["_product_id"], row["_quantity"])
        ShopOrderItem.objects.create(
            order=instance,
            product=product,
            ct_id=f"csv-{uuid.uuid4().hex}",
            it_id=product.pk,
            it_name=product.it_name,
            ct_price=row["_unit_price"],
            ct_qty=row["_quantity"],
            ct_option="",
            ct_status=STATUS_ORDERED,
            io_type=0,
            io_price=0,
            ct_notax=product.it_notax,
            ct_send_cost=0,
            stock_adjusted=True,
            image_url=product.image_url,
        )
