"""상품정보제공고시: keep every notice row in a JSON column.

Earlier imports copied YoungCart's PHP-serialized ``it_info_value`` into the 255-character
``it_info_title`` column, so the rows were cut short and shown as one garbled line. This
moves whatever can still be read (the complete leading rows of a cut value) into
``it_info_value`` and clears the copied text. A plain text that is not a serialized notice
stays in ``it_info_title``.

The reader is frozen here (a copy of the scalar/array subset shop/item_info.py reads, without
the product-kind titles: the product page resolves those when a row has none), so later changes
to that module cannot change what this migration does. A row that cannot be read is left as it
was; one bad row never stops the migration. The reverse step writes the rows back into
``it_info_title`` as PHP-serialized text, cut at 255 characters like the old import.
"""
import json
import logging
import re

from django.db import migrations, models

logger = logging.getLogger(__name__)

TITLE_MAX = 255
MAX_ROWS = 100
MAX_DEPTH = 8
_INT = re.compile(rb"-?\d+")


class _Unreadable(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def expect(self, token):
        if not self.data.startswith(token, self.pos):
            raise _Unreadable(f"expected {token!r} at {self.pos}")
        self.pos += len(token)

    def number(self, end):
        stop = self.data.find(end, self.pos)
        if stop < 0:
            raise _Unreadable("unterminated number")
        raw = self.data[self.pos:stop]
        self.pos = stop + len(end)
        return raw

    def integer(self, end):
        raw = self.number(end)
        if not _INT.fullmatch(raw):
            raise _Unreadable("bad integer")
        return int(raw)

    def value(self, depth):
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
                raise _Unreadable("truncated string")
            self.pos += length
            self.expect(b'";')
            return raw.decode("utf-8", errors="replace")
        if kind == b"i:":
            return self.integer(b";")
        if kind == b"b:":
            return self.integer(b";") != 0
        if kind == b"d:":
            try:
                return float(self.number(b";").decode("ascii", errors="replace"))
            except ValueError as exc:
                raise _Unreadable("bad float") from exc
        if kind == b"a:":
            return self.array(depth + 1)
        raise _Unreadable(f"unsupported type {kind!r}")

    def array(self, depth, salvage=None):
        if depth > MAX_DEPTH:
            raise _Unreadable("nested too deeply")
        count = self.integer(b":")
        self.expect(b"{")
        pairs = salvage if salvage is not None else []
        for _ in range(count):
            key = self.value(depth)
            if not isinstance(key, (str, int)):
                raise _Unreadable("bad array key")
            pairs.append((str(key), self.value(depth)))
        self.expect(b"}")
        return pairs


def _pairs(text):
    """(pairs, complete) of a PHP-serialized array; a cut value gives its leading pairs."""
    reader = _Reader(text.encode("utf-8"))
    pairs = []
    try:
        reader.expect(b"a:")
        reader.array(1, salvage=pairs)
    except (_Unreadable, IndexError):
        return pairs, False
    return pairs, True


def _scalar(value):
    if value is None or isinstance(value, (list, tuple, dict)):
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    return str(value)


def _rows(pairs):
    rows = []
    for key, value, title in pairs:
        key = str(key or "").strip()
        if key:
            rows.append({"key": key, "title": str(title or "").strip(), "value": _scalar(value)})
    return rows[:MAX_ROWS]


def serialized_rows(text):
    """The notice rows of a PHP-serialized (possibly addslashes-escaped, possibly cut) value."""
    best = []
    for candidate in (text, re.sub(r"\\(.?)", r"\1", text, flags=re.DOTALL)):
        pairs, complete = _pairs(candidate)
        if complete:
            best = pairs
            break
        if len(pairs) > len(best):
            best = pairs
    return _rows((key, value, "") for key, value in best)


def json_rows(text):
    """Rows of a JSON copy of the notice (an older seed format), None when it is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict) and "value" in data and set(data) <= {"gubun", "key", "value", "title"}:
        rows = _rows([(data.get("key") or data.get("title"), data.get("value"), data.get("title"))])
        return [row for row in rows if row["value"]]
    if isinstance(data, dict):
        return _rows((key, value, "") for key, value in data.items())
    if isinstance(data, list):
        return _rows(
            (item.get("key") or item.get("title"), item.get("value"), item.get("title"))
            for item in data
            if isinstance(item, dict)
        )
    return None


def move_info_rows(apps, schema_editor):
    ShopProduct = apps.get_model("shop", "ShopProduct")
    products = ShopProduct.objects.exclude(it_info_title="").only("it_id", "it_info_title")
    for product in products.iterator():
        text = product.it_info_title.strip()
        try:
            if text.startswith("a:"):
                rows = serialized_rows(text)
            elif text[:1] in ("[", "{"):
                rows = json_rows(text)
            else:
                rows = None
        except Exception:  # noqa: BLE001 - one unreadable row must not stop the migration
            logger.warning("it_info_title of product %s could not be read; left as it was", product.pk, exc_info=True)
            continue
        if rows is None:
            continue  # a plain notice text stays where it is
        ShopProduct.objects.filter(pk=product.pk).update(it_info_value=rows, it_info_title="")


def _php_string(value):
    text = str(value)
    return f's:{len(text.encode("utf-8"))}:"{text}";'


def serialize_rows(rows):
    """PHP serialize() of key -> value, as YoungCart stored it_info_value."""
    pairs = [
        (str(row.get("key") or ""), _scalar(row.get("value")))
        for row in rows
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    ]
    body = "".join(_php_string(key) + _php_string(value) for key, value in pairs)
    return f"a:{len(pairs)}:{{{body}}}" if pairs else ""


def restore_info_title(apps, schema_editor):
    ShopProduct = apps.get_model("shop", "ShopProduct")
    products = ShopProduct.objects.filter(it_info_title="").only("it_id", "it_info_value")
    for product in products.iterator():
        rows = product.it_info_value
        if not isinstance(rows, list) or not rows:
            continue
        try:
            text = serialize_rows(rows)
        except Exception:  # noqa: BLE001 - leave a row that cannot be written back as it is
            logger.warning("it_info_value of product %s could not be written back", product.pk, exc_info=True)
            continue
        if text:
            ShopProduct.objects.filter(pk=product.pk).update(it_info_title=text[:TITLE_MAX])


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0030_shoporder_refund_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopproduct",
            name="it_info_value",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(move_info_rows, restore_info_title),
    ]
