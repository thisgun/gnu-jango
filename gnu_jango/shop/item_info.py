"""상품정보제공고시 (YoungCart it_info_gubun + it_info_value).

YoungCart keeps the notice as a PHP-serialized array of article key -> value
(adm/shop_admin/itemformupdate.php) and prints each row with the article title of the
product kind (lib/iteminfo.lib.php, skin/shop/basic/item.info.skin.php). Here the rows
are stored in ``ShopProduct.it_info_value`` as a JSON list of ``{"key", "title", "value"}``.

The PHP reader below understands only the scalar/array subset ``serialize()`` writes for
that table (``a``, ``s``, ``i``, ``d``, ``b``, ``N``); objects and references are refused,
so nothing in the imported text can build or run code.
"""
import json
import re

from .item_info_kinds import ITEM_INFO_KINDS

MAX_ITEM_INFO_ROWS = 100
_INT = re.compile(rb"-?\d+")


class _SerializedError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def expect(self, token):
        if not self.data.startswith(token, self.pos):
            raise _SerializedError(f"expected {token!r} at {self.pos}")
        self.pos += len(token)

    def number(self, end):
        stop = self.data.find(end, self.pos)
        if stop < 0:
            raise _SerializedError("unterminated number")
        raw = self.data[self.pos:stop]
        self.pos = stop + len(end)
        return raw

    def integer(self, end):
        raw = self.number(end)
        if not _INT.fullmatch(raw):
            raise _SerializedError("bad integer")
        return int(raw)

    def value(self, depth=0):
        kind = self.data[self.pos:self.pos + 2]
        if kind == b"N;":
            self.pos += 2
            return None
        self.pos += 2
        if kind == b"s:":
            length = self.integer(b":")
            self.expect(b'"')
            raw = self.data[self.pos:self.pos + length]
            if len(raw) != length:
                raise _SerializedError("truncated string")
            self.pos += length
            self.expect(b'";')
            return raw.decode("utf-8", errors="replace")
        if kind == b"i:":
            return self.integer(b";")
        if kind == b"b:":
            return self.integer(b";") != 0
        if kind == b"d:":
            raw = self.number(b";").decode("ascii", errors="replace")
            try:
                return float(raw)
            except ValueError as exc:
                raise _SerializedError("bad float") from exc
        if kind == b"a:":
            return self.array(depth + 1)
        raise _SerializedError(f"unsupported type {kind!r}")

    def array(self, depth, *, salvage=None):
        if depth > 8:
            raise _SerializedError("nested too deeply")
        count = self.integer(b":")
        self.expect(b"{")
        pairs = salvage if salvage is not None else []
        for _ in range(count):
            key = self.value(depth)
            if not isinstance(key, (str, int)):
                raise _SerializedError("bad array key")
            pairs.append((str(key), self.value(depth)))
        self.expect(b"}")
        return pairs


def parse_php_array(raw):
    """Return ``(pairs, complete)`` for a PHP-serialized array, or ``(None, False)``.

    A value cut short (an older import stored it in a 255-character column) still yields
    the rows read before the cut, with ``complete`` False.
    """
    text = str(raw or "").strip()
    if not text.startswith("a:"):
        return None, False
    reader = _Reader(text.encode("utf-8"))
    pairs = []
    try:
        reader.expect(b"a:")
        reader.array(1, salvage=pairs)
    except (_SerializedError, IndexError):
        return pairs, False
    return pairs, True


def _stripslashes(text):
    return re.sub(r"\\(.?)", r"\1", text, flags=re.DOTALL)


def kind_title(gubun):
    kind = ITEM_INFO_KINDS.get(str(gubun or ""))
    return kind["title"] if kind else ""


def _article(gubun, key):
    kind = ITEM_INFO_KINDS.get(str(gubun or ""))
    for article in kind["articles"] if kind else ():
        if article[0] == key:
            return article
    return None


def article_title(gubun, key):
    article = _article(gubun, key)
    return article[1] if article else str(key or "")


