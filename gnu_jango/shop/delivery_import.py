"""송장 엑셀 일괄 등록 (youngcart adm/shop_admin/orderdelivery.php, orderdeliveryexcel.php,
orderdeliveryupdate.php).

The download lists the orders that are 준비 with youngcart's ten columns; the admin fills in
배송회사 and 운송장번호 and uploads the sheet back (.xlsx or CSV, shop/spreadsheet.py). Each order that is still 준비 gets the courier
and invoice and moves to 배송 through the regular order flow (move_order_status), which stamps
the invoice time, moves the lines and queues the 배송 mail. Any other row is reported and left.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from .delivery import find_delivery_company
from .models import ShopOrder
from .order_flow import canonical_status, move_order_status
from .order_statuses import STATUS_READY, STATUS_SHIPPING
from .spreadsheet import ExcelText, SpreadsheetError, read_upload

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
READY_SPELLINGS = (STATUS_READY, "ready")
SCIENTIFIC_HINT = "E+"
MAX_INVOICE_LENGTH = 100
HEADERS = (
    "주문번호",
    "주문자명",
    "주문자전화1",
    "주문자전화2",
    "배송자명",
    "배송지전화1",
    "배송지전화2",
    "배송지주소",
    "배송회사",
    "운송장번호",
)
# the 20-digit order number and the invoice stay text in the .xlsx sheet (no 2.03E+19)
TEXT_COLUMNS = (HEADERS.index("주문번호"), HEADERS.index("운송장번호"))
HEADER_ALIASES = {
    "od_id": ("주문번호", "od_id"),
    "company": ("배송회사", "택배사", "od_delivery_company"),
    "invoice": ("운송장번호", "송장번호", "od_invoice"),
}
# youngcart orderdeliveryupdate.php reads columns A, I and J
POSITIONAL = {"od_id": 0, "company": 8, "invoice": 9}


@dataclass
class DeliveryRow:
    line: int
    od_id: str = ""
    company: str = ""
    invoice: str = ""
    customer: str = ""
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    saved: bool = False

    @property
    def ok(self):
        return not self.errors


@dataclass
class DeliveryReport:
    rows: list
    applied: bool = False

    @property
    def valid_count(self):
        return sum(1 for row in self.rows if row.ok)

    @property
    def error_count(self):
        return sum(1 for row in self.rows if not row.ok)

    @property
    def saved_count(self):
        return sum(1 for row in self.rows if row.saved)


def template_rows(default_company="", limit=MAX_ROWS):
    """The 준비 orders as youngcart's delivery sheet (orderdeliveryexcel.php)."""
    orders = ShopOrder.objects.filter(od_status__in=READY_SPELLINGS).order_by("od_id")[:limit]
    rows = []
    for order in orders:
        address = " ".join(part for part in (order.od_b_addr1, order.od_b_addr2, order.od_b_addr3) if part)
        if order.od_b_zip:
            address = f"({order.od_b_zip}) {address}"
        rows.append(
            [
                ExcelText(order.od_id),
                order.od_name,
                order.od_tel,
                order.od_hp,
                order.od_b_name,
                order.od_b_tel,
                order.od_b_hp,
                address,
                order.od_delivery_company or default_company,
                ExcelText(order.od_invoice) if order.od_invoice else "",
            ]
        )
    return [list(HEADERS)], rows


def _columns(header):
    names = [cell.strip() for cell in header]
    mapping = {}
    for key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in names:
                mapping[key] = names.index(alias)
                break
    return mapping


def _cell(row, index):
    return row[index].strip() if index is not None and index < len(row) else ""


def normalize_company(value):
    """The listed courier name for ``value`` (youngcart's partial match), else the value."""
    text = " ".join(str(value or "").split())
    entry = find_delivery_company(text)
    return (entry[0], True) if entry else (text, False)


