"""Bulk stock edits (youngcart adm/shop_admin/itemstocklistupdate.php, optionstocklistupdate.php).

youngcart overwrites the stock columns with whatever the list form posts. Here each edit sets the
new quantity on a locked product row and writes a ShopStockAdjustment entry with the before/after
quantities, as the single stock adjustment screen does, so the stock history stays complete.

The form also posts the quantity it showed. When the stored quantity no longer matches (an order
reserved stock meanwhile) the row is left alone and reported, instead of silently overwriting a
change the admin never saw.
"""

import re
from dataclasses import dataclass, field

from django.db import transaction

from .models import ShopProduct, ShopStockAdjustment

MAX_STOCK = 2_147_483_647
DEFAULT_REASON = "재고 일괄수정"
OPTION_ID_SEPARATOR = "\x1e"  # youngcart chr(30) between the option values of a choice
# the product switches the list edits, with the value each stores when turned off
FLAG_FIELDS = (("it_use", "0"), ("it_soldout", ""), ("it_stock_sms", ""))


@dataclass
class BulkResult:
    changed: list = field(default_factory=list)
    unchanged: int = 0
    errors: list = field(default_factory=list)  # (label, message)

    def error(self, label, message):
        self.errors.append((label, message))


def parse_quantity(value):
    """A whole stock quantity in 0..MAX_STOCK, or None."""
    text = str(value if value is not None else "").replace(",", "").strip()
    if not re.fullmatch(r"-?[0-9]+", text):
        return None
    number = int(text)
    return number if 0 <= number <= MAX_STOCK else None


def option_label(option_id):
    return str(option_id or "").replace(OPTION_ID_SEPARATOR, " / ")


def option_rows(product):
    """The stock-managed option records of ``product``: (io_type, io_id, record) for choices (0)
    and supplements (1) with an id."""
    rows = []
    for record in product.options if isinstance(product.options, list) else []:
        if not isinstance(record, dict):
            continue
        option_id = str(record.get("io_id") or "").strip()
        try:
            option_type = int(record.get("io_type") or 0)
        except (TypeError, ValueError):
            continue
        if option_id and option_type in (0, 1):
            rows.append((option_type, option_id, record))
    return rows


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log(product, scope, before, after, reason, actor, *, io_id="", io_type=None):
    ShopStockAdjustment.objects.create(
        product=product,
        it_id=product.it_id,
        it_name=product.it_name,
        scope=scope,
        io_id=io_id,
        io_type=io_type,
        before_qty=before,
        delta=after - before,
        after_qty=after,
        reason=reason,
        actor=actor,
    )


def apply_product_rows(rows, *, actor, reason=DEFAULT_REASON):
    """Save product rows ``{"it_id", "stock", "stock_was", "it_use", "it_soldout",
    "it_stock_sms"}`` (flags are booleans; ``stock`` / ``stock_was`` as posted)."""
    result = BulkResult()
    reason = (str(reason or "").strip() or DEFAULT_REASON)[:255]
    for row in rows:
        it_id = str(row.get("it_id") or "").strip()
        stock = parse_quantity(row.get("stock"))
        stock_was = parse_quantity(row.get("stock_was"))
        if not it_id:
            continue
        if stock is None:
            result.error(it_id, f"재고는 0 이상 {MAX_STOCK:,} 이하의 정수로 입력하세요.")
            continue
        with transaction.atomic():
            product = ShopProduct.objects.select_for_update().filter(pk=it_id).first()
            if product is None:
                result.error(it_id, "상품이 없습니다.")
                continue
            before = int(product.it_stock_qty)
            if stock != before and stock_was is not None and stock_was != before:
                result.error(
                    it_id,
                    f"화면을 연 뒤 재고가 {stock_was:,}에서 {before:,}(으)로 바뀌어 저장하지 않았습니다. 목록을 새로 고친 뒤 다시 입력하세요.",
                )
                continue
            fields = []
            for name, off_value in FLAG_FIELDS:
                wanted = bool(row.get(name))
                if wanted != (getattr(product, name) == "1"):
                    setattr(product, name, "1" if wanted else off_value)
                    fields.append(name)
            if stock != before:
                product.it_stock_qty = stock
                fields.append("it_stock_qty")
            if not fields:
                result.unchanged += 1
                continue
            product.save(update_fields=[*fields, "updated_at"])
            if stock != before:
                _log(product, "product", before, stock, reason, actor)
            result.changed.append(it_id)
    return result


def apply_option_rows(rows, *, actor, reason=DEFAULT_REASON):
    """Save option rows ``{"it_id", "io_type", "io_id", "stock", "stock_was", "noti", "use"}``.

    The rows of one product are saved together under one lock of its row."""
    result = BulkResult()
    reason = (str(reason or "").strip() or DEFAULT_REASON)[:255]
    by_product = {}
    for row in rows:
        it_id = str(row.get("it_id") or "").strip()
        if it_id:
            by_product.setdefault(it_id, []).append(row)
    for it_id, product_rows in by_product.items():
        with transaction.atomic():
            product = ShopProduct.objects.select_for_update().filter(pk=it_id).first()
            if product is None:
                result.error(it_id, "상품이 없습니다.")
                continue
            records = [dict(record) if isinstance(record, dict) else record for record in (product.options or [])]
            index = {}
            for position, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                option_id = str(record.get("io_id") or "").strip()
                option_type = _int_or(record.get("io_type") or 0, -1)
                if option_id and option_type in (0, 1):
                    index.setdefault((option_type, option_id), position)
            logs = []
            touched = []
            for row in product_rows:
                option_type = _int_or(row.get("io_type"), -1)
                option_id = str(row.get("io_id") or "").strip()
                label = f"{it_id} {option_label(option_id)}"
                position = index.get((option_type, option_id))
                if position is None:
                    result.error(label, "옵션이 없습니다. 상품의 옵션이 바뀌었을 수 있습니다.")
                    continue
                stock = parse_quantity(row.get("stock"))
                noti = parse_quantity(row.get("noti")) if str(row.get("noti") or "").strip() else 0
                if stock is None:
                    result.error(label, f"재고는 0 이상 {MAX_STOCK:,} 이하의 정수로 입력하세요.")
                    continue
                if noti is None:
                    result.error(label, "통보수량은 0 이상의 정수로 입력하세요.")
                    continue
                record = records[position]
                before = _int_or(record.get("io_stock_qty") or 0, 0)
                stock_was = parse_quantity(row.get("stock_was"))
                if stock != before and stock_was is not None and stock_was != before:
                    result.error(
                        label,
                        f"화면을 연 뒤 재고가 {stock_was:,}에서 {before:,}(으)로 바뀌어 저장하지 않았습니다. 목록을 새로 고친 뒤 다시 입력하세요.",
                    )
                    continue
                use = 1 if row.get("use") else 0
                current_use = 0 if _int_or(record.get("io_use", 1), 1) == 0 else 1
                current_noti = _int_or(record.get("io_noti_qty") or 0, 0)
                if stock == before and use == current_use and noti == current_noti:
                    result.unchanged += 1
                    continue
                record["io_stock_qty"] = stock
                record["io_use"] = use
                record["io_noti_qty"] = noti
                if stock != before:
                    logs.append((option_type, option_id, before, stock))
                touched.append(label)
            if not touched:
                continue
            product.options = records
            product.save(update_fields=["options", "updated_at"])
            for option_type, option_id, before, stock in logs:
                _log(product, "option", before, stock, reason, actor, io_id=option_id, io_type=option_type)
            result.changed.extend(touched)
    return result
