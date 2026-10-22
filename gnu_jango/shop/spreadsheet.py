"""Reading and writing the CSV files the bulk shop tools exchange with spreadsheet programs.

youngcart reads .xls uploads with PHPExcel (adm/shop_admin/itemexcelupdate.php,
orderdeliveryupdate.php). No spreadsheet library is installed here, so the tools take CSV, which
every spreadsheet program saves ("CSV UTF-8" in Excel). A CSV cell is only text: nothing in an
upload is evaluated, and a cell we write that starts like a formula is prefixed with ``'`` (the
reverse is undone on reading, so a downloaded template uploads back unchanged).
"""

import csv
import io
import re
from decimal import Decimal

from django.http import HttpResponse

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
# Excel saves "CSV UTF-8" with a BOM; an older "CSV" save of a Korean sheet is CP949
ENCODINGS = ("utf-8-sig", "cp949")
SPREADSHEET_EXTENSIONS = (".xls", ".xlsx", ".xlsm", ".ods")


TEXT_CODE_RE = re.compile(r"[0-9A-Za-z_-]{1,64}")
EXCEL_TEXT_RE = re.compile(r'="([0-9A-Za-z_-]{1,64})"')


class SpreadsheetError(ValueError):
    """The upload cannot be read at all (the message is shown to the admin)."""


class ExcelText(str):
    """A code Excel must keep as text: a 20-digit order number opened from a CSV would become
    2.03E+19 and lose its digits. Written as ="..." (Excel shows, and saves back, the text)."""


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)  # a number (a negative refund total) is not a formula
    text = str(value)
    if isinstance(value, ExcelText) and TEXT_CODE_RE.fullmatch(text):
        return f'="{text}"'
    return "'" + text if text[:1] in FORMULA_PREFIXES else text


def read_cell(value):
    text = str(value or "").strip()
    wrapped = EXCEL_TEXT_RE.fullmatch(text)
    if wrapped:
        return wrapped.group(1)
    # a cell this module wrote as '=..., or one typed that way to keep Excel from calculating
    if len(text) > 1 and text[0] == "'" and text[1] in FORMULA_PREFIXES:
        return text[1:]
    return text


def read_csv_upload(uploaded, *, max_rows, max_bytes=MAX_UPLOAD_BYTES):
    """The rows of an uploaded CSV file as lists of stripped strings (blank rows dropped).

    Raises SpreadsheetError for a missing, oversized, binary or unreadable file, or one with more
    than ``max_rows`` data rows (header rows included in the count)."""
    if not uploaded:
        raise SpreadsheetError("업로드할 CSV 파일을 선택하세요.")
    name = str(getattr(uploaded, "name", "") or "").lower()
    if name.endswith(SPREADSHEET_EXTENSIONS):
        raise SpreadsheetError(
            "엑셀 파일은 바로 읽을 수 없습니다. 엑셀에서 '다른 이름으로 저장 → CSV UTF-8(쉼표로 분리)'로 저장해 올려 주세요."
        )
    size = getattr(uploaded, "size", None)
    if size is not None and size > max_bytes:
        raise SpreadsheetError(f"파일이 너무 큽니다. {max_bytes // (1024 * 1024)}MB 이하로 나눠 올려 주세요.")
    raw = uploaded.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SpreadsheetError(f"파일이 너무 큽니다. {max_bytes // (1024 * 1024)}MB 이하로 나눠 올려 주세요.")
    if raw[:2] == b"PK" or raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or b"\x00" in raw[:4096]:
        raise SpreadsheetError(
            "CSV 파일이 아닙니다. 엑셀에서 'CSV UTF-8(쉼표로 분리)' 형식으로 저장해 올려 주세요."
        )
    text = None
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SpreadsheetError("파일의 문자 인코딩을 읽을 수 없습니다. UTF-8로 저장해 올려 주세요.")
    rows = []
    try:
        for row in csv.reader(io.StringIO(text, newline="")):
            cells = [read_cell(cell) for cell in row]
            if not any(cells):
                continue
            rows.append(cells)
            if len(rows) > max_rows:
                raise SpreadsheetError(f"한 번에 {max_rows:,}행까지 올릴 수 있습니다. 파일을 나눠 올려 주세요.")
    except csv.Error as exc:
        raise SpreadsheetError(f"CSV 형식을 읽을 수 없습니다: {exc}") from exc
    if not rows:
        raise SpreadsheetError("파일에 내용이 없습니다.")
    return rows


def csv_download(filename, header_rows, rows):
    """A CSV attachment Excel opens as UTF-8 (BOM), with formula-like cells neutralised."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")
    writer = csv.writer(response)
    for row in (*header_rows, *rows):
        writer.writerow([safe_cell(value) for value in row])
    return response
