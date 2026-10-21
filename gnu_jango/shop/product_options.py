"""Product option rows (youngcart g5_shop_item_option) kept in ``ShopProduct.options``.

Each row is ``{"io_no", "io_id", "io_type", "io_price", "io_stock_qty", "io_noti_qty", "io_use"}``:

* 선택옵션 (``io_type`` 0): ``io_id`` joins up to three option values with chr(30), one per
  option name in ``it_option_subject`` ("색상,사이즈" -> "빨강\\x1eL").
* 추가옵션 (``io_type`` 1): ``io_id`` is "항목명\\x1e값"; ``it_supply_subject`` lists the item names.

The admin option builder (itemform.php 선택옵션 / 추가옵션) writes these rows and
``normalize_option_rows`` checks them on the server the way itemformupdate.php would, but refuses
bad input with a message instead of silently dropping it.
"""

import re

from django.core.exceptions import ValidationError

OPTION_SEPARATOR = "\x1e"  # youngcart chr(30)
MAX_OPTION_LEVELS = 3
MAX_INT = 2_147_483_647
# youngcart itemoption.php / itemsupply.php defaults for a freshly generated row
DEFAULT_OPTION_STOCK = 9999
DEFAULT_OPTION_NOTI = 100

# G5_OPTION_ID_FILTER strips quotes; itemformupdate.php drops ids that look like markup or script.
FORBIDDEN_OPTION_PATTERNS = (
    re.compile(r"['\"]"),
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
)
OPTION_ROW_KEYS = ("io_no", "io_id", "io_type", "io_price", "io_stock_qty", "io_noti_qty", "io_use")


def split_option_values(text):
    """'빨강, 파랑,,빨강' -> ['빨강', '파랑']: youngcart's comma list without blanks or repeats."""
    values = []
    for part in str(text or "").split(","):
        value = part.strip()
        if value and value not in values:
            values.append(value)
    return values


def option_combinations(value_lists):
    """Every combination of the option values, first option outermost (itemoption.php order)."""
    lists = [values for values in value_lists if values]
    if not lists:
        return []
    combos = [[]]
    for values in lists:
        combos = [[*combo, value] for combo in combos for value in values]
    return [OPTION_SEPARATOR.join(combo) for combo in combos]


def _forbidden(text):
    return any(pattern.search(text) for pattern in FORBIDDEN_OPTION_PATTERNS)


def _whole_number(value, label, position, *, minimum, default):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        value = int(value)
    if not isinstance(value, int):
        raise ValidationError(f"{position}: {label}은(는) 정수로 입력해 주세요.")
    if value < minimum or value > MAX_INT:
        if minimum == 0:
            raise ValidationError(f"{position}: {label}은(는) 0 이상 {MAX_INT:,} 이하로 입력해 주세요.")
        raise ValidationError(f"{position}: {label}은(는) {minimum:,} ~ {MAX_INT:,} 사이로 입력해 주세요.")
    return value


def _option_parts(io_id, io_type, position):
    if not isinstance(io_id, str) or not io_id.strip():
        raise ValidationError(f"{position}: 옵션 항목(io_id)이 비어 있습니다.")
    parts = [part.strip() for part in io_id.split(OPTION_SEPARATOR)]
    if any(not part for part in parts):
        raise ValidationError(f"{position}: 비어 있는 옵션 값이 있습니다.")
    if any(_forbidden(part) for part in parts):
        raise ValidationError(f"{position}: 옵션 값에 따옴표나 스크립트로 보이는 내용은 쓸 수 없습니다.")
    if any("," in part for part in parts):
        # the storefront option picker joins id, price and stock with commas
        raise ValidationError(f"{position}: 옵션 값에는 쉼표(,)를 쓸 수 없습니다.")
    if io_type == 0 and len(parts) > MAX_OPTION_LEVELS:
        raise ValidationError(f"{position}: 선택옵션은 {MAX_OPTION_LEVELS}단계까지만 쓸 수 있습니다.")
    if io_type == 1 and len(parts) != 2:
        raise ValidationError(f"{position}: 추가옵션은 '항목명{OPTION_SEPARATOR!r}값' 형식이어야 합니다.")
    return parts


def _stored_option_ids(stored):
    """(io_type, io_id) of the rows already saved on the product, exactly as stored."""
    ids = set()
    for row in stored if isinstance(stored, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("io_id"), str):
            continue
        io_type = row.get("io_type", 0)
        if io_type in (0, 1, "0", "1"):
            ids.add((int(io_type), row["io_id"]))
    return ids


