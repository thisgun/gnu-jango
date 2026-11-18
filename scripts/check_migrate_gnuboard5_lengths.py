"""List every Django field migrate_gnuboard5 can overflow from a Gnuboard5 column.

PostgreSQL refuses a value longer than a varchar(n) and the whole --apply rolls back, while SQLite
stores it, so an overflow shows up only on the production database. This reads the importer's code
for each `"field": scalar(row, "column")`, `field=...` and `obj.field = ...`, finds the Django field
it lands in, and compares that field's max_length with the column's type in the source's
information_schema. A read cut by `text(..., max_length=n)` or `[:n]` counts as cut to n.

    python scripts/check_migrate_gnuboard5_lengths.py --source-root "<Gnuboard5 root>"

MySQL is only read. Exit status 1 when a column can overflow its field.
"""

import argparse
import ast
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import models  # noqa: E402

from gnu_jango.core.management.commands import migrate_gnuboard5 as command  # noqa: E402

STRING_READERS = {"scalar", "text"}
NOT_TEXT = {"bool", "len", "int", "integer", "bool_char", "max", "min", "exists", "filter", "get", "first"}
SAME_LENGTH = {"str", "strip", "lower", "upper", "casefold"}
# importer helpers that cut what they return, and to how many characters
HELPER_CUTS = {
    "safe_email": 254,
    "unique_email": 254,
    "unique_nickname": 100,
    "copy_legacy_board_file": 100,  # legacy_board_file_target
    "_social_identity_config_name": 50,  # a prefix and a 40-character digest
}
# (importer method, model, field) the importer keeps short in a way this scan cannot see, and why
KNOWN_SAFE = {
    ("import_board_goods", "Post_good", "bg_flag"): "only good and nogood get through",
    ("import_member_social", "User", "email"): "a key of the link's JSON value, not a User write",
    ("import_member_social", "User", "username"): "a key of the link's JSON value, not a User write",
}
WRITE_METHODS = {"update_or_create", "get_or_create", "create"}
NOT_FIELDS = {"defaults", "default", "max_length", "save", "update_fields"}
# importers import_selected calls outside its importers table
EXTRA_TABLES = {
    "import_member_avatars": "member_table",
    "import_shop_product_metrics": "g5_shop_item_table",
    "import_shop_product_tax_flags": "g5_shop_item_table",
    "import_shop_product_categories": "g5_shop_item_table",
}
UNBOUNDED = float("inf")


def command_models():
    found = {
        name: value
        for name, value in vars(command).items()
        if inspect.isclass(value) and issubclass(value, models.Model)
    }
    found["User"] = get_user_model()
    return found


def column_reads(expr, local_values, bound=UNBOUNDED, via=(), seen=()):
    """(column, cut, helpers) for each source column the expression can write as text. cut is the
    shortest slice or text(max_length=) the read passes through; helpers are the other calls it
    passes through, which may cut it too and need a look by hand."""
    if isinstance(expr, ast.Subscript):
        piece = expr.slice
        if isinstance(piece, ast.Slice) and piece.lower is None and isinstance(piece.upper, ast.Constant):
            bound = min(bound, piece.upper.value)
        yield from column_reads(expr.value, local_values, bound, via, seen)
        return
    if isinstance(expr, ast.Compare):
        return
    if isinstance(expr, ast.IfExp):
        for branch in (expr.body, expr.orelse):
            yield from column_reads(branch, local_values, bound, via, seen)
        return
    if isinstance(expr, ast.Call):
        func = expr.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name in NOT_TEXT:
            return
        if name in STRING_READERS and isinstance(func, ast.Name):
            if len(expr.args) >= 2 and isinstance(expr.args[1], ast.Constant) and isinstance(expr.args[1].value, str):
                cut = bound
                for keyword in expr.keywords:
                    if keyword.arg == "max_length" and isinstance(keyword.value, ast.Constant):
                        cut = min(cut, keyword.value.value)
                yield expr.args[1].value, cut, via
            return
        if name in HELPER_CUTS:
            bound = min(bound, HELPER_CUTS[name])
        elif name not in SAME_LENGTH:
            via = (*via, name)
    if isinstance(expr, ast.Name) and expr.id in local_values and expr.id not in seen:
        for value in local_values[expr.id]:
            yield from column_reads(value, local_values, bound, via, (*seen, expr.id))
        return
    for child in ast.iter_child_nodes(expr):
        yield from column_reads(child, local_values, bound, via, seen)


def field_writes(method):
    """(field name, owner hint, value expression) for every value the method writes to a model."""
    local_values = {}
    writes = []
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    local_values.setdefault(target.id, []).append(node.value)
                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    writes.append((target.attr, target.value.id, node.value))
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    writes.append((target.slice.value, None, node.value))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    writes.append((key.value, None, value))
        elif isinstance(node, ast.Call):
            func = node.func
            is_write = (isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS) or (
                isinstance(func, ast.Name) and func.id in MODELS
            )
            if is_write:
                writes.extend((kw.arg, None, kw.value) for kw in node.keywords if kw.arg and kw.arg not in NOT_FIELDS)
    return writes, local_values


