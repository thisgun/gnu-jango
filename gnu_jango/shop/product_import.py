"""상품 엑셀 일괄등록 (youngcart adm/shop_admin/itemexcel.php, itemexcelupdate.php).

The upload, an .xlsx workbook or a CSV file (shop/spreadsheet.py), keeps youngcart's column layout (lib/Excel/itemexcel.xls): row 1 the Korean labels,
row 2 the field names, the products from row 3. Options are not part of the sheet, as in
youngcart. youngcart only adds products and fails a row whose 상품코드 exists; here the admin may
choose to update existing products instead, where an empty cell keeps the stored value.

Every row is validated before anything is written, and each valid row is saved on its own, so
one bad row does not stop the others (youngcart reports the failed codes the same way).
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.db import transaction

from .models import ShopCategory, ShopProduct, ShopStockAdjustment
from .spreadsheet import read_upload

logger = logging.getLogger(__name__)

MAX_ROWS = 1000
MAX_STOCK = 2_147_483_647
MAX_PRICE = 2_000_000_000
MODE_CREATE = "create"
MODE_UPDATE = "update"
IMAGE_COUNT = 10

# (field, label) in youngcart's itemexcel.xls column order
COLUMNS = (
    ("it_id", "상품코드"),
    ("ca_id", "기본분류"),
    ("ca_id2", "2차분류"),
    ("ca_id3", "3차분류"),
    ("it_name", "상품명"),
    ("it_maker", "제조사"),
    ("it_origin", "원산지"),
    ("it_brand", "브랜드"),
    ("it_model", "모델"),
    ("it_type1", "히트"),
    ("it_type2", "추천"),
    ("it_type3", "신상품"),
    ("it_type4", "인기"),
    ("it_type5", "할인"),
    ("it_basic", "기본설명"),
    ("it_explan", "상품설명"),
    ("it_mobile_explan", "모바일 상품설명(사용 안 함)"),
    ("it_cust_price", "시중가격"),
    ("it_price", "판매가격"),
    ("it_tel_inq", "전화문의"),
    ("it_point", "포인트"),
    ("it_point_type", "포인트 유형"),
    ("it_sell_email", "판매자 이메일(사용 안 함)"),
    ("it_use", "판매가능"),
    ("it_stock_qty", "재고수량"),
    ("it_noti_qty", "재고통보수량(사용 안 함)"),
    ("it_buy_min_qty", "최소구매수량"),
    ("it_buy_max_qty", "최대구매수량"),
    ("it_notax", "과세유형"),
    ("it_order", "출력순서"),
    *((f"it_img{number}", f"이미지{number}") for number in range(1, IMAGE_COUNT + 1)),
)
FIELD_NAMES = tuple(name for name, _label in COLUMNS)
# codes the .xlsx template formats as text, so Excel keeps a long or zero-led code as typed
TEXT_COLUMNS = tuple(FIELD_NAMES.index(name) for name in ("it_id", "ca_id", "ca_id2", "ca_id3"))
LABEL_FIELDS = {label: name for name, label in COLUMNS}
# youngcart columns this model has no place for: read and ignored
IGNORED_FIELDS = {"it_mobile_explan", "it_sell_email", "it_noti_qty"}
TEXT_FIELDS = {"it_maker": 255, "it_origin": 255, "it_brand": 255, "it_model": 255, "it_name": 255}
LONG_TEXT_FIELDS = ("it_basic", "it_explan")
FLAG_FIELDS = ("it_type1", "it_type2", "it_type3", "it_type4", "it_type5", "it_tel_inq")
# field: (default on create, minimum, maximum)
NUMBER_FIELDS = {
    "it_cust_price": (0, 0, MAX_PRICE),
    "it_price": (0, 0, MAX_PRICE),
    "it_point": (0, 0, MAX_PRICE),
    "it_point_type": (0, 0, 2),
    "it_stock_qty": (9999, 0, MAX_STOCK),
    "it_buy_min_qty": (1, 0, MAX_STOCK),
    "it_buy_max_qty": (0, 0, MAX_STOCK),
    "it_notax": (0, 0, 1),
    "it_order": (0, -MAX_STOCK, MAX_STOCK),
}
TRUE_VALUES = {"1", "y", "yes", "o", "true", "on", "예", "사용"}
FALSE_VALUES = {"0", "n", "no", "x", "false", "off", "아니오", "미사용"}
IT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
SCIENTIFIC_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+[eE][-+]?[0-9]+")
LEGACY_IMAGE_PREFIX = "/data/item/"


class RowConflict(Exception):
    """The database changed between validation and saving a row."""


@dataclass
class ImportRow:
    line: int
    it_id: str = ""
    it_name: str = ""
    action: str = ""  # create | update | error
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    values: dict = field(default_factory=dict)
    saved: bool = False

    @property
    def ok(self):
        return not self.errors

    @property
    def action_label(self):
        return {"create": "신규 등록", "update": "기존 상품 수정"}.get(self.action, "오류")


@dataclass
class ImportReport:
    rows: list
    applied: bool = False
    ignored_columns: list = field(default_factory=list)

    @property
    def valid_count(self):
        return sum(1 for row in self.rows if row.ok)

    @property
    def error_count(self):
        return sum(1 for row in self.rows if not row.ok)

    @property
    def saved_count(self):
        return sum(1 for row in self.rows if row.saved)


def template_rows():
    """Header rows and one sample product for the downloadable template."""
    sample = {
        "it_id": "1700000001",
        "ca_id": "10",
        "it_name": "예시 상품",
        "it_maker": "제조사",
        "it_origin": "국내산",
        "it_brand": "브랜드",
        "it_model": "MODEL-1",
        "it_type1": "1",
        "it_basic": "한 줄 설명",
        "it_explan": "<p>상품 상세 설명</p>",
        "it_cust_price": "12000",
        "it_price": "10000",
        "it_point": "0",
        "it_point_type": "0",
        "it_use": "1",
        "it_stock_qty": "100",
        "it_buy_min_qty": "1",
        "it_buy_max_qty": "0",
        "it_notax": "0",
        "it_order": "0",
        "it_img1": "https://example.com/item.jpg",
    }
    return [[label for _name, label in COLUMNS], list(FIELD_NAMES)], [[sample.get(name, "") for name in FIELD_NAMES]]


def _column_map(rows):
    """(index of the first data row, {field: column}) from the header rows, or (None, {})."""
    for position, row in enumerate(rows[:3]):
        names = [cell.strip() for cell in row]
        if "it_id" in names:
            return position + 1, {name: index for index, name in enumerate(names) if name in FIELD_NAMES}
    for position, row in enumerate(rows[:3]):
        labels = [cell.strip() for cell in row]
        if "상품코드" in labels:
            mapping = {LABEL_FIELDS[label]: index for index, label in enumerate(labels) if label in LABEL_FIELDS}
            start = position + 1
            # the youngcart sheet has the field-name row right under the labels
            if start < len(rows) and "it_id" in rows[start]:
                start += 1
            return start, mapping
    return None, {}


def _clean_it_id(value):
    text = str(value or "").strip()
    if SCIENTIFIC_RE.fullmatch(text):
        # Excel shows a long numeric code as 1.7E+09 (youngcart: sprintf("%.0f"))
        try:
            text = format(Decimal(text).quantize(Decimal(1)), "f")
        except InvalidOperation:
            return ""
    return text


def _number(value, minimum, maximum):
    text = str(value or "").replace(",", "").replace("원", "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not re.fullmatch(r"-?\d+", text):
        return None
    number = int(text)
    return number if minimum <= number <= maximum else None


def _flag(value):
    text = str(value or "").strip().lower()
    if text in TRUE_VALUES:
        return "1"
    if text in FALSE_VALUES or not text:
        return ""
    return None


def clean_image_url(value):
    """An http(s) URL or a youngcart data/item path as the stored image URL; "" if unsafe."""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.IGNORECASE):
        try:
            parsed = urlsplit(text)
        except ValueError:
            return ""
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return ""
        return text
    if text.startswith("//"):
        return ""
    relative = text.lstrip("/")
    if relative.startswith("data/item/"):
        relative = relative[len("data/item/"):]
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts) or any(char in relative for char in "?#<>\"'"):
        return ""
    return LEGACY_IMAGE_PREFIX + "/".join(parts)


def _cell(row, mapping, name):
    index = mapping.get(name)
    return row[index].strip() if index is not None and index < len(row) else ""


def _validate_row(line, row, mapping, *, mode, categories, existing, seen):
    item = ImportRow(line=line)
    item.it_id = _clean_it_id(_cell(row, mapping, "it_id"))
    item.it_name = _cell(row, mapping, "it_name")
    if not item.it_id:
        item.errors.append("상품코드가 없습니다.")
    elif not IT_ID_RE.fullmatch(item.it_id):
        item.errors.append("상품코드는 영문·숫자·_·- 40자 이내로 입력하세요.")
    elif item.it_id in seen:
        item.errors.append(f"{seen[item.it_id]}행과 상품코드가 같습니다.")
    else:
        seen[item.it_id] = line
    is_update = item.it_id in existing
    if is_update and mode != MODE_UPDATE:
        item.errors.append("이미 있는 상품코드입니다. 기존 상품을 고치려면 '기존 상품 수정'을 고르세요.")
    item.action = "update" if is_update else "create"
    values = {}

    for name in ("ca_id", "ca_id2", "ca_id3"):
        code = _cell(row, mapping, name)
        if not code:
            if name == "ca_id" and not is_update:
                item.errors.append("기본분류가 없습니다.")
            continue
        if code not in categories:
            item.errors.append(f"분류 '{code}'이(가) 없습니다.")
            continue
        values[{"ca_id": "category_id", "ca_id2": "category2_id", "ca_id3": "category3_id"}[name]] = code

    if not item.it_name and not is_update:
        item.errors.append("상품명이 없습니다.")
    for name, limit in TEXT_FIELDS.items():
        text = _cell(row, mapping, name)
        if len(text) > limit:
            item.errors.append(f"{name}은(는) {limit}자 이내로 입력하세요.")
        elif text:
            values[name] = text
    for name in LONG_TEXT_FIELDS:
        text = _cell(row, mapping, name)
        if text:
            values[name] = text
    for name in FLAG_FIELDS:
        raw = _cell(row, mapping, name)
        flag = _flag(raw)
        if flag is None:
            item.errors.append(f"{name}은(는) 1(사용) 또는 0(미사용)으로 입력하세요.")
        elif raw:
            values[name] = flag
    use = _cell(row, mapping, "it_use")
    if use:
        flag = _flag(use)
        if flag is None:
            item.errors.append("판매가능은 1(판매) 또는 0(판매 안 함)으로 입력하세요.")
        else:
            values["it_use"] = flag or "0"
    for name, (_default, minimum, maximum) in NUMBER_FIELDS.items():
        raw = _cell(row, mapping, name)
        if not raw:
            continue
        number = _number(raw, minimum, maximum)
        if number is None:
            item.errors.append(f"{name} 값 '{raw[:20]}'이(가) 올바르지 않습니다 ({minimum:,}~{maximum:,}의 정수).")
        else:
            values[name] = number

    # youngcart would store a blank 판매가격 as 0 and sell the product for free; a new product on
    # sale needs a price unless it is a 전화문의 product (or is added as not on sale)
    if (
        not is_update
        and not values.get("it_price")
        and values.get("it_tel_inq") != "1"
        and values.get("it_use", "1") == "1"
        and not any("it_price" in error for error in item.errors)
    ):
        item.errors.append(
            "판매가격이 없습니다. 가격을 넣거나, 가격 없이 올리려면 전화문의를 1 또는 판매가능을 0으로 두세요."
        )

    images = []
    image_given = False
    for number in range(1, IMAGE_COUNT + 1):
        raw = _cell(row, mapping, f"it_img{number}")
        if not raw:
            continue
        image_given = True
        url = clean_image_url(raw)
        if not url:
            item.errors.append(f"이미지{number} 주소를 쓸 수 없습니다 (http(s) 주소 또는 data/item 경로).")
        elif url not in images:
            images.append(url)
    if image_given:
        values["images"] = images
    ignored = [name for name in IGNORED_FIELDS if _cell(row, mapping, name)]
    if ignored:
        item.notes.append("저장하지 않는 항목: " + ", ".join(sorted(ignored)))
    item.values = values
    if item.errors:
        item.action = "error"
    return item


def parse_products(uploaded, *, mode=MODE_CREATE):
    """Read and validate the upload; nothing is saved. Raises SpreadsheetError."""
    from .spreadsheet import SpreadsheetError

    rows = read_upload(uploaded, max_rows=MAX_ROWS + 2)
    start, mapping = _column_map(rows)
    if start is None or "it_id" not in mapping:
        raise SpreadsheetError("항목 이름 행을 찾을 수 없습니다. 내려받은 양식의 1~2행(항목 이름)을 지우지 말고 올려 주세요.")
    data = rows[start:]
    if not data:
        raise SpreadsheetError("등록할 상품 행이 없습니다.")
    if len(data) > MAX_ROWS:
        raise SpreadsheetError(f"한 번에 {MAX_ROWS:,}개 상품까지 올릴 수 있습니다.")
    codes = {_clean_it_id(_cell(row, mapping, "it_id")) for row in data}
    existing = set(ShopProduct.objects.filter(pk__in=[code for code in codes if code]).values_list("pk", flat=True))
    category_codes = {_cell(row, mapping, name) for row in data for name in ("ca_id", "ca_id2", "ca_id3")}
    categories = set(ShopCategory.objects.filter(pk__in=[code for code in category_codes if code]).values_list("pk", flat=True))
    seen = {}
    parsed = [
        _validate_row(start + offset + 1, row, mapping, mode=mode, categories=categories, existing=existing, seen=seen)
        for offset, row in enumerate(data)
    ]
    ignored_columns = [name for name in FIELD_NAMES if name not in mapping and name not in IGNORED_FIELDS]
    return ImportReport(rows=parsed, ignored_columns=ignored_columns)


def _apply_images(product, images):
    product.images = [{"url": url, "alt": product.it_name} for url in images]
    product.image_url = images[0] if images else ""


def _create(item):
    values = {name: default for name, (default, _min, _max) in NUMBER_FIELDS.items()}
    values.update({key: value for key, value in item.values.items() if key != "images"})
    values.setdefault("it_use", "1")
    product = ShopProduct(it_id=item.it_id, **values)
    _apply_images(product, item.values.get("images", []))
    product.save(force_insert=True)
    return product


def _update(item, actor, reason):
    product = ShopProduct.objects.select_for_update().get(pk=item.it_id)
    before_stock = int(product.it_stock_qty)
    for key, value in item.values.items():
        if key != "images":
            setattr(product, key, value)
    fields = [key for key in item.values if key != "images"]
    if "images" in item.values:
        _apply_images(product, item.values["images"])
        fields += ["images", "image_url"]
    product.save(update_fields=[*fields, "updated_at"])
    if product.it_stock_qty != before_stock:
        ShopStockAdjustment.objects.create(
            product=product,
            it_id=product.it_id,
            it_name=product.it_name,
            scope="product",
            before_qty=before_stock,
            delta=product.it_stock_qty - before_stock,
            after_qty=product.it_stock_qty,
            reason=reason,
            actor=actor,
        )
    return product


def apply_products(report, *, actor, on_saved=None, reason="상품 엑셀 일괄수정"):
    """Save the valid rows of ``report`` (each in its own transaction). A row that fails to save
    (a product added meanwhile with the same code ...) is marked with the error instead."""
    for item in report.rows:
        if not item.ok:
            continue
        try:
            with transaction.atomic():
                if item.action == "update":
                    product = _update(item, actor, reason)
                else:
                    if ShopProduct.objects.filter(pk=item.it_id).exists():
                        raise RowConflict("그 사이에 같은 상품코드의 상품이 등록되었습니다.")
                    product = _create(item)
        except ShopProduct.DoesNotExist:
            item.errors.append("그 사이에 상품이 삭제되었습니다.")
            item.action = "error"
            continue
        except RowConflict as exc:
            item.errors.append(str(exc))
            item.action = "error"
            continue
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the rest; it is reported
            logger.exception("Product import row %s (%s) failed.", item.line, item.it_id)
            item.errors.append(f"저장하지 못했습니다: {exc}")
            item.action = "error"
            continue
        item.saved = True
        item.it_name = product.it_name
        if on_saved:
            on_saved(product, item)
    report.applied = True
    return report