def normalize_option_rows(rows, *, stored=None):
    """Checked, typed copies of the option rows; raises ValidationError (Korean) on bad input.

    Selection rows come first, then supplement rows, each in the given order, numbered by io_no.
    Missing numbers take the values the cart already assumes for them (price/stock/notice 0, used).

    A row whose io_id is one of the ``stored`` rows' (same type, same text) keeps that id as it is:
    ids imported from youngcart may hold quotes or commas, and must not block editing the stock or
    price of this or any other row. New or renamed rows are checked strictly."""
    if rows in (None, ""):
        return []
    if not isinstance(rows, list):
        raise ValidationError("옵션은 옵션 행의 목록(JSON 배열)이어야 합니다.")
    legacy_ids = _stored_option_ids(stored)
    seen = set()
    levels = None
    normalized = {0: [], 1: []}
    for index, row in enumerate(rows, 1):
        position = f"{index}번째 옵션"
        if not isinstance(row, dict):
            raise ValidationError(f"{position}: 옵션 행은 객체여야 합니다.")
        io_type = row.get("io_type", 0)
        if io_type in (0, 1, "0", "1"):
            io_type = int(io_type)
        else:
            raise ValidationError(f"{position}: io_type 은 0(선택옵션) 또는 1(추가옵션)이어야 합니다.")
        if (io_type, row.get("io_id")) in legacy_ids:
            io_id = row["io_id"]
            parts = io_id.split(OPTION_SEPARATOR)
        else:
            parts = _option_parts(row.get("io_id"), io_type, position)
            io_id = OPTION_SEPARATOR.join(parts)
        if io_type == 0:
            if levels is None:
                levels = len(parts)
            elif levels != len(parts):
                raise ValidationError(f"{position}: 선택옵션의 단계 수가 다른 옵션과 다릅니다.")
        key = (io_type, io_id)
        if key in seen:
            label = " > ".join(parts)
            raise ValidationError(f"{position}: '{label}' 옵션이 중복되었습니다.")
        seen.add(key)
        io_use = row.get("io_use", 1)
        if io_use in (True, False):
            io_use = int(io_use)
        if io_use not in (0, 1, "0", "1"):
            raise ValidationError(f"{position}: 사용여부는 0 또는 1이어야 합니다.")
        normalized[io_type].append({
            "io_id": io_id,
            "io_type": io_type,
            "io_price": _whole_number(row.get("io_price"), "추가금액", position, minimum=-MAX_INT, default=0),
            "io_stock_qty": _whole_number(row.get("io_stock_qty"), "재고수량", position, minimum=0, default=0),
            "io_noti_qty": _whole_number(row.get("io_noti_qty"), "통보수량", position, minimum=0, default=0),
            "io_use": int(io_use),
        })
    ordered = [*normalized[0], *normalized[1]]
    return [{"io_no": number, **row} for number, row in enumerate(ordered, 1)]


def _loose_row(row):
    def number(key, default):
        try:
            return int(str(row.get(key, default)).strip() or default)
        except (TypeError, ValueError):
            return str(row.get(key))

    return (
        number("io_type", 0),
        str(row.get("io_id") or "").strip(),
        number("io_price", 0),
        number("io_stock_qty", 0),
        number("io_noti_qty", 0),
        number("io_use", 1),
    )


def option_rows_equivalent(first, second):
    """True when two option lists say the same thing (ignoring io_no, key order and number
    spelling), so re-submitting stored rows unchanged is not treated as an edit."""
    if not isinstance(first, list) or not isinstance(second, list) or len(first) != len(second):
        return False
    if not all(isinstance(row, dict) for row in [*first, *second]):
        return False
    return [_loose_row(row) for row in first] == [_loose_row(row) for row in second]


def option_levels(rows):
    """How many option names the selection rows use (0 when there are none)."""
    for row in rows:
        if row.get("io_type") == 0:
            return len(str(row.get("io_id") or "").split(OPTION_SEPARATOR))
    return 0


def clean_option_subject(subject, rows):
    """it_option_subject for the rows: empty without selection rows, else one name per level.

    An empty subject is kept (the storefront labels the levels itself); a subject whose name count
    differs from the rows' levels is refused."""
    levels = option_levels(rows)
    if not levels:
        return ""
    names = [name.strip() for name in str(subject or "").split(",")]
    if names == [""]:
        return ""
    if any(not name for name in names) or any(_forbidden(name) for name in names):
        raise ValidationError("옵션명에 빈 값, 따옴표나 스크립트로 보이는 내용은 쓸 수 없습니다.")
    if len(names) != levels:
        raise ValidationError(
            f"옵션명은 {levels}개여야 합니다(현재 {len(names)}개). 옵션목록을 다시 생성해 주세요."
        )
    return ",".join(names)


def supply_subject(rows):
    """it_supply_subject: the supplement item names in order (itemformupdate.php $arr_spl)."""
    names = []
    for row in rows:
        if row.get("io_type") == 1:
            name = str(row.get("io_id") or "").split(OPTION_SEPARATOR)[0]
            if name not in names:
                names.append(name)
    return ",".join(names)