def owner_models(field_name, owner_hint, method_models):
    def has(model):
        try:
            return model._meta.get_field(field_name)
        except Exception:
            return None

    named = [m for m in method_models if has(m)]
    if named:
        return named
    if owner_hint:
        hinted = [m for m in MODELS.values() if m.__name__.lower() == owner_hint.replace("_", "").lower() and has(m)]
        if hinted:
            return hinted
    return [m for m in set(MODELS.values()) if has(m)]


def method_tables(cls_node):
    """Command method name -> TABLE_KEYS key of the source table its rows come from."""
    methods = {node.name: node for node in cls_node.body if isinstance(node, ast.FunctionDef)}
    label_to_key = {label: key for key, label in command.TABLE_KEYS.items()}
    tables = dict(EXTRA_TABLES)
    for node in ast.walk(methods["import_selected"]):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "importers" for t in node.targets):
            for key, value in zip(node.value.keys, node.value.values):
                target = value.body if isinstance(value, ast.Lambda) else value
                target = target.func if isinstance(target, ast.Call) else target
                tables[target.attr] = label_to_key[key.value]
    changed = True
    while changed:
        changed = False
        for name, table_key in list(tables.items()):
            for node in ast.walk(methods[name]):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr in methods
                    and node.func.attr not in tables
                ):
                    tables[node.func.attr] = table_key
                    changed = True
    return methods, tables


def source_columns(cursor, database):
    cursor.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, COLUMN_TYPE "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s",
        [database],
    )
    columns = {}
    for row in cursor.fetchall():
        if row["CHARACTER_MAXIMUM_LENGTH"] is not None:
            capacity = int(row["CHARACTER_MAXIMUM_LENGTH"])
        elif row["NUMERIC_PRECISION"] is not None:
            capacity = int(row["NUMERIC_PRECISION"]) + 2  # sign and decimal point
        else:
            capacity = 26  # date, time and datetime(6) as text
        columns[(row["TABLE_NAME"], row["COLUMN_NAME"])] = (capacity, row["COLUMN_TYPE"])
    return columns


def resolve_table(table_key, config, columns):
    table = config["tables"].get(table_key, "")
    if table_key == "write_prefix":
        boards = sorted({name for name, _ in columns if name.startswith(table)})
        return boards[0] if boards else ""
    return table


MODELS = command_models()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-root", default=str(command.DEFAULT_SOURCE_ROOT))
    options = parser.parse_args()
    config = command.parse_php_config(Path(options.source_root) / "data" / "dbconfig.php")

    tree = ast.parse(Path(command.__file__).read_text(encoding="utf-8"))
    cls_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Command")
    methods, tables = method_tables(cls_node)

    with command.mysql_connection(config) as connection, connection.cursor() as cursor:
        columns = source_columns(cursor, config["database"])
        checked, findings, unresolved = 0, set(), []
        for name, table_key in sorted(tables.items()):
            table = resolve_table(table_key, config, columns)
            writes, local_values = field_writes(methods[name])
            method_models = {
                MODELS[n.id] for n in ast.walk(methods[name]) if isinstance(n, ast.Name) and n.id in MODELS
            }
            for field_name, owner_hint, value in writes:
                reads = list(column_reads(value, local_values))
                if not reads:
                    continue
                owners = owner_models(field_name, owner_hint, method_models)
                if not owners:
                    unresolved.append(f"NOT A FIELD     {name}: {field_name} <- {', '.join(read[0] for read in reads)}")
                for model in owners:
                    max_length = getattr(model._meta.get_field(field_name), "max_length", None)
                    if not max_length:
                        continue
                    for column, cut, helpers in reads:
                        checked += 1
                        if (table, column) not in columns:
                            unresolved.append(
                                f"NO SUCH COLUMN  {name}: {model.__name__}.{field_name} <- {table}.{column}"
                            )
                            continue
                        capacity, column_type = columns[(table, column)]
                        if min(capacity, cut) <= max_length or (name, model.__name__, field_name) in KNOWN_SAFE:
                            continue
                        cursor.execute(f"SELECT MAX(CHAR_LENGTH(`{column}`)) AS n FROM `{table}`")
                        longest = cursor.fetchone()["n"] or 0
                        if helpers:
                            kind = "THROUGH HELPER "
                        elif "char" in column_type or "text" in column_type:
                            kind = "OVERFLOWS NOW  " if longest > max_length else "CAN OVERFLOW   "
                        else:
                            kind = "NUMBER         "
                        line = (
                            f"{model.__name__}.{field_name}({max_length}) <- {table}.{column} {column_type}, "
                            f"longest {longest} [{name}]"
                            + (f" via {', '.join(dict.fromkeys(helpers))}" if helpers else "")
                        )
                        findings.add((kind, line))

    print(f"Checked {checked} column-to-field write(s) in {len(tables)} importer method(s).")
    for kind, line in sorted(findings):
        print(f"{kind} {line}")
    for line in sorted(set(unresolved)):
        print(line)
    return 1 if any(kind.startswith(("OVERFLOWS", "CAN")) for kind, _ in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