def _scalar_text(value):
    if value is None or isinstance(value, (list, tuple, dict)):
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    return str(value)


def _row(gubun, key, value, title=""):
    key = str(key or "").strip()
    if not key:
        return None
    return {"key": key, "title": str(title or "").strip() or article_title(gubun, key), "value": _scalar_text(value)}


def _rows(gubun, pairs):
    rows = [row for row in (_row(gubun, key, value) for key, value in pairs) if row]
    return rows[:MAX_ITEM_INFO_ROWS]


def _json_rows(gubun, data):
    if isinstance(data, dict) and set(data) <= {"gubun", "key", "value", "title"} and "value" in data:
        # an older smoke/seed format: one {"gubun", "key", "value"} record
        row = _row(gubun or data.get("gubun"), data.get("key") or data.get("title"), data.get("value"), data.get("title"))
        return [row] if row and row["value"] else []
    if isinstance(data, dict):
        return _rows(gubun, data.items())
    if isinstance(data, list):
        rows = []
        for item in data:
            if isinstance(item, dict):
                row = _row(gubun, item.get("key") or item.get("title"), item.get("value"), item.get("title"))
                if row:
                    rows.append(row)
        return rows[:MAX_ITEM_INFO_ROWS]
    return None


def parse_item_info_value(raw, gubun=""):
    """Rows from a YoungCart ``it_info_value`` (PHP-serialized) or a JSON copy of one.

    Returns ``None`` when the text is neither; a truncated serialized value gives its
    complete leading rows.
    """
    if isinstance(raw, (list, dict)):
        return _json_rows(gubun, raw)
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("a:"):
        best = []
        for candidate in (text, _stripslashes(text)):
            pairs, complete = parse_php_array(candidate)
            if complete:
                return _rows(gubun, pairs)
            if pairs and len(pairs) > len(best):
                best = pairs
        return _rows(gubun, best)
    if text[0] in "[{":
        try:
            return _json_rows(gubun, json.loads(text))
        except ValueError:
            return None
    return None


def item_info_rows(product):
    """The notice rows the product page shows, titles resolved from the product kind."""
    rows = parse_item_info_value(product.it_info_value, product.it_info_gubun) or []
    result = []
    for row in rows:
        article = _article(product.it_info_gubun, row["key"])
        result.append({
            "key": row["key"],
            "title": row["title"] or (article[1] if article else row["key"]),
            "value": row["value"],
            "example": article[2] if article else "",
        })
    return result


def item_info_kind_choices(current=""):
    choices = [("", "없음")] + [(code, kind["title"]) for code, kind in ITEM_INFO_KINDS.items()]
    if current and current not in ITEM_INFO_KINDS:
        choices.append((current, current))
    return choices


def item_info_to_text(rows):
    """The admin form's editable text: one ``title: value`` line per row."""
    lines = []
    for row in rows or []:
        if isinstance(row, dict):
            value = " ".join(str(row.get("value") or "").splitlines())
            lines.append(f"{row.get('title') or row.get('key') or ''}: {value}")
    return "\n".join(lines)


def item_info_from_text(text, gubun=""):
    """Parse the admin text back into rows; a title of the product kind gets its article key.

    Raises ``ValueError`` naming the first line without a ``title: value`` shape.
    """
    kind = ITEM_INFO_KINDS.get(str(gubun or ""))
    keys_by_title = {article[1]: article[0] for article in kind["articles"]} if kind else {}
    rows = []
    for number, line in enumerate(str(text or "").splitlines(), 1):
        if not line.strip():
            continue
        title, separator, value = line.partition(":")
        if not separator or not title.strip():
            raise ValueError(number)
        title = title.strip()
        rows.append({"key": keys_by_title.get(title, title), "title": title, "value": value.strip()})
    if len(rows) > MAX_ITEM_INFO_ROWS:
        raise ValueError(MAX_ITEM_INFO_ROWS + 1)
    return rows