def parse_deliveries(uploaded):
    rows = read_upload(uploaded, max_rows=MAX_ROWS + 1)
    mapping = _columns(rows[0])
    if len(mapping) == len(HEADER_ALIASES):
        data = rows[1:]
        start = 2
    elif "주문번호" in rows[0] or any(cell in HEADERS for cell in rows[0]):
        raise SpreadsheetError("주문번호·배송회사·운송장번호 열을 찾을 수 없습니다. 내려받은 양식의 첫 행을 그대로 두세요.")
    else:
        # no header row: youngcart's column positions from the first row
        mapping = dict(POSITIONAL)
        data = rows
        start = 1
    if not data:
        raise SpreadsheetError("등록할 송장 행이 없습니다.")
    if len(data) > MAX_ROWS:
        raise SpreadsheetError(f"한 번에 {MAX_ROWS:,}건까지 올릴 수 있습니다.")
    ids = [_cell(row, mapping["od_id"]).lstrip("'") for row in data]
    orders = ShopOrder.objects.in_bulk([value for value in ids if value])
    seen = {}
    parsed = []
    for offset, row in enumerate(data):
        item = DeliveryRow(line=start + offset)
        item.od_id = ids[offset]
        company, listed = normalize_company(_cell(row, mapping["company"]))
        item.company = company
        item.invoice = " ".join(_cell(row, mapping["invoice"]).split())
        if not item.od_id:
            item.errors.append("주문번호가 없습니다.")
        elif SCIENTIFIC_HINT in item.od_id.upper():
            item.errors.append("주문번호가 지수 형식(예: 2.03E+19)으로 바뀌었습니다. 엑셀에서 주문번호 열을 텍스트로 두고 저장하세요.")
        elif item.od_id in seen:
            item.errors.append(f"{seen[item.od_id]}행과 주문번호가 같습니다.")
        else:
            seen[item.od_id] = item.line
        order = orders.get(item.od_id) if item.od_id else None
        if item.od_id and order is None:
            item.errors.append("주문이 없습니다.")
        elif order is not None:
            item.customer = order.od_b_name or order.od_name
            status = canonical_status(order.od_status)
            if status != STATUS_READY:
                item.errors.append(f"'{status or '-'}' 상태의 주문입니다. 준비 상태의 주문만 배송으로 바꿉니다.")
        if not item.company:
            item.errors.append("배송회사가 없습니다.")
        elif not listed:
            item.notes.append("배송회사 목록에 없는 이름입니다. 배송조회 링크가 만들어지지 않습니다.")
        if not item.invoice:
            item.errors.append("운송장번호가 없습니다.")
        elif SCIENTIFIC_HINT in item.invoice.upper():
            item.errors.append("운송장번호가 지수 형식(예: 1.23E+11)으로 바뀌었습니다. 엑셀에서 운송장번호 열을 텍스트로 두고 저장하세요.")
        elif len(item.invoice) > MAX_INVOICE_LENGTH:
            item.errors.append(f"운송장번호는 {MAX_INVOICE_LENGTH}자 이내로 입력하세요.")
        if len(item.company) > 100:
            item.errors.append("배송회사는 100자 이내로 입력하세요.")
        parsed.append(item)
    return DeliveryReport(rows=parsed)


class _MoveFailed(Exception):
    pass


def apply_deliveries(report, *, actor, on_saved=None, send_sms=False):
    """Register the invoices of the valid rows and move those orders to 배송, one transaction per
    order (the 배송 mail goes out once that order commits). The 배송 text (de_sms_use5) goes out
    only with ``send_sms`` (orderdelivery.php's 배송안내 SMS box), still within the SMS limits."""
    now_label = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    for item in report.rows:
        if not item.ok:
            continue
        try:
            with transaction.atomic():
                order = ShopOrder.objects.select_for_update().filter(pk=item.od_id).first()
                if order is None:
                    raise _MoveFailed("주문이 없습니다.")
                if canonical_status(order.od_status) != STATUS_READY:
                    raise _MoveFailed("그 사이에 주문 상태가 바뀌었습니다.")
                order.od_delivery_company = item.company
                order.od_invoice = item.invoice
                order.od_invoice_time = now_label
                order.save(update_fields=["od_delivery_company", "od_invoice", "od_invoice_time"])
                result = move_order_status(order, STATUS_SHIPPING, actor=actor, send_sms=send_sms)
                if not result:
                    raise _MoveFailed(result.message or "배송으로 바꾸지 못했습니다.")
        except _MoveFailed as exc:
            item.errors.append(str(exc))
            continue
        except Exception as exc:  # noqa: BLE001 - reported per row; the other orders go on
            logger.exception("Delivery upload row %s (%s) failed.", item.line, item.od_id)
            item.errors.append(f"처리하지 못했습니다: {exc}")
            continue
        item.saved = True
        if on_saved:
            on_saved(order, item)
    report.applied = True
    return report
