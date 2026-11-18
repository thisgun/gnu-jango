import hashlib
import html
import ipaddress
import itertools
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, time
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.files.base import File
from django.core.files.images import get_image_dimensions
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.fields import AutoFieldMixin
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.html import strip_tags

from gnu_jango import defaults
from gnu_jango.api.community_common import _general_qa_product
from gnu_jango.api.community_qas import QA_ACTIVE_EXTENSION_RE, _qa_empty_meta, _qa_load_meta, _qa_save_meta
from gnu_jango.api.v1_auth import SOCIAL_PROVIDER_SPECS, _social_identity_config_name
from gnu_jango.notifications.context import suppress_notification_events
from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file, Post_good, Post_scrap
from gnu_jango.config import signals
from gnu_jango.config.models import Config
from gnu_jango.core.models import ContentPage, FAQItem, FAQMaster, New_win, Poll, PollChoice, PollComment, Site_menu
from gnu_jango.shop.models import (
    ShopAddress,
    ShopBanner,
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopCouponZone,
    ShopEvent,
    ShopEventItem,
    ShopOrder,
    ShopOrderData,
    ShopOrderItem,
    ShopPersonalPay,
    ShopProduct,
    ShopProductRelation,
    ShopQA,
    ShopReview,
    ShopStockNotification,
    ShopShippingCost,
    ShopShippingPolicy,
    ShopWishlist,
    ORDER_ITEM_STATUS_COMPLETED,
    generate_order_uid,
)
from gnu_jango.shop.item_info import parse_item_info_value
from gnu_jango.shop.order_flow import canonical_status
from gnu_jango.shop.order_statuses import STATUS_ORDERED, STATUS_PAID, STATUS_READY
from gnu_jango.users.hashers import convert_gnuboard_password_hash
from gnu_jango.users.models import Profile, User_Memo, User_Point

DEFAULT_SOURCE_ROOT = Path(r"C:\xampp824\www\gnuboard5_3")
TABLE_KEYS = {
    "member_table": "member",
    "point_table": "point",
    "memo_table": "memo",
    "group_table": "group",
    "board_table": "board",
    "write_prefix": "board_posts",
    "board_file_table": "board_files",
    "content_table": "content",
    "faq_master_table": "faq_master",
    "faq_table": "faq",
    "poll_table": "poll",
    "poll_etc_table": "poll_etc",
    "g5_shop_category_table": "shop_category",
    "g5_shop_banner_table": "shop_banner",
    "g5_shop_item_table": "shop_item",
    "g5_shop_event_table": "shop_event",
    "g5_shop_event_item_table": "shop_event_item",
    "g5_shop_default_table": "shop_default",
    "g5_shop_sendcost_table": "shop_sendcost",
    "g5_shop_item_option_table": "shop_item_option",
    "g5_shop_item_relation_table": "shop_item_relation",
    "g5_shop_order_table": "shop_order",
    "g5_shop_order_data_table": "shop_order_data",
    "g5_shop_cart_table": "shop_cart",
    "g5_shop_order_address_table": "shop_address",
    "g5_shop_coupon_zone_table": "shop_coupon_zone",
    "g5_shop_coupon_table": "shop_coupon",
    "g5_shop_coupon_log_table": "shop_coupon_log",
    "g5_shop_personalpay_table": "shop_personalpay",
    "g5_shop_item_use_table": "shop_review",
    "g5_shop_item_qa_table": "shop_qna",
    "g5_shop_item_stocksms_table": "shop_item_stocksms",
    # after the members, posts, products and product questions they point at
    "social_profile_table": "member_social",
    "qa_content_table": "qa_content",
    "g5_shop_wish_table": "shop_wish",
    "scrap_table": "scrap",
    "board_good_table": "board_good",
    "new_win_table": "new_win",
    "menu_table": "menu",
    "auth_table": "auth",
}
DEFAULT_TABLE_SUFFIXES = {
    "member_table": "member",
    "point_table": "point",
    "memo_table": "memo",
    "group_table": "group",
    "board_table": "board",
    "write_prefix": "write_",
    "board_file_table": "board_file",
    "content_table": "content",
    "faq_master_table": "faq_master",
    "faq_table": "faq",
    "poll_table": "poll",
    "poll_etc_table": "poll_etc",
    "g5_shop_category_table": "category",
    "g5_shop_banner_table": "banner",
    "g5_shop_item_table": "item",
    "g5_shop_event_table": "event",
    "g5_shop_event_item_table": "event_item",
    "g5_shop_default_table": "default",
    "g5_shop_sendcost_table": "sendcost",
    "g5_shop_item_option_table": "item_option",
    "g5_shop_item_relation_table": "item_relation",
    "g5_shop_order_table": "order",
    "g5_shop_order_data_table": "order_data",
    "g5_shop_cart_table": "cart",
    "g5_shop_order_address_table": "order_address",
    "g5_shop_coupon_zone_table": "coupon_zone",
    "g5_shop_coupon_table": "coupon",
    "g5_shop_coupon_log_table": "coupon_log",
    "g5_shop_personalpay_table": "personalpay",
    "g5_shop_item_use_table": "item_use",
    "g5_shop_item_qa_table": "item_qa",
    "g5_shop_item_stocksms_table": "item_stocksms",
    "social_profile_table": "member_social_profiles",
    "qa_content_table": "qa_content",
    "g5_shop_wish_table": "wish",
    "scrap_table": "scrap",
    "board_good_table": "board_good",
    "new_win_table": "new_win",
    "menu_table": "menu",
    "auth_table": "auth",
}
LEGACY_MEMBER_IMAGE_EXTENSIONS = {".gif", ".jpg", ".jpeg", ".png"}
EMAIL_MAX_LENGTH = 254  # Django's EmailField
# the algorithm of every hash convert_gnuboard_password_hash writes (gnu_jango.users.hashers)
GNUBOARD_HASH_PREFIX = "gnu_"


def parse_php_config(path):
    if not path.exists():
        raise CommandError(f"Gnuboard5 dbconfig file was not found: {path}")

    text = path.read_text(encoding="utf-8", errors="ignore")
    constants = dict(re.findall(r"define\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)", text))
    table_prefix = constants.get("G5_TABLE_PREFIX", "g5_")
    shop_prefix = constants.get("G5_SHOP_TABLE_PREFIX", "g5_shop_")
    tables = {}

    for key, expression in re.findall(r"\$g5\['([^']+)'\]\s*=\s*([^;]+);", text):
        tables[key] = resolve_php_table_expression(expression, table_prefix, shop_prefix)

    for key, suffix in TABLE_KEYS.items():
        if key not in tables:
            if key.startswith("g5_shop_"):
                tables[key] = f"{shop_prefix}{DEFAULT_TABLE_SUFFIXES[key]}"
            else:
                tables[key] = f"{table_prefix}{DEFAULT_TABLE_SUFFIXES[key]}"

    return {
        "host": constants.get("G5_MYSQL_HOST", "localhost"),
        "user": constants.get("G5_MYSQL_USER", ""),
        "password": constants.get("G5_MYSQL_PASSWORD", ""),
        "database": constants.get("G5_MYSQL_DB", ""),
        "charset": constants.get("G5_DB_CHARSET", "utf8mb4"),
        "table_prefix": table_prefix,
        "shop_prefix": shop_prefix,
        "tables": tables,
    }


def resolve_php_table_expression(expression, table_prefix, shop_prefix):
    value = expression.strip()
    value = value.replace("G5_TABLE_PREFIX", repr(table_prefix))
    value = value.replace("G5_SHOP_TABLE_PREFIX", repr(shop_prefix))
    parts = []
    for part in value.split("."):
        part = part.strip()
        if (part.startswith("'") and part.endswith("'")) or (
            part.startswith('"') and part.endswith('"')
        ):
            parts.append(part[1:-1])
    return "".join(parts)


def mask_secret(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def import_pymysql():
    try:
        import pymysql
    except ImportError as exc:
        raise CommandError(
            "PyMySQL is required for live Gnuboard5 MySQL import. "
            "Install it in the virtualenv or run without --apply for config/table inspection."
        ) from exc
    return pymysql


def mysql_connection(config):
    pymysql = import_pymysql()
    return pymysql.connect(
        host=config["host"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def scalar(row, key, default=""):
    value = row.get(key, default)
    return default if value is None else value


def text(row, key, default="", max_length=None):
    value = str(scalar(row, key, default) or "")
    return value[:max_length] if max_length else value


def integer(row, key, default=0):
    """The column as an int; ``default`` only when it is missing, NULL or blank (a 0 stays 0)."""
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def flag(row, key, default="0"):
    """A tinyint flag as the "0" or "1" its CharField(1) holds. Gnuboard tests it for truth in PHP, so
    0, NULL and blank are "0" and any other value is "1"; ``default`` only when the column is missing."""
    if key not in row:
        return default
    value = row[key]
    return "0" if value is None or str(value).strip() in ("", "0") else "1"


def post_reply_marker(row):
    """Preserve Gnuboard's alphabetic reply path when importing a post."""
    value = str(scalar(row, "wr_reply", "") or "").strip()
    if value == "0":
        return ""
    if len(value) > 10:
        raise ValueError("Gnuboard wr_reply values cannot exceed 10 characters.")
    return value


QA_HTML_LINE_END_RE = re.compile(r"<br\s*/?>|</(?:p|div|li|tr|h[1-6])\s*>", re.IGNORECASE)


def qa_plain_text(row):
    """A g5_qa_content body as the plain text a Django 1:1 inquiry holds and the page prints as is.
    qa_html 1 and 2 are editor HTML (qaview.php conv_content); qa_html 0 is text already."""
    content = text(row, "qa_content")
    if integer(row, "qa_html", 0) <= 0:
        return content
    content = html.unescape(strip_tags(QA_HTML_LINE_END_RE.sub("\n", content)))
    lines = content.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in lines)).strip()


def bool_char(row, key, default=True):
    value = str(scalar(row, key, "")).strip()
    if value == "":
        return default
    return value not in ("0", "N", "n", "false", "False")


def date_value(value):
    if not value:
        return None
    value_text = str(value).strip()
    if value_text.startswith("0000-00-00"):
        return None
    if hasattr(value, "date"):
        return value.date()
    try:
        return parse_date(value_text[:10])
    except ValueError:
        return None


def ymd_date_value(value):
    """g5_member.mb_leave_date / mb_intercept_date: "Ymd" text, empty when not set."""
    digits = re.sub(r"[^0-9]", "", str(value or ""))[:8]
    if len(digits) != 8 or digits == "00000000":
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None


def datetime_value(value):
    if not value:
        return timezone.now()
    if hasattr(value, "tzinfo"):
        if timezone.is_naive(value):
            return timezone.make_aware(value)
        return value
    parsed = parse_datetime(str(value))
    if parsed:
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
    parsed_date = parse_date(str(value)[:10])
    if parsed_date:
        return timezone.make_aware(datetime.combine(parsed_date, time.min))
    return timezone.now()


def optional_datetime_value(value):
    value = str(value or "").strip()
    if not value or value.startswith("0000-00-00"):
        return None
    return datetime_value(value)


def _safe_table(table):
    # Table names cannot be passed as bound parameters, so they are
    # interpolated into the SQL string. Restrict them to a strict identifier
    # pattern to prevent SQL injection via crafted table arguments.
    table = str(table or "")
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise ValueError(f"Unsafe table name: {table!r}")
    return table


def fetch_rows(cursor, table, limit=None):
    sql = f"SELECT * FROM `{_safe_table(table)}`"
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql)
    return list(cursor.fetchall())


def count_table(cursor, table):
    cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{_safe_table(table)}`")
    row = cursor.fetchone() or {}
    return int(row.get("cnt") or 0)


def table_exists(cursor, table):
    cursor.execute("SHOW TABLES LIKE %s", (table,))
    return bool(cursor.fetchone())


# youngcart get_it_stock_qty / get_option_stock_qty subtract the lines still waiting in these
# from the stock on the fly; it takes a line off the stock itself only later (ct_stock_use 1).
STOCK_PENDING_STATUSES = frozenset({STATUS_ORDERED, STATUS_PAID, STATUS_READY})


def cart_stock_taken(row):
    """A youngcart cart row whose quantity already came off it_stock_qty / io_stock_qty. A row of
    quantity 0 (imported as 1) holds nothing a cancel could put back."""
    return integer(row, "ct_stock_use", 0) == 1 and integer(row, "ct_qty", 0) > 0


def cart_stock_pending(row):
    """A youngcart cart row that youngcart's available stock still subtracts."""
    return (
        integer(row, "ct_stock_use", 0) == 0
        and integer(row, "ct_qty", 0) > 0
        and canonical_status(text(row, "ct_status")) in STOCK_PENDING_STATUSES
    )


def stock_key(it_id, io_id="", io_type=0):
    """The stock a line draws on: the option (it_id, io_id, io_type), or the product for io_id ""."""
    return (str(it_id).strip(), io_id, io_type if io_id else 0)


class Command(BaseCommand):
    help = (
        "Inspect or migrate selected Gnuboard5 MySQL tables into Django models. Run --apply against a fresh "
        "target. --apply stops on a target that holds an earlier import; --allow-rerun applies the same dump "
        "again, before go-live only. A newer dump always goes to a fresh target."
    )
    # g5_config.cf_admin: the only member Gnuboard treats as super admin (lib/common.lib.php is_admin)
    super_admin_id = ""

    def warn(self, message):
        self.stdout.write(self.style.WARNING(message))

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-root",
            default=str(DEFAULT_SOURCE_ROOT),
            help="Path to the Gnuboard5 PHP root. Defaults to C:\\xampp824\\www\\gnuboard5_3.",
        )
        parser.add_argument(
            "--dbconfig",
            default="",
            help="Explicit path to data/dbconfig.php. Overrides --source-root.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Write imported rows. Without this option the command only inspects/counts. Use a fresh "
                "target: --apply stops on a target that holds an earlier import."
            ),
        )
        parser.add_argument(
            "--allow-rerun",
            action="store_true",
            help=(
                "With --apply, apply the same dump again to a target that holds an earlier import, before "
                "go-live only. Members get their Gnuboard password, block state and admin flags back, and rows "
                "removed or edited in Django take the source rows again. A newer dump goes to a fresh target."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help=(
                "Limit rows per source table during import for smoke testing. Rows come in MySQL's own "
                "order (no ORDER BY), so a limited run may skip rows that point at rows it left out."
            ),
        )
        parser.add_argument(
            "--only",
            nargs="*",
            choices=sorted(
                [
                    *TABLE_KEYS.values(),
                    "member_avatars",
                    "public_config",
                    "shop_product_metrics",
                    "shop_product_tax_flags",
                    "shop_product_categories",
                ]
            ),
            help="Restrict import/counts to selected logical tables.",
        )
        parser.add_argument(
            "--skip-counts",
            action="store_true",
            help="Do not connect to MySQL for table counts during dry-run.",
        )

    @suppress_notification_events()
    def handle(self, *args, **options):
        source_root = Path(options["source_root"])
        self.source_root = source_root
        dbconfig = Path(options["dbconfig"]) if options["dbconfig"] else source_root / "data" / "dbconfig.php"
        config = parse_php_config(dbconfig)
        selected = set(options["only"] or [*TABLE_KEYS.values(), "public_config"])

        self.print_config(dbconfig, config, selected)
        if not options["apply"] and options["skip_counts"]:
            self.stdout.write(self.style.WARNING("Dry run only. Counts skipped by --skip-counts."))
            return

        if not options["apply"] and not self.has_pymysql():
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. PyMySQL is not installed, so live table counts were skipped."
                )
            )
            return

        with mysql_connection(config) as connection:
            with connection.cursor() as cursor:
                counts = self.get_counts(cursor, config, selected)
                self.print_counts(counts)
                if not options["apply"]:
                    self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to import rows."))
                    return

                if self.holds_an_earlier_import():
                    message = (
                        "This target already holds rows from an earlier migrate_gnuboard5 run. A rerun applies the "
                        "source rows again: members get their Gnuboard password, block state and admin flags back, "
                        "social links, scraps, wishlist items and votes removed in Django come back, and rows edited "
                        "or added in Django take the source rows. Import into a fresh target; a newer dump always "
                        "goes to a fresh target."
                    )
                    if not options["allow_rerun"]:
                        raise CommandError(
                            message + " Nothing was written. To apply the same dump again before go-live, add "
                            "--allow-rerun."
                        )
                    self.warn(message)
                with transaction.atomic():
                    imported = self.import_selected(cursor, config, selected, options["limit"] or None)

        for label, count in imported.items():
            self.stdout.write(self.style.SUCCESS(f"Imported {count} {label} row(s)."))

    def print_config(self, dbconfig, config, selected):
        self.stdout.write(f"Source config: {dbconfig}")
        self.stdout.write(f"MySQL host: {config['host']}")
        self.stdout.write(f"MySQL database: {config['database']}")
        self.stdout.write(f"MySQL user: {config['user']}")
        self.stdout.write(f"MySQL password: {mask_secret(config['password'])}")
        self.stdout.write("Selected table mapping:")
        for key, label in TABLE_KEYS.items():
            if label in selected:
                self.stdout.write(f"  {label}: {config['tables'].get(key, '')}")
        if "shop_product_metrics" in selected:
            self.stdout.write(f"  shop_product_metrics: {config['tables'].get('g5_shop_item_table', '')}")
        if "shop_product_tax_flags" in selected:
            self.stdout.write(f"  shop_product_tax_flags: {config['tables'].get('g5_shop_item_table', '')}")
        if "shop_product_categories" in selected:
            self.stdout.write(f"  shop_product_categories: {config['tables'].get('g5_shop_item_table', '')}")
        if "member_avatars" in selected:
            self.stdout.write(f"  member_avatars: {config['tables'].get('member_table', '')} + data/member_image")
        if "public_config" in selected:
            config_table, shop_default_table = self.public_config_tables(config)
            self.stdout.write(f"  public_config: {config_table} + {shop_default_table} (public fields only)")

    def has_pymysql(self):
        try:
            import_pymysql()
            return True
        except CommandError:
            return False

    def get_counts(self, cursor, config, selected):
        counts = {}
        for key, label in TABLE_KEYS.items():
            if label not in selected:
                continue
            if label == "board_posts":
                counts[label] = self.count_board_posts(cursor, config)
                continue
            table = config["tables"][key]
            if not table_exists(cursor, table):
                counts[label] = None
                continue
            counts[label] = count_table(cursor, table)
        if "shop_product_metrics" in selected:
            table = config["tables"]["g5_shop_item_table"]
            counts["shop_product_metrics"] = count_table(cursor, table) if table_exists(cursor, table) else None
        if "shop_product_tax_flags" in selected:
            table = config["tables"]["g5_shop_item_table"]
            counts["shop_product_tax_flags"] = count_table(cursor, table) if table_exists(cursor, table) else None
        if "shop_product_categories" in selected:
            table = config["tables"]["g5_shop_item_table"]
            counts["shop_product_categories"] = count_table(cursor, table) if table_exists(cursor, table) else None
        if "member_avatars" in selected:
            root = self.source_root / "data" / "member_image"
            counts["member_avatars"] = (
                sum(
                    1
                    for path in root.rglob("*")
                    if path.is_file() and path.suffix.lower() in LEGACY_MEMBER_IMAGE_EXTENSIONS
                )
                if root.is_dir()
                else None
            )
        if "public_config" in selected:
            tables = self.public_config_tables(config)
            counts["public_config"] = sum(
                count_table(cursor, table)
                for table in tables
                if table and table_exists(cursor, table)
            )
        return counts

    def print_counts(self, counts):
        self.stdout.write("Source table counts:")
        for label, count in counts.items():
            count_text = "missing" if count is None else str(count)
            self.stdout.write(f"  {label}: {count_text}")

    def import_selected(self, cursor, config, selected, limit):
        # A pending line is stock_adjusted only because the product import takes it off the stock, so
        # the lines never come in without the stock they are taken from (an older import would oversell).
        missing_stock_tables = {"shop_item", "shop_item_option"} - selected
        if "shop_cart" in selected and missing_stock_tables:
            raise CommandError(
                "--only shop_cart also needs "
                + ", ".join(sorted(missing_stock_tables))
                + " in the same run: order lines YoungCart holds stock for are marked stock_adjusted, which "
                "is only right when the product stock they come from is imported with them."
            )
        imported = {}
        if "member" in selected:
            self.super_admin_id = self.source_super_admin(cursor, config)
        pending_stock = (
            self.source_pending_stock(cursor, config, limit) if selected & {"shop_item", "shop_item_option"} else Counter()
        )
        importers = {
            "member": self.import_members,
            "point": self.import_points,
            "memo": self.import_memos,
            "group": self.import_groups,
            "board": self.import_boards,
            "board_posts": lambda rows: self.import_board_posts(cursor, config, limit),
            "board_files": self.import_board_files,
            "content": self.import_content,
            "faq_master": self.import_faq_master,
            "faq": self.import_faq,
            "poll": self.import_poll,
            "poll_etc": self.import_poll_comments,
            "shop_category": self.import_shop_categories,
            "shop_banner": self.import_shop_banners,
            "shop_item": lambda rows: self.import_shop_products(rows, pending_stock),
            "shop_event": self.import_shop_events,
            "shop_event_item": self.import_shop_event_items,
            "shop_default": self.import_shop_default,
            "shop_sendcost": self.import_shop_sendcosts,
            "shop_item_option": lambda rows: self.import_shop_item_options(rows, pending_stock),
            "shop_item_relation": self.import_shop_item_relations,
            "shop_order": self.import_shop_orders,
            "shop_order_data": self.import_shop_order_data,
            "shop_cart": self.import_shop_cart_items,
            "shop_address": self.import_shop_addresses,
            "shop_coupon_zone": self.import_shop_coupon_zones,
            "shop_coupon": self.import_shop_coupons,
            "shop_coupon_log": self.import_shop_coupon_logs,
            "shop_personalpay": self.import_shop_personal_pays,
            "shop_review": self.import_shop_reviews,
            "shop_qna": self.import_shop_qna,
            "shop_item_stocksms": self.import_shop_stock_notifications,
            "member_social": self.import_member_social,
            "qa_content": self.import_qa_content,
            "shop_wish": self.import_shop_wishes,
            "scrap": self.import_scraps,
            "board_good": self.import_board_goods,
            "new_win": self.import_new_wins,
            "menu": self.import_menus,
            "auth": self.report_admin_auth,
        }
        for key, label in TABLE_KEYS.items():
            if label not in selected:
                continue
            if label == "board_posts":
                imported[label] = importers[label]([])
                continue
            table = config["tables"][key]
            if not table_exists(cursor, table):
                imported[label] = 0
                continue
            rows = fetch_rows(cursor, table, limit=limit)
            imported[label] = importers[label](rows)
            if imported[label]:
                # before a later importer creates rows of a model this one wrote under source ids
                self.advance_id_sequences()
        if "member_avatars" in selected:
            table = config["tables"]["member_table"]
            if table_exists(cursor, table):
                rows = fetch_rows(cursor, table, limit=limit)
                imported["member_avatars"] = self.import_member_avatars(rows)
            else:
                imported["member_avatars"] = 0
        if "public_config" in selected:
            imported["public_config"] = self.import_public_config(cursor, config)
        if "shop_product_metrics" in selected and "shop_item" not in selected:
            table = config["tables"]["g5_shop_item_table"]
            if table_exists(cursor, table):
                rows = fetch_rows(cursor, table, limit=limit)
                imported["shop_product_metrics"] = self.import_shop_product_metrics(rows)
            else:
                imported["shop_product_metrics"] = 0
        if "shop_product_tax_flags" in selected and "shop_item" not in selected:
            table = config["tables"]["g5_shop_item_table"]
            if table_exists(cursor, table):
                rows = fetch_rows(cursor, table, limit=limit)
                imported["shop_product_tax_flags"] = self.import_shop_product_tax_flags(rows)
            else:
                imported["shop_product_tax_flags"] = 0
        if "shop_product_categories" in selected and "shop_item" not in selected:
            table = config["tables"]["g5_shop_item_table"]
            if table_exists(cursor, table):
                rows = fetch_rows(cursor, table, limit=limit)
                imported["shop_product_categories"] = self.import_shop_product_categories(rows)
            else:
                imported["shop_product_categories"] = 0
        if any(imported.values()):
            self.advance_id_sequences()
        return imported

    def holds_an_earlier_import(self):
        """Rows only an import writes: the source post, question and restock request numbers, and
        members still on the Gnuboard password hash (Django rehashes one at the member's next login)."""
        return (
            Post.objects.filter(legacy_wr_id__isnull=False).exists()
            or ShopQA.objects.filter(Q(legacy_iq_id__isnull=False) | Q(legacy_qa_id__isnull=False)).exists()
            or ShopStockNotification.objects.filter(legacy_ss_id__isnull=False).exists()
            or get_user_model().objects.filter(password__startswith=GNUBOARD_HASH_PREFIX).exists()
        )

    def advance_id_sequences(self):
        """Rows imported under their source id leave PostgreSQL id sequences behind, so the next row
        Django creates (a menu added in the admin) would take an id already in use. Each sequence
        moves up to the largest id and never back: on a live database it may be ahead of every row,
        and an id handed out before must not be reused. A no-op elsewhere; SQLite and MySQL pick the
        id after the largest."""
        if connection.vendor != "postgresql":
            return
        quote = connection.ops.quote_name
        with connection.cursor() as db_cursor:
            for label in ("users", "bbs", "core", "shop"):
                for model in apps.get_app_config(label).get_models():
                    pk = model._meta.pk
                    if model._meta.proxy or not model._meta.managed or not isinstance(pk, AutoFieldMixin):
                        continue
                    db_cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [model._meta.db_table, pk.column])
                    sequence = db_cursor.fetchone()[0]
                    if not sequence:
                        continue
                    db_cursor.execute(
                        f"SELECT (SELECT MAX({quote(pk.column)}) FROM {quote(model._meta.db_table)}), last_value, "
                        f"is_called FROM {sequence}"
                    )
                    largest, last_value, is_called = db_cursor.fetchone()
                    next_id = last_value + 1 if is_called else last_value
                    if largest is not None and largest >= next_id:
                        db_cursor.execute("SELECT setval(%s, %s)", [sequence, largest])

    def source_super_admin(self, cursor, config):
        config_table, _ = self.public_config_tables(config)
        if not table_exists(cursor, config_table):
            return ""
        rows = fetch_rows(cursor, config_table, limit=1)
        return text(rows[0], "cf_admin").strip() if rows else ""

    def source_pending_stock(self, cursor, config, limit=None):
        """Per stock_key, the quantity of the pending youngcart lines the cart import brings in.

        The product and option import subtract it from the source stock, and the cart import marks
        those lines stock_adjusted, so a Django cancel puts it back. Both read only the source, so
        a re-run lands on the same stock instead of subtracting again."""
        cart_table = config["tables"].get("g5_shop_cart_table", "")
        order_table = config["tables"].get("g5_shop_order_table", "")
        if not (cart_table and order_table and table_exists(cursor, cart_table) and table_exists(cursor, order_table)):
            return Counter()
        # the cart import skips a row whose order is gone, so no imported line would hold its stock
        orders = {text(row, "od_id") for row in fetch_rows(cursor, order_table, limit=limit)}
        pending = Counter()
        for row in fetch_rows(cursor, cart_table, limit=limit):
            if text(row, "od_id") in orders and cart_stock_pending(row):
                key = stock_key(text(row, "it_id"), text(row, "io_id"), integer(row, "io_type", 0))
                pending[key] += integer(row, "ct_qty", 0)
        return pending

    @staticmethod
    def public_config_tables(config):
        return (
            config["tables"].get("config_table") or f"{config.get('table_prefix', 'g5_')}config",
            config["tables"].get("g5_shop_default_table") or f"{config.get('shop_prefix', 'g5_shop_')}default",
        )

    def import_public_config(self, cursor, config):
        config_table, shop_default_table = self.public_config_tables(config)
        config_row = fetch_rows(cursor, config_table, limit=1)[0] if table_exists(cursor, config_table) else {}
        shop_row = (
            fetch_rows(cursor, shop_default_table, limit=1)[0]
            if table_exists(cursor, shop_default_table)
            else {}
        )

        # Import only values needed for public branding and shop support. Payment
        # credentials, OAuth secrets, SMS keys (cf_icode_id / cf_icode_pw / cf_icode_token_key),
        # and other private settings are excluded.
        mappings = (
            (config_row, "cf_title", "cf_title", 255),
            # SMS 사용 / 전송유형; de_sms_hp, de_sms_use1..5 and de_sms_cont1..5 come with the shop options
            (config_row, "cf_sms_use", "cf_sms_use", 16),
            (config_row, "cf_sms_type", "cf_sms_type", 8),
            (shop_row, "de_admin_company_name", "cf_company_name", 255),
            (shop_row, "de_admin_company_owner", "cf_company_owner", 255),
            (shop_row, "de_admin_company_addr", "cf_company_addr", 255),
            (shop_row, "de_admin_company_saupja_no", "cf_company_biz_no", 64),
            (shop_row, "de_admin_company_tel", "cf_company_tel", 64),
            (shop_row, "de_admin_tongsin_no", "cf_company_tongsin_no", 128),
            (shop_row, "de_admin_buga_no", "cf_company_buga_no", 128),
            (shop_row, "de_admin_company_fax", "cf_company_fax", 64),
            (shop_row, "de_admin_company_zip", "cf_company_zip", 16),
            (shop_row, "de_admin_info_name", "cf_company_info_name", 255),
            (shop_row, "de_admin_info_email", "cf_company_email", 255),
            (shop_row, "de_admin_company_tel", "de_admin_company_tel", 64),
            (shop_row, "de_bank_use", "de_bank_use", 8),
            (shop_row, "de_bank_account", "de_bank_account", None),
        )
        imported = 0
        for row, source_name, target_name, max_length in mappings:
            if not row:
                continue
            value = text(row, source_name, max_length=max_length)
            if not value.strip():
                continue
            Config.objects.update_or_create(name=target_name, defaults={"value": value})
            imported += 1
        imported += self.import_shop_options(shop_row)
        if imported:
            signals.config_done.send(sender=Config)
        return imported

    def import_shop_options(self, shop_row):
        """Copy youngcart's non-secret shop options (same column names) from g5_shop_default."""
        from gnu_jango.shop.shop_options import SHOP_CONFIG_OPTIONS

        imported = 0
        for name, option in SHOP_CONFIG_OPTIONS.items():
            if not name.startswith("de_") or name not in shop_row:
                continue
            value = text(shop_row, name, max_length=option.max_length if option.kind != "int" else None).strip()
            if option.kind == "int" and not value.lstrip("-").isdigit():
                continue
            Config.objects.update_or_create(name=name, defaults={"value": value})
            imported += 1
        return imported

    def count_board_posts(self, cursor, config):
        total = 0
        for board_row in self.source_board_rows(cursor, config):
            table = self.write_table_for_board(cursor, config, board_row["bo_table"])
            if not table:
                continue
            total += count_table(cursor, table)
        return total

    def source_board_rows(self, cursor, config):
        table = config["tables"]["board_table"]
        if not table_exists(cursor, table):
            return []
        return fetch_rows(cursor, table)

    def write_table_for_board(self, cursor, config, bo_table):
        prefix = config["tables"].get("write_prefix") or f"{config['table_prefix']}write_"
        candidates = [
            f"{prefix}{bo_table}",
            f"{prefix}{str(bo_table).lower()}",
            f"{prefix}{str(bo_table).upper()}",
        ]
        for table in candidates:
            if table_exists(cursor, table):
                return table
        return ""

    def legacy_user(self, username):
        if not username:
            return None
        User = get_user_model()
        return User.objects.filter(username=username).first()

    def legacy_password(self, row):
        converted = convert_gnuboard_password_hash(scalar(row, "mb_password"))
        return converted or make_password(None)

    def unique_nickname(self, user, nickname):
        nickname = (str(nickname or "").strip() or user.get_username())[:100]
        base = nickname[:92] or user.get_username()[:92] or "member"
        candidate = nickname
        suffix = 1
        while Profile.objects.filter(nickname=candidate).exclude(user=user).exists():
            suffix += 1
            candidate = "%s-%s" % (base, suffix)
            candidate = candidate[:100]
        return candidate

    def unique_email(self, username, email):
        User = get_user_model()
        username = str(username or "member").strip() or "member"
        email = self.safe_email(email) or "%s@legacy.local" % username
        if not User.objects.filter(email__iexact=email).exclude(username=username).exists():
            return email

        local, domain = email.rsplit("@", 1)
        safe_username = re.sub(r"[^A-Za-z0-9_.-]+", "-", username)
        for suffix in itertools.count(1):
            tag = safe_username[:60] if suffix == 1 else "%s-%s" % (safe_username[:50], suffix)
            # a cut domain is someone else's, so only the local part gives way
            room = EMAIL_MAX_LENGTH - len("+%s@%s" % (tag, domain))
            if room < 1:
                return self.unique_email(username, None)
            candidate = "%s+%s@%s" % (local[:room], tag, domain)
            if not User.objects.filter(email__iexact=candidate).exclude(username=username).exists():
                return candidate

    def import_members(self, rows):
        count = 0
        User = get_user_model()
        for row in rows:
            username = str(scalar(row, "mb_id")).strip()
            if not username:
                continue
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "password": self.legacy_password(row),
                    "first_name": scalar(row, "mb_name")[:150],
                    "email": self.unique_email(username, scalar(row, "mb_email")),
                    # mb_level 10 alone opens no Gnuboard admin page: only cf_admin is super admin, and
                    # a sub-admin's g5_auth menu grants have no Django equivalent (report_admin_auth)
                    "is_staff": bool(self.super_admin_id) and username == self.super_admin_id,
                    "is_superuser": bool(self.super_admin_id) and username == self.super_admin_id,
                    "is_active": not bool(scalar(row, "mb_leave_date") or scalar(row, "mb_intercept_date")),
                    "date_joined": datetime_value(scalar(row, "mb_datetime")),
                    "last_login": optional_datetime_value(scalar(row, "mb_today_login")),
                },
            )
            profile = user.profile
            profile.nickname = self.unique_nickname(user, scalar(row, "mb_nick") or username)
            profile.nickname_date = optional_datetime_value(scalar(row, "mb_nick_date"))
            profile.realname = scalar(row, "mb_name")[:256]
            profile.user_homepage = scalar(row, "mb_homepage")[:255]
            profile.user_hp = scalar(row, "mb_hp")[:100]
            profile.user_level = integer(row, "mb_level", 1)
            profile.user_zip = (scalar(row, "mb_zip1") + scalar(row, "mb_zip2"))[:10]
            profile.user_addr1 = scalar(row, "mb_addr1")[:255]
            profile.user_addr2 = scalar(row, "mb_addr2")[:255]
            profile.user_addr_jibeon = scalar(row, "mb_addr_jibeon")[:255]
            profile.user_point = integer(row, "mb_point", 0)
            # mb_leave_date is "Ymd"; mb_email_certify empty or zero means not certified; mb_open_date is a date.
            profile.leave_date = ymd_date_value(scalar(row, "mb_leave_date"))
            profile.email_certify = optional_datetime_value(scalar(row, "mb_email_certify"))
            profile.email_certify_token = text(row, "mb_email_certify2", max_length=255)
            profile.open_profile = integer(row, "mb_open", 0) > 0
            # g5_member.mb_mailling keeps no date of its own; the import is when it was carried over.
            profile.mailing = integer(row, "mb_mailling", 0) > 0
            profile.mailing_date = timezone.now() if profile.mailing else None
            open_date = date_value(scalar(row, "mb_open_date"))
            profile.open_profile_date = (
                timezone.make_aware(datetime.combine(open_date, time.min)) if open_date else None
            )
            self.copy_legacy_member_avatar(profile, username)
            profile.save()
            count += 1
        super_admin = User.objects.filter(username=self.super_admin_id, is_superuser=True).first()
        if rows and not super_admin:
            self.warn(
                f"member: the source super admin (cf_admin {self.super_admin_id!r}) was not imported, so no "
                "member has Django admin access. Run createsuperuser."
            )
        elif rows and not super_admin.is_active:
            self.warn(
                f"member: the source super admin (cf_admin {self.super_admin_id!r}) is left or blocked in the "
                "source, so it came in inactive and cannot log in to the Django admin. Run createsuperuser."
            )
        return count

    def import_member_avatars(self, rows):
        imported = 0
        User = get_user_model()
        for row in rows:
            username = str(scalar(row, "mb_id")).strip()
            if not username:
                continue
            user = User.objects.filter(username=username).first()
            if not user:
                continue
            profile = Profile.objects.filter(user=user).first()
            if not profile or not self.copy_legacy_member_avatar(profile, username):
                continue
            profile.save(update_fields=["avatar"])
            imported += 1
        return imported

    def copy_legacy_member_avatar(self, profile, username):
        if getattr(profile.avatar, "name", ""):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(username or "")):
            return False

        member_image_root = (self.source_root / "data" / "member_image").resolve()
        if not member_image_root.is_dir():
            return False

        candidate_dirs = (
            member_image_root / username[:2].lower(),
            member_image_root / username[:2],
        )
        candidates = []
        for directory in dict.fromkeys(candidate_dirs):
            if not directory.is_dir():
                continue
            candidates.extend(
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.stem.casefold() == username.casefold()
                and path.suffix.lower() in LEGACY_MEMBER_IMAGE_EXTENSIONS
            )

        extension_order = {
            suffix: index
            for index, suffix in enumerate((".gif", ".jpg", ".jpeg", ".png"))
        }
        candidates.sort(key=lambda path: (extension_order[path.suffix.lower()], path.name.casefold()))
        for candidate in candidates:
            try:
                source_path = candidate.resolve(strict=True)
                source_path.relative_to(member_image_root)
                if not source_path.is_file():
                    continue
                with source_path.open("rb") as source_file:
                    dimensions = get_image_dimensions(source_file)
                    if not dimensions or min(dimensions) <= 0:
                        continue
                    source_file.seek(0)
                    profile.avatar.save(source_path.name, File(source_file), save=False)
                return True
            except (OSError, ValueError):
                continue
        return False

    def import_points(self, rows):
        count = 0
        for row in rows:
            point_id = integer(row, "po_id", 0)
            user = self.legacy_user(scalar(row, "mb_id"))
            if not point_id:
                continue
            User_Point.objects.update_or_create(
                pk=point_id,
                defaults={
                    "user": user,
                    "po_datetime": datetime_value(scalar(row, "po_datetime")),
                    "po_content": scalar(row, "po_content")[:255],
                    "po_point": integer(row, "po_point", 0),
                    "po_use_point": integer(row, "po_use_point", 0),
                    "po_expired": integer(row, "po_expired", 0),
                    "po_expire_date": optional_datetime_value(scalar(row, "po_expire_date")),
                    "po_mb_point": integer(row, "po_mb_point", 0),
                    "po_rel_table": scalar(row, "po_rel_table")[:20],
                    "po_rel_id": integer(row, "po_rel_id", 0),
                    "po_rel_action": scalar(row, "po_rel_action")[:255],
                },
            )
            count += 1
        return count

    @suppress_notification_events()
    def import_memos(self, rows):
        count = 0
        for row in rows:
            memo_id = integer(row, "me_id", 0)
            memo_type = scalar(row, "me_type") or "recv"
            recv_user = self.legacy_user(scalar(row, "me_recv_mb_id"))
            send_user = self.legacy_user(scalar(row, "me_send_mb_id"))
            owner = send_user if memo_type == "send" else recv_user
            if not memo_id or not owner:
                continue
            User_Memo.objects.update_or_create(
                pk=memo_id,
                defaults={
                    "user": owner,
                    "me_recv_user_id": recv_user.pk if recv_user else 0,
                    "me_send_datetime": datetime_value(scalar(row, "me_send_datetime")),
                    "me_read_datetime": optional_datetime_value(scalar(row, "me_read_datetime")),
                    "me_memo": scalar(row, "me_memo"),
                    # Django's received memo names its sender's user id here; gnuboard leaves it 0
                    # and only fills it on the sent copy (the id of the received one)
                    "me_send_id": (
                        integer(row, "me_send_id", 0) if memo_type == "send" else (send_user.pk if send_user else 0)
                    ),
                    "me_type": memo_type,
                    "me_send_ip": scalar(row, "me_send_ip")[:100],
                },
            )
            count += 1
        return count

    def import_groups(self, rows):
        count = 0
        for row in rows:
            gr_id = str(scalar(row, "gr_id")).strip()
            if not gr_id:
                continue
            Group.objects.update_or_create(
                gr_id=gr_id,
                defaults={
                    "gr_subject": scalar(row, "gr_subject") or gr_id,
                    "gr_device": scalar(row, "gr_device", "both") or "both",
                    "gr_admin": scalar(row, "gr_admin"),
                    "gr_use_access": integer(row, "gr_use_access", 0),
                    "gr_order": integer(row, "gr_order", 0),
                },
            )
            count += 1
        return count

    def import_boards(self, rows):
        count = 0
        for row in rows:
            bo_table = str(scalar(row, "bo_table")).strip()
            group = Group.objects.filter(gr_id=scalar(row, "gr_id")).first()
            if not bo_table or not group:
                continue
            Board.objects.update_or_create(
                bo_table=bo_table,
                defaults={
                    "group": group,
                    "bo_subject": scalar(row, "bo_subject") or bo_table,
                    "bo_mobile_subject": scalar(row, "bo_mobile_subject"),
                    "bo_device": scalar(row, "bo_device", "both") or "both",
                    "bo_category_list": scalar(row, "bo_category_list"),
                    "bo_admin": scalar(row, "bo_admin"),
                    "bo_list_level": integer(row, "bo_list_level", 1),
                    "bo_read_level": integer(row, "bo_read_level", 1),
                    "bo_write_level": integer(row, "bo_write_level", 1),
                    "bo_reply_level": integer(row, "bo_reply_level", 1),
                    "bo_comment_level": integer(row, "bo_comment_level", 1),
                    "bo_upload_level": integer(row, "bo_upload_level", 1),
                    "bo_download_level": integer(row, "bo_download_level", 1),
                    "bo_html_level": integer(row, "bo_html_level", 1),
                    "bo_link_level": integer(row, "bo_link_level", 1),
                    "bo_count_delete": integer(row, "bo_count_delete", 0),
                    "bo_count_modify": integer(row, "bo_count_modify", 0),
                    "bo_read_point": integer(row, "bo_read_point", 0),
                    "bo_write_point": integer(row, "bo_write_point", 0),
                    "bo_comment_point": integer(row, "bo_comment_point", 0),
                    "bo_download_point": integer(row, "bo_download_point", 0),
                    "bo_use_category": bool_char(row, "bo_use_category", False),
                    "bo_use_sideview": bool_char(row, "bo_use_sideview", False),
                    "bo_use_file_content": bool_char(row, "bo_use_file_content", False),
                    "bo_use_secret": bool_char(row, "bo_use_secret", False),
                    "bo_use_dhtml_editor": bool_char(row, "bo_use_dhtml_editor", False),
                    "bo_select_editor": bool_char(row, "bo_select_editor", False),
                    "bo_use_rss_view": bool_char(row, "bo_use_rss_view", False),
                    "bo_use_good": bool_char(row, "bo_use_good", False),
                    "bo_use_nogood": bool_char(row, "bo_use_nogood", False),
                    "bo_use_name": bool_char(row, "bo_use_name", False),
                    "bo_use_signature": bool_char(row, "bo_use_signature", False),
                    "bo_use_ip_view": bool_char(row, "bo_use_ip_view", False),
                    "bo_use_list_view": bool_char(row, "bo_use_list_view", False),
                    "bo_use_list_file": bool_char(row, "bo_use_list_file", False),
                    "bo_use_list_content": bool_char(row, "bo_use_list_content", False),
                    "bo_table_width": integer(row, "bo_table_width", 0),
                    "bo_subject_len": integer(row, "bo_subject_len", 0),
                    "bo_mobile_subject_len": integer(row, "bo_mobile_subject_len", 0),
                    "bo_page_rows": integer(row, "bo_page_rows", 0),
                    "bo_mobile_page_rows": integer(row, "bo_mobile_page_rows", 0),
                    "bo_new": integer(row, "bo_new", 0),
                    "bo_hot": integer(row, "bo_hot", 0),
                    "bo_image_width": integer(row, "bo_image_width", 0),
                    "bo_skin": scalar(row, "bo_skin") or "basic",
                    "bo_mobile_skin": scalar(row, "bo_mobile_skin") or "basic",
                    "bo_content_head": scalar(row, "bo_content_head"),
                    "bo_mobile_content_head": scalar(row, "bo_mobile_content_head"),
                    "bo_content_tail": scalar(row, "bo_content_tail"),
                    "bo_mobile_content_tail": scalar(row, "bo_mobile_content_tail"),
                    "bo_insert_content": scalar(row, "bo_insert_content"),
                    "bo_gallery_cols": integer(row, "bo_gallery_cols", 0),
                    "bo_gallery_width": integer(row, "bo_gallery_width", 0),
                    "bo_gallery_height": integer(row, "bo_gallery_height", 0),
                    "bo_mobile_gallery_width": integer(row, "bo_mobile_gallery_width", 0),
                    "bo_mobile_gallery_height": integer(row, "bo_mobile_gallery_height", 0),
                    "bo_upload_size": integer(row, "bo_upload_size", 0),
                    "bo_reply_order": bool_char(row, "bo_reply_order", False),
                    "bo_use_search": bool_char(row, "bo_use_search", False),
                    "bo_order": integer(row, "bo_order", 0),
                    "bo_count_write": integer(row, "bo_count_write", 0),
                    "bo_count_comment": integer(row, "bo_count_comment", 0),
                    "bo_write_min": integer(row, "bo_write_min", 0),
                    "bo_write_max": integer(row, "bo_write_max", 0),
                    "bo_comment_min": integer(row, "bo_comment_min", 0),
                    "bo_comment_max": integer(row, "bo_comment_max", 0),
                    "bo_notice": scalar(row, "bo_notice"),
                    "bo_upload_count": integer(row, "bo_upload_count", 0),
                    "bo_use_email": bool_char(row, "bo_use_email", False),
                    "bo_use_cert": scalar(row, "bo_use_cert"),
                    "bo_use_sns": bool_char(row, "bo_use_sns", False),
                    "bo_use_captcha": bool_char(row, "bo_use_captcha", False),
                    "bo_sort_field": scalar(row, "bo_sort_field"),
                },
            )
            count += 1
        return count

    def import_board_posts(self, cursor, config, limit):
        imported = 0
        boards = Board.objects.order_by("bo_table")
        for board in boards:
            table = self.write_table_for_board(cursor, config, board.bo_table)
            if not table:
                continue
            rows = fetch_rows(cursor, table, limit=limit)
            posts_by_legacy_id = {}
            for row in rows:
                if integer(row, "wr_is_comment", 0) != 0:
                    continue
                post = self.upsert_post(board, row)
                posts_by_legacy_id[integer(row, "wr_id", 0)] = post
                imported += 1
            for row in rows:
                if integer(row, "wr_is_comment", 0) == 0:
                    continue
                post = posts_by_legacy_id.get(integer(row, "wr_parent", 0))
                if post is None:
                    post = Post.objects.filter(board=board, wr_parent=integer(row, "wr_parent", 0)).order_by("pk").first()
                if not post:
                    continue
                self.upsert_comment(board, post, row)
                imported += 1
        return imported

    def import_board_files(self, rows):
        imported = 0
        touched_posts = set()
        for row in rows:
            board = Board.objects.filter(bo_table=scalar(row, "bo_table")).first()
            if not board:
                continue
            post = Post.objects.filter(board=board, wr_parent=integer(row, "wr_id", 0)).order_by("pk").first()
            if not post:
                continue
            self.upsert_board_file(board, post, row)
            touched_posts.add(post.pk)
            imported += 1

        for post_id in touched_posts:
            Post.objects.filter(pk=post_id).update(wr_file=Post_file.objects.filter(post_id=post_id).count())
        return imported

    def upsert_board_file(self, board, post, row):
        legacy_file = self.legacy_filename(scalar(row, "bf_file"))
        source_path = self.legacy_board_file_path(board.bo_table, legacy_file) if legacy_file else None
        copied_name = self.copy_legacy_board_file(board, legacy_file, source_path)
        post_file = (
            Post_file.objects.filter(board=board, post=post, bf_no=integer(row, "bf_no", 0))
            .order_by("pk")
            .first()
        )
        if post_file is None:
            post_file = Post_file(board=board, post=post, bf_no=integer(row, "bf_no", 0))

        if copied_name:
            post_file.bf_file = copied_name
            storage_name = "local"
        else:
            storage_name = "local" if getattr(post_file.bf_file, "name", "") else "legacy_missing"

        post_file.bf_source = (scalar(row, "bf_source") or legacy_file)[:255]
        post_file.bf_download = integer(row, "bf_download", 0)
        post_file.bf_content = scalar(row, "bf_content")
        post_file.bf_fileurl = scalar(row, "bf_fileurl")[:255] or self.legacy_board_file_url(board.bo_table, legacy_file)
        post_file.bf_thumburl = scalar(row, "bf_thumburl")[:255]
        post_file.bf_storage = storage_name
        post_file.bf_filesize = integer(row, "bf_filesize", 0)
        post_file.bf_width = integer(row, "bf_width", 0)
        post_file.bf_height = integer(row, "bf_height", 0)
        post_file.bf_type = integer(row, "bf_type", 0)
        post_file.bf_datetime = datetime_value(scalar(row, "bf_datetime"))
        post_file.save()
        return post_file

    def legacy_filename(self, value):
        value = str(value or "").replace("\\", "/").strip()
        return value.rsplit("/", 1)[-1] if value else ""

    def legacy_board_file_path(self, bo_table, filename):
        if not filename:
            return None
        # bo_table and bf_file come from the imported database: never read outside data/file.
        base = (self.source_root / "data" / "file").resolve()
        path = (base / str(bo_table) / filename).resolve()
        return path if path.is_relative_to(base) and path != base else None

    def legacy_board_file_url(self, bo_table, filename):
        if not filename:
            return ""
        return f"data/file/{bo_table}/{filename}"[:255]

    def copy_legacy_board_file(self, board, filename, source_path):
        if not filename or not source_path or not source_path.exists() or not source_path.is_file():
            return ""

        target_name = self.legacy_board_file_target(board, filename)
        if default_storage.exists(target_name):
            return target_name

        with source_path.open("rb") as source_file:
            return default_storage.save(target_name, File(source_file))

    def legacy_board_file_target(self, board, filename):
        target = Path(defaults.BBS_FILE_DIR) / str(board.id) / filename
        target_name = target.as_posix()
        if len(target_name) <= 95:
            return target_name

        path = Path(filename)
        suffix = path.suffix[:20]
        stem = path.stem[:40] or "legacy-file"
        digest = hashlib.sha1(filename.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return (Path(defaults.BBS_FILE_DIR) / str(board.id) / f"{stem}-{digest}{suffix}").as_posix()

    def write_option(self, row):
        value = str(scalar(row, "wr_option")).strip()
        if not value:
            return "html1"
        supported = {"html1", "html2", "secret", "mail"}
        options = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip() in supported))
        return ",".join(options) if options else value[:100]

    def upsert_post(self, board, row):
        legacy_id = integer(row, "wr_id", 0)
        post = Post.objects.filter(
            board=board, legacy_wr_id=legacy_id
        ).order_by("pk").first()
        if post is None:
            # Compatibility with rows imported before their source wr_id was
            # stored separately. Their original importer set each row's own ID
            # as wr_parent, so this lookup recovers that row safely.
            post = Post.objects.filter(
                board=board,
                wr_parent=legacy_id,
                wr_reply="",
            ).order_by("pk").first()
        if post is None:
            post = Post(board=board)
        post.legacy_wr_id = legacy_id or None
        post.wr_num = integer(row, "wr_num", 0)
        post.wr_reply = post_reply_marker(row)
        # a post is its own wr_parent; 0 is not a post id to link to
        post.wr_parent = integer(row, "wr_parent", 0) or legacy_id
        post.ca_name = scalar(row, "ca_name")[:255]
        post.wr_comment = integer(row, "wr_comment", 0)
        post.wr_option = self.write_option(row)
        post.wr_subject = scalar(row, "wr_subject")[:255]
        post.wr_content = scalar(row, "wr_content")
        post.wr_link1 = scalar(row, "wr_link1")
        post.wr_link2 = scalar(row, "wr_link2")
        post.wr_link1_hit = integer(row, "wr_link1_hit", 0)
        post.wr_link2_hit = integer(row, "wr_link2_hit", 0)
        post.wr_hit = integer(row, "wr_hit", 0)
        post.wr_good = integer(row, "wr_good", 0)
        post.wr_nogood = integer(row, "wr_nogood", 0)
        post.user = self.legacy_user(scalar(row, "mb_id"))
        post.wr_password = scalar(row, "wr_password")[:255]
        post.wr_name = scalar(row, "wr_name")[:255]
        post.wr_email = scalar(row, "wr_email")[:255]
        post.wr_homepage = scalar(row, "wr_homepage")[:255]
        post.wr_datetime = datetime_value(scalar(row, "wr_datetime"))
        post.wr_file = integer(row, "wr_file", 0)
        post.wr_last = optional_datetime_value(scalar(row, "wr_last"))
        post.wr_ip = scalar(row, "wr_ip")[:255]
        post.is_notice = 1 if str(legacy_id) in str(board.bo_notice or "").replace("\n", ",").split(",") else 0
        post.save()
        return post

    @suppress_notification_events()
    def upsert_comment(self, board, post, row):
        legacy_id = integer(row, "wr_id", 0)
        comment = Comment.objects.filter(board=board, post=post, order_num=legacy_id).order_by("pk").first()
        if comment is None:
            comment = Comment(board=board, post=post, order_num=legacy_id)
        comment.wr_comment = integer(row, "wr_comment", 0)
        comment.user = self.legacy_user(scalar(row, "mb_id"))
        comment.parent = integer(row, "wr_parent", 0)
        comment.wr_comment_reply = scalar(row, "wr_comment_reply")[:5]
        comment.wr_option = self.write_option(row)
        comment.wr_content = scalar(row, "wr_content")
        comment.wr_good = integer(row, "wr_good", 0)
        comment.wr_nogood = integer(row, "wr_nogood", 0)
        comment.wr_password = scalar(row, "wr_password")[:255]
        comment.wr_name = scalar(row, "wr_name")[:255]
        comment.wr_email = scalar(row, "wr_email")[:255]
        comment.wr_datetime = datetime_value(scalar(row, "wr_datetime"))
        comment.wr_file = integer(row, "wr_file", 0)
        comment.wr_last = optional_datetime_value(scalar(row, "wr_last"))
        comment.wr_ip = scalar(row, "wr_ip")[:255]
        comment.save()
        return comment

    def import_content(self, rows):
        count = 0
        for row in rows:
            co_id = str(scalar(row, "co_id")).strip()
            if not co_id:
                continue
            ContentPage.objects.update_or_create(
                co_id=co_id,
                defaults={
                    "co_subject": scalar(row, "co_subject"),
                    "co_content": scalar(row, "co_content"),
                    "co_mobile_content": scalar(row, "co_mobile_content"),
                    "co_html": integer(row, "co_html", 1),
                    "co_skin": text(row, "co_skin", "basic", max_length=64) or "basic",
                    "co_mobile_skin": text(row, "co_mobile_skin", "basic", max_length=64) or "basic",
                    "co_seo_title": scalar(row, "co_seo_title"),
                    "co_include_head": scalar(row, "co_include_head"),
                    "co_include_tail": scalar(row, "co_include_tail"),
                    "co_order": integer(row, "co_order", 0),
                    "co_use": integer(row, "co_use", 1),
                },
            )
            count += 1
        return count

    def import_faq_master(self, rows):
        count = 0
        for row in rows:
            fm_id = integer(row, "fm_id", 0)
            if not fm_id:
                continue
            FAQMaster.objects.update_or_create(
                fm_id=fm_id,
                defaults={
                    "fm_subject": scalar(row, "fm_subject"),
                    "fm_head_html": scalar(row, "fm_head_html"),
                    "fm_tail_html": scalar(row, "fm_tail_html"),
                    "fm_mobile_head_html": scalar(row, "fm_mobile_head_html"),
                    "fm_mobile_tail_html": scalar(row, "fm_mobile_tail_html"),
                    "fm_order": integer(row, "fm_order", 0),
                    "fm_use": integer(row, "fm_use", 1),
                },
            )
            count += 1
        return count

    def import_faq(self, rows):
        count = 0
        for row in rows:
            fa_id = integer(row, "fa_id", 0)
            fm_id = integer(row, "fm_id", 0)
            master = FAQMaster.objects.filter(pk=fm_id).first()
            if not fa_id or not master:
                continue
            FAQItem.objects.update_or_create(
                fa_id=fa_id,
                defaults={
                    "master": master,
                    "fa_subject": scalar(row, "fa_subject"),
                    "fa_content": scalar(row, "fa_content"),
                    "fa_order": integer(row, "fa_order", 0),
                    "fa_use": integer(row, "fa_use", 1),
                },
            )
            count += 1
        return count

    def import_poll(self, rows):
        count = 0
        for row in rows:
            po_id = integer(row, "po_id", 0)
            if not po_id:
                continue
            poll, _ = Poll.objects.update_or_create(
                po_id=po_id,
                defaults={
                    "po_subject": scalar(row, "po_subject"),
                    "po_etc": scalar(row, "po_etc"),
                    "po_level": integer(row, "po_level", 1),
                    "po_point": integer(row, "po_point", 0),
                    "po_date": date_value(scalar(row, "po_date")) or timezone.localdate(),
                    "po_use": integer(row, "po_use", 1),
                },
            )
            self.import_poll_choices(poll, row)
            count += 1
        return count

    def import_poll_choices(self, poll, row):
        for num in range(1, 10):
            content = scalar(row, f"po_poll{num}")
            if not str(content).strip():
                continue
            PollChoice.objects.update_or_create(
                poll=poll,
                num=num,
                defaults={
                    "content": content,
                    "count": integer(row, f"po_cnt{num}", 0),
                },
            )

    def import_poll_comments(self, rows):
        count = 0
        User = get_user_model()
        for row in rows:
            pc_id = integer(row, "pc_id", 0)
            poll = Poll.objects.filter(pk=integer(row, "po_id", 0)).first()
            if not pc_id or not poll:
                continue
            username = scalar(row, "mb_id")
            user = User.objects.filter(username=username).first() if username else None
            PollComment.objects.update_or_create(
                pc_id=pc_id,
                defaults={
                    "poll": poll,
                    "user": user,
                    "pc_name": scalar(row, "pc_name") or username,
                    "pc_idea": scalar(row, "pc_idea"),
                    "pc_datetime": datetime_value(scalar(row, "pc_datetime")),
                },
            )
            count += 1
        return count

    def import_shop_categories(self, rows):
        count = 0
        for row in rows:
            ca_id = str(scalar(row, "ca_id")).strip()
            if not ca_id:
                continue
            ShopCategory.objects.update_or_create(
                ca_id=ca_id,
                defaults={
                    "ca_name": scalar(row, "ca_name"),
                    "ca_parent": ca_id[:-2] if len(ca_id) > 2 else "",
                    "ca_order": integer(row, "ca_order", 0),
                    "ca_skin": text(row, "ca_skin", max_length=100),
                    "ca_use": bool_char(row, "ca_use", True),
                    # categoryform.php 출력설정 and 쿠폰적용안함
                    "ca_list_mod": max(0, integer(row, "ca_list_mod", 0)),
                    "ca_list_row": max(0, integer(row, "ca_list_row", 0)),
                    "ca_mobile_list_mod": max(0, integer(row, "ca_mobile_list_mod", 0)),
                    "ca_mobile_list_row": max(0, integer(row, "ca_mobile_list_row", 0)),
                    "ca_nocoupon": bool(integer(row, "ca_nocoupon", 0)),
                },
            )
            count += 1
        return count

    def import_shop_banners(self, rows):
        count = 0
        banner_asset_dir = self.source_root / "data" / "banner"
        for row in rows:
            bn_id = integer(row, "bn_id", 0)
            if not bn_id:
                continue
            if banner_asset_dir.is_dir() and not (banner_asset_dir / str(bn_id)).is_file():
                ShopBanner.objects.filter(pk=bn_id).update(is_active=False)
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped active banner {bn_id}: image file was not found in {banner_asset_dir}."
                    )
                )
                continue
            ShopBanner.objects.update_or_create(
                bn_id=bn_id,
                defaults={
                    "bn_alt": text(row, "bn_alt", max_length=255),
                    "bn_url": text(row, "bn_url", "/shop", max_length=1000) or "/shop",
                    "bn_position": text(row, "bn_position", "메인", max_length=100) or "메인",
                    "bn_device": text(row, "bn_device", "both", max_length=10) or "both",
                    "bn_border": bool_char(row, "bn_border", False),
                    "bn_new_win": bool_char(row, "bn_new_win", False),
                    "bn_order": integer(row, "bn_order", 0),
                    "image_url": f"/data/banner/{bn_id}",
                    "is_active": True,
                    "begin_at": optional_datetime_value(scalar(row, "bn_begin_time")),
                    "end_at": optional_datetime_value(scalar(row, "bn_end_time")),
                    "hit_count": integer(row, "bn_hit", 0),
                },
            )
            count += 1
        return count

    def import_shop_products(self, rows, pending_stock=None):
        pending_stock = pending_stock or Counter()
        count = 0
        missing_images = []
        for row in rows:
            it_id = str(scalar(row, "it_id")).strip()
            if not it_id:
                continue
            category = self.product_category(row)
            missing = []
            images = self.product_image_paths(row, missing)
            if missing:
                missing_images.append(it_id)
            # it_time is when the product was registered: the new-arrival order (ShopProduct -created_at)
            registered = optional_datetime_value(scalar(row, "it_time"))
            ShopProduct.objects.update_or_create(
                it_id=it_id,
                defaults={
                    "category": category,
                    "category2": self.known_category(scalar(row, "ca_id2")),
                    "category3": self.known_category(scalar(row, "ca_id3")),
                    "it_name": scalar(row, "it_name"),
                    "it_seo_title": scalar(row, "it_seo_title"),
                    "it_brand": scalar(row, "it_brand"),
                    "it_maker": scalar(row, "it_maker"),
                    "it_origin": scalar(row, "it_origin"),
                    "it_model": scalar(row, "it_model"),
                    "it_price": integer(row, "it_price", 0),
                    "it_basic_price": integer(row, "it_price", 0),
                    "it_cust_price": integer(row, "it_cust_price", 0),
                    "it_hit": integer(row, "it_hit", 0),
                    **self.shop_product_metrics(row),
                    "it_point": integer(row, "it_point", 0),
                    "it_point_type": integer(row, "it_point_type", 0),
                    "it_stock_qty": integer(row, "it_stock_qty", 9999) - pending_stock[stock_key(it_id)],
                    "it_buy_min_qty": integer(row, "it_buy_min_qty", 1),
                    "it_buy_max_qty": integer(row, "it_buy_max_qty", 0),
                    "it_tel_inq": flag(row, "it_tel_inq"),
                    "it_soldout": flag(row, "it_soldout"),
                    "it_use": flag(row, "it_use", "1"),
                    "it_stock_sms": flag(row, "it_stock_sms"),
                    "it_sc_type": integer(row, "it_sc_type", 0),
                    "it_sc_method": integer(row, "it_sc_method", 0),
                    "it_sc_price": integer(row, "it_sc_price", 3000),
                    "it_sc_minimum": integer(row, "it_sc_minimum", 50000),
                    "it_sc_qty": integer(row, "it_sc_qty", 0),
                    "it_notax": integer(row, "it_notax", 0),
                    "it_nocoupon": bool(integer(row, "it_nocoupon", 0)),
                    "it_type1": flag(row, "it_type1"),
                    "it_type2": flag(row, "it_type2"),
                    "it_type3": flag(row, "it_type3"),
                    "it_type4": flag(row, "it_type4"),
                    "it_type5": flag(row, "it_type5"),
                    "it_basic": scalar(row, "it_basic"),
                    "it_content": scalar(row, "it_content"),
                    "it_explan": scalar(row, "it_explan"),
                    "it_head_html": scalar(row, "it_head_html"),
                    "it_tail_html": scalar(row, "it_tail_html"),
                    "it_info_gubun": scalar(row, "it_info_gubun"),
                    **self.product_info_fields(row),
                    "it_option_subject": scalar(row, "it_option_subject"),
                    "it_supply_subject": scalar(row, "it_supply_subject"),
                    "image_url": images[0] if images else "",
                    "images": [{"url": image, "alt": scalar(row, "it_name")} for image in images],
                    **({"created_at": registered} if registered else {}),
                },
            )
            count += 1
        if missing_images:
            self.warn(
                f"shop_item: {len(missing_images)} product(s) list image files missing from the source: "
                + ", ".join(missing_images)
            )
        return count

    def product_info_fields(self, row):
        """YoungCart keeps 상품정보제공고시 as a PHP-serialized array: store its rows, not the text."""
        raw = text(row, "it_info_value")
        rows = parse_item_info_value(raw, text(row, "it_info_gubun"))
        if rows is None:
            return {"it_info_title": raw[:255], "it_info_value": []}
        return {"it_info_title": "", "it_info_value": rows}

    def shop_product_metrics(self, row):
        return {
            "it_update_time": optional_datetime_value(scalar(row, "it_update_time")),
            "it_order": integer(row, "it_order", 0),
            "it_sum_qty": max(0, integer(row, "it_sum_qty", 0)),
            "it_use_cnt": max(0, integer(row, "it_use_cnt", 0)),
            "it_use_avg": scalar(row, "it_use_avg", 0),
        }

    def import_shop_product_metrics(self, rows):
        count = 0
        for row in rows:
            it_id = text(row, "it_id", max_length=40)
            if not it_id:
                continue
            count += ShopProduct.objects.filter(pk=it_id).update(**self.shop_product_metrics(row))
        return count

    def import_shop_product_categories(self, rows):
        """Backfill ca_id2/ca_id3 only, leaving every other product column untouched."""
        count = 0
        for row in rows:
            it_id = text(row, "it_id", max_length=40)
            if not it_id:
                continue
            count += ShopProduct.objects.filter(pk=it_id).update(
                category2=self.known_category(scalar(row, "ca_id2")),
                category3=self.known_category(scalar(row, "ca_id3")),
            )
        return count

    def import_shop_product_tax_flags(self, rows):
        count = 0
        for row in rows:
            it_id = text(row, "it_id", max_length=40)
            if not it_id:
                continue
            count += ShopProduct.objects.filter(pk=it_id).update(
                it_notax=integer(row, "it_notax", 0)
            )
        return count

    def import_shop_stock_notifications(self, rows):
        count = 0
        for row in rows:
            legacy_ss_id = integer(row, "ss_id", 0)
            it_id = text(row, "it_id", max_length=40)
            if legacy_ss_id <= 0 or not it_id:
                continue
            product = ShopProduct.objects.filter(pk=it_id).first()
            ShopStockNotification.objects.update_or_create(
                legacy_ss_id=legacy_ss_id,
                defaults={
                    "product": product,
                    "it_id": it_id,
                    "ss_hp": text(row, "ss_hp", max_length=255),
                    "ss_send": bool(integer(row, "ss_send", 0)),
                    "ss_send_time": optional_datetime_value(scalar(row, "ss_send_time")),
                    "ss_datetime": optional_datetime_value(scalar(row, "ss_datetime")),
                    "ss_ip": text(row, "ss_ip", max_length=45),
                    "source": "legacy-db",
                },
            )
            count += 1
        return count

    def import_shop_events(self, rows):
        count = 0
        for row in rows:
            ev_id = integer(row, "ev_id", 0)
            if ev_id <= 0:
                continue
            ShopEvent.objects.update_or_create(
                ev_id=ev_id,
                defaults={
                    "ev_skin": text(row, "ev_skin", max_length=255),
                    "ev_mobile_skin": text(row, "ev_mobile_skin", max_length=255),
                    "ev_img_width": integer(row, "ev_img_width", 0),
                    "ev_img_height": integer(row, "ev_img_height", 0),
                    "ev_list_mod": integer(row, "ev_list_mod", 0),
                    "ev_list_row": integer(row, "ev_list_row", 0),
                    "ev_mobile_img_width": integer(row, "ev_mobile_img_width", 0),
                    "ev_mobile_img_height": integer(row, "ev_mobile_img_height", 0),
                    "ev_mobile_list_mod": integer(row, "ev_mobile_list_mod", 0),
                    "ev_mobile_list_row": integer(row, "ev_mobile_list_row", 0),
                    "ev_subject": text(row, "ev_subject", max_length=255),
                    "ev_subject_strong": bool_char(row, "ev_subject_strong", False),
                    "ev_head_html": text(row, "ev_head_html"),
                    "ev_tail_html": text(row, "ev_tail_html"),
                    "ev_use": bool_char(row, "ev_use", False),
                },
            )
            count += 1
        return count

    def import_shop_event_items(self, rows):
        count = 0
        for row in rows:
            ev_id = integer(row, "ev_id", 0)
            it_id = text(row, "it_id", max_length=40)
            if ev_id <= 0 or not it_id:
                continue
            event = ShopEvent.objects.filter(pk=ev_id).first()
            if not event:
                continue
            product = ShopProduct.objects.filter(pk=it_id).first()
            ShopEventItem.objects.update_or_create(
                event=event,
                it_id=it_id,
                defaults={"product": product},
            )
            count += 1
        return count

    def import_shop_default(self, rows):
        if not rows:
            return 0
        row = rows[0]
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            defaults={
                "de_delivery_company": text(row, "de_delivery_company", max_length=255),
                "de_admin_company_name": text(row, "de_admin_company_name", max_length=255),
                "de_admin_company_tel": text(row, "de_admin_company_tel", max_length=30),
                "de_send_cost_case": text(row, "de_send_cost_case", max_length=255),
                "de_send_cost_limit": text(row, "de_send_cost_limit", max_length=255),
                "de_send_cost_list": text(row, "de_send_cost_list", max_length=255),
                "de_baesong_content": text(row, "de_baesong_content"),
                "de_change_content": text(row, "de_change_content"),
                "de_item_use_write": integer(row, "de_item_use_write", 0),
                "de_item_use_use": integer(row, "de_item_use_use", 0),
                "de_tax_flag_use": integer(row, "de_tax_flag_use", 0),
                "de_settle_min_point": integer(row, "de_settle_min_point", 0),
                "de_settle_max_point": integer(row, "de_settle_max_point", 0),
                # a point unit of 0 cannot round anything (the admin form starts at 1)
                "de_settle_point_unit": integer(row, "de_settle_point_unit", 0) or 1,
            },
        )
        return 1
        return 1

    def import_shop_sendcosts(self, rows):
        count = 0
        for row in rows:
            sc_id = integer(row, "sc_id", 0)
            if sc_id <= 0:
                continue
            ShopShippingCost.objects.update_or_create(
                sc_id=sc_id,
                defaults={
                    "sc_name": text(row, "sc_name", max_length=255),
                    "sc_zip1": text(row, "sc_zip1", max_length=10),
                    "sc_zip2": text(row, "sc_zip2", max_length=10),
                    "sc_price": max(0, integer(row, "sc_price", 0)),
                },
            )
            count += 1
        return count

    def known_category(self, ca_id):
        ca_id = str(ca_id or "").strip()
        return ShopCategory.objects.filter(pk=ca_id).first() if ca_id else None

    def product_category(self, row):
        for key in ("ca_id", "ca_id2", "ca_id3"):
            category = self.known_category(scalar(row, key))
            if category:
                return category
        return None

    def product_image_paths(self, row, missing=None):
        """The product's image URLs; the it_imgN values whose file is not under data/item go to missing."""
        image_root = self.source_root / "data" / "item"
        image_root_exists = image_root.is_dir()
        images = []

        for index in range(1, 11):
            image = str(scalar(row, f"it_img{index}") or "").strip()
            if not image:
                continue
            if image.startswith(("http://", "https://")):
                images.append(image)
                continue

            relative = Path(image.replace("\\", "/").lstrip("/"))
            if relative.parts[:2] == ("data", "item"):
                relative = Path(*relative.parts[2:])
            if image_root_exists:
                image_path = image_root / relative
                try:
                    image_path.resolve().relative_to(image_root.resolve())
                except ValueError:
                    continue
                if not image_path.is_file():
                    if missing is not None:
                        missing.append(relative.as_posix())
                    continue
            images.append(f"/data/item/{relative.as_posix()}")

        if images or not image_root_exists:
            return images

        # Recent Gnuboard product uploads can be stored as image-01.png files
        # even when legacy it_imgN fields still point to removed filenames.
        it_id = str(scalar(row, "it_id") or "").strip()
        product_dir = image_root / it_id
        try:
            product_dir.resolve().relative_to(image_root.resolve())
        except ValueError:
            return []

        for index in range(1, 11):
            for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                image_path = product_dir / f"image-{index:02d}{suffix}"
                if image_path.is_file():
                    images.append(f"/data/item/{it_id}/{image_path.name}")
                    break
        if not images and (product_dir / "w700.png").is_file():
            images.append(f"/data/item/{it_id}/w700.png")
        return images

    def import_shop_item_options(self, rows, pending_stock=None):
        pending_stock = pending_stock or Counter()
        grouped = {}
        for row in rows:
            it_id = str(scalar(row, "it_id")).strip()
            if not it_id:
                continue
            io_id = text(row, "io_id")
            io_type = integer(row, "io_type", 0)
            grouped.setdefault(it_id, []).append(
                {
                    "io_no": integer(row, "io_no", 0),
                    "io_id": io_id,
                    "io_type": io_type,
                    "io_price": integer(row, "io_price", 0),
                    "io_stock_qty": integer(row, "io_stock_qty", 0) - pending_stock[stock_key(it_id, io_id, io_type)],
                    "io_noti_qty": integer(row, "io_noti_qty", 0),
                    "io_use": integer(row, "io_use", 1),
                }
            )

        count = 0
        for it_id, options in grouped.items():
            product = ShopProduct.objects.filter(pk=it_id).first()
            if not product:
                continue
            product.options = sorted(options, key=lambda item: (item["io_type"], item["io_no"], item["io_id"]))
            product.save(update_fields=["options", "updated_at"])
            count += len(options)
        return count

    def import_shop_item_relations(self, rows):
        """g5_shop_item_relation (it_id, it_id2, ir_no): both directions are already rows there."""
        known = set(ShopProduct.objects.values_list("it_id", flat=True))
        count = 0
        for row in rows:
            it_id = text(row, "it_id", max_length=40).strip()
            related_id = text(row, "it_id2", max_length=40).strip()
            if not it_id or not related_id or it_id == related_id:
                continue
            if it_id not in known or related_id not in known:
                continue
            ShopProductRelation.objects.update_or_create(
                product_id=it_id,
                related_id=related_id,
                defaults={"ir_no": integer(row, "ir_no", 0)},
            )
            count += 1
        return count

    @suppress_notification_events()
    def import_shop_orders(self, rows):
        count = 0
        for row in rows:
            od_id = str(scalar(row, "od_id")).strip()
            if not od_id:
                continue
            order, _ = ShopOrder.objects.update_or_create(
                od_id=od_id,
                defaults={
                    "user": self.legacy_user(scalar(row, "mb_id")),
                    "od_name": text(row, "od_name", max_length=100),
                    "od_tel": text(row, "od_tel", max_length=50),
                    "od_hp": text(row, "od_hp", max_length=50),
                    "od_email": self.safe_email(scalar(row, "od_email")),
                    "od_zip": self.combined_zip(row, "od_zip")[:20],
                    "od_addr1": text(row, "od_addr1", max_length=255),
                    "od_addr2": text(row, "od_addr2", max_length=255),
                    "od_addr3": text(row, "od_addr3", max_length=255) or text(row, "od_addr_jibeon", max_length=255),
                    "od_b_name": text(row, "od_b_name", max_length=100),
                    "od_b_tel": text(row, "od_b_tel", max_length=50),
                    "od_b_hp": text(row, "od_b_hp", max_length=50),
                    "od_b_zip": self.combined_zip(row, "od_b_zip")[:20],
                    "od_b_addr1": text(row, "od_b_addr1", max_length=255),
                    "od_b_addr2": text(row, "od_b_addr2", max_length=255),
                    "od_b_addr3": text(row, "od_b_addr3", max_length=255) or text(row, "od_b_addr_jibeon", max_length=255),
                    "od_memo": text(row, "od_memo"),
                    "od_cart_price": integer(row, "od_cart_price", 0),
                    "od_send_cost": integer(row, "od_send_cost", 0),
                    "od_send_cost2": integer(row, "od_send_cost2", 0),
                    "od_receipt_price": integer(row, "od_receipt_price", 0),
                    "od_cancel_price": integer(row, "od_cancel_price", 0),
                    "od_refund_price": integer(row, "od_refund_price", 0),
                    "od_shop_memo": text(row, "od_shop_memo"),
                    "od_mod_history": text(row, "od_mod_history"),
                    "od_receipt_point": integer(row, "od_receipt_point", 0),
                    "od_deposit_name": text(row, "od_deposit_name", max_length=100),
                    "od_status": text(row, "od_status", "order", max_length=50) or "order",
                    "od_settle_case": text(row, "od_settle_case", "bank", max_length=50) or "bank",
                    "od_test": text(row, "od_test", max_length=1),
                    "od_misu": integer(row, "od_misu", 0),
                    "od_pg": text(row, "od_pg", max_length=50),
                    "od_tno": text(row, "od_tno", max_length=255),
                    "od_app_no": text(row, "od_app_no", max_length=255),
                    "od_tax_flag": integer(row, "od_tax_flag", 0),
                    "od_tax_mny": integer(row, "od_tax_mny", 0),
                    "od_vat_mny": integer(row, "od_vat_mny", 0),
                    "od_free_mny": integer(row, "od_free_mny", 0),
                    # od_coupon is the order coupon only: the product coupons (od_cart_coupon) come
                    # back from the imported coupon logs (order_coupon_totals), so folding them in
                    # here subtracted them twice from the order total
                    "od_coupon": integer(row, "od_coupon", 0),
                    "od_send_coupon": integer(row, "od_send_coupon", 0),
                    "od_point": integer(row, "od_receipt_point", 0),
                    "od_cash_no": text(row, "od_cash_no", max_length=255),
                    "od_cash_res": text(row, "od_cash_info", max_length=255),
                    "od_delivery_company": text(row, "od_delivery_company", max_length=100),
                    "od_invoice": text(row, "od_invoice", max_length=100),
                    "od_invoice_time": text(row, "od_invoice_time", max_length=100),
                    "od_datetime": datetime_value(scalar(row, "od_time")),
                    "od_receipt_time": text(row, "od_receipt_time", max_length=100),
                    "od_ip": self.safe_ip(scalar(row, "od_ip")),
                },
            )
            if not order.uid:
                order.uid = generate_order_uid()
                order.save(update_fields=["uid"])
            count += 1
        return count

    def import_shop_cart_items(self, rows):
        count = 0
        for row in rows:
            order = ShopOrder.objects.filter(pk=text(row, "od_id")).first()
            if not order:
                continue
            ct_id = str(integer(row, "ct_id", 0))
            product = ShopProduct.objects.filter(pk=text(row, "it_id")).first()
            order_item = (
                ShopOrderItem.objects.filter(order=order, ct_id=ct_id)
                .order_by("pk")
                .first()
            )
            if order_item is None:
                order_item = ShopOrderItem(order=order, ct_id=ct_id)
            order_item.product = product
            order_item.it_id = text(row, "it_id", max_length=40)
            order_item.it_name = text(row, "it_name", max_length=255)
            order_item.ct_price = integer(row, "ct_price", 0)
            order_item.ct_qty = max(integer(row, "ct_qty", 1), 1)
            order_item.ct_point = integer(row, "ct_point", 0)
            # Django keeps the option id here (inventory, cart, subscriptions match on it), not
            # youngcart's display label; the label is rebuilt from io_id and it_option_subject
            order_item.ct_option = text(row, "io_id", max_length=255)
            order_item.ct_status = text(row, "ct_status", "order", max_length=50) or "order"
            order_item.io_type = integer(row, "io_type", 0)
            order_item.io_price = integer(row, "io_price", 0)
            order_item.ct_notax = integer(row, "ct_notax", 0)
            order_item.ct_send_cost = integer(row, "ct_send_cost", 0)
            # source_pending_stock subtracted the pending lines from the imported stock already
            order_item.stock_adjusted = cart_stock_taken(row) or cart_stock_pending(row)
            self.apply_cart_point_state(order_item, row)
            order_item.image_url = product.image_url if product else ""
            order_item.save()
            count += 1
        return count

    def apply_cart_point_state(self, order_item, row):
        """Carry youngcart ct_point_use / ct_complete_time so a line PHP already paid is not paid
        again. A completed row without the column counts as paid; a line this site already paid
        stays paid on a re-import."""
        is_completed = order_item.ct_status == ORDER_ITEM_STATUS_COMPLETED
        if "ct_point_use" in row:
            point_use = bool(integer(row, "ct_point_use", 0))
        else:
            point_use = is_completed
        order_item.ct_point_use = bool(order_item.ct_point_use) or point_use
        complete_time = optional_datetime_value(scalar(row, "ct_complete_time"))
        if complete_time is None and is_completed:
            # youngcart save_order_point counts an unstamped completed line from its cart time
            complete_time = optional_datetime_value(scalar(row, "ct_time"))
        order_item.ct_complete_time = (complete_time or order_item.ct_complete_time) if is_completed else None

    def import_shop_order_data(self, rows):
        count = 0
        for row in rows:
            od_id = text(row, "od_id", max_length=40)
            cart_id = text(row, "cart_id", max_length=40)
            dt_pg = text(row, "dt_pg", max_length=50)
            dt_time = datetime_value(scalar(row, "dt_time"))
            log_id = self.order_data_log_id(row)
            ShopOrderData.objects.update_or_create(
                log_id=log_id,
                defaults={
                    "order": ShopOrder.objects.filter(pk=od_id).first(),
                    "od_id": od_id,
                    "cart_id": cart_id,
                    "user": self.legacy_user(scalar(row, "mb_id")),
                    "mb_id": text(row, "mb_id", max_length=150),
                    "dt_pg": dt_pg,
                    "dt_data": text(row, "dt_data"),
                    "dt_time": dt_time,
                },
            )
            count += 1
        return count

    def order_data_log_id(self, row):
        raw = "|".join(
            [
                text(row, "od_id"),
                text(row, "cart_id"),
                text(row, "mb_id"),
                text(row, "dt_pg"),
                str(scalar(row, "dt_time")),
                text(row, "dt_data")[:128],
            ]
        )
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def import_shop_addresses(self, rows):
        count = 0
        for row in rows:
            ad_id = integer(row, "ad_id", 0)
            user = self.legacy_user(scalar(row, "mb_id"))
            if not ad_id or not user:
                continue
            ShopAddress.objects.update_or_create(
                pk=ad_id,
                defaults={
                    "user": user,
                    "ad_subject": text(row, "ad_subject", max_length=100),
                    "ad_default": bool_char(row, "ad_default", False),
                    "ad_name": text(row, "ad_name", max_length=100),
                    "ad_tel": text(row, "ad_tel", max_length=50),
                    "ad_hp": text(row, "ad_hp", max_length=50),
                    "ad_zip": self.combined_zip(row, "ad_zip")[:20],
                    "ad_addr1": text(row, "ad_addr1", max_length=255),
                    "ad_addr2": text(row, "ad_addr2", max_length=255),
                    "ad_addr3": text(row, "ad_addr3", max_length=255),
                    "ad_jibeon": text(row, "ad_jibeon", max_length=255),
                },
            )
            count += 1
        return count

    def import_shop_coupon_zones(self, rows):
        count = 0
        for row in rows:
            cz_id = integer(row, "cz_id", 0)
            if not cz_id:
                continue
            ShopCouponZone.objects.update_or_create(
                pk=cz_id,
                defaults={
                    "cz_type": integer(row, "cz_type", 0),
                    "cz_point": integer(row, "cz_point", 0),
                    "cz_subject": text(row, "cz_subject", max_length=255),
                    "cz_start": date_value(scalar(row, "cz_start")) or timezone.localdate(),
                    "cz_end": date_value(scalar(row, "cz_end")),
                    "cz_file": text(row, "cz_file", max_length=1000),
                    "cz_period": integer(row, "cz_period", 30),
                    "cz_download": integer(row, "cz_download", 0),
                    "cp_method": integer(row, "cp_method", 2),
                    "cp_target": text(row, "cp_target", max_length=100),
                    "cp_type": integer(row, "cp_type", 0),
                    "cp_price": integer(row, "cp_price", 0),
                    "cp_minimum": integer(row, "cp_minimum", 0),
                    "cp_maximum": integer(row, "cp_maximum", 0),
                    "cp_trunc": integer(row, "cp_trunc", 1),
                    "image_url": self.coupon_zone_image_url(row),
                    "created_at": datetime_value(scalar(row, "cz_datetime")),
                },
            )
            count += 1
        return count

    def import_shop_coupons(self, rows):
        count = 0
        for row in rows:
            cp_id = str(scalar(row, "cp_id")).strip()
            if not cp_id:
                cp_id = f"legacy-{integer(row, 'cp_no', 0)}"
            coupon_zone = ShopCouponZone.objects.filter(pk=integer(row, "cz_id", 0)).first()
            ShopCoupon.objects.update_or_create(
                cp_id=cp_id[:40],
                defaults={
                    "user": self.legacy_user(scalar(row, "mb_id")),
                    "cp_all_members": scalar(row, "mb_id") == "전체회원",
                    "coupon_zone": coupon_zone,
                    "cp_subject": text(row, "cp_subject", max_length=255),
                    "cp_method": integer(row, "cp_method", 2),
                    "cp_target": text(row, "cp_target", max_length=100),
                    "cp_type": integer(row, "cp_type", 0),
                    "cp_price": integer(row, "cp_price", 0),
                    "cp_minimum": integer(row, "cp_minimum", 0),
                    "cp_maximum": integer(row, "cp_maximum", 0),
                    "cp_trunc": integer(row, "cp_trunc", 1),
                    "cp_start": date_value(scalar(row, "cp_start")) or timezone.localdate(),
                    "cp_end": date_value(scalar(row, "cp_end")),
                    "cp_used": "1" if scalar(row, "od_id") and scalar(row, "mb_id") != "전체회원" else "",
                    "created_at": datetime_value(scalar(row, "cp_datetime")),
                },
            )
            count += 1
        return count

    def import_shop_coupon_logs(self, rows):
        count = 0
        for row in rows:
            cl_id = integer(row, "cl_id", 0)
            if not cl_id:
                continue
            cp_id = text(row, "cp_id", max_length=40)
            od_id = text(row, "od_id", max_length=40)
            ShopCouponLog.objects.update_or_create(
                cl_id=cl_id,
                defaults={
                    "coupon": ShopCoupon.objects.filter(pk=cp_id).first(),
                    "cp_id": cp_id,
                    "user": self.legacy_user(scalar(row, "mb_id")),
                    "mb_id": text(row, "mb_id", max_length=150),
                    "order": ShopOrder.objects.filter(pk=od_id).first(),
                    "od_id": od_id,
                    "cp_price": integer(row, "cp_price", 0),
                    "cl_datetime": datetime_value(scalar(row, "cl_datetime")),
                },
            )
            count += 1
        return count

    def import_shop_personal_pays(self, rows):
        count = 0
        for row in rows:
            pp_id = str(integer(row, "pp_id", 0) or scalar(row, "pp_id")).strip()
            if not pp_id:
                continue
            order = ShopOrder.objects.filter(pk=text(row, "od_id")).first()
            ShopPersonalPay.objects.update_or_create(
                pp_id=pp_id[:40],
                defaults={
                    "user": self.legacy_user(scalar(row, "mb_id")),
                    "order": order,
                    "pp_name": text(row, "pp_name", max_length=100),
                    "pp_email": self.safe_email(scalar(row, "pp_email")),
                    "pp_hp": text(row, "pp_hp", max_length=50),
                    "pp_content": text(row, "pp_content"),
                    "pp_price": integer(row, "pp_price", 0),
                    "pp_settle_case": text(row, "pp_settle_case", "bank", max_length=50) or "bank",
                    "pp_bank_account": text(row, "pp_bank_account", max_length=255),
                    "pp_deposit_name": text(row, "pp_deposit_name", max_length=100),
                    "pp_receipt_price": integer(row, "pp_receipt_price", 0),
                    "pp_pg": text(row, "pp_pg", max_length=50),
                    "pp_tno": text(row, "pp_tno", max_length=255),
                    "pp_app_no": text(row, "pp_app_no", max_length=255),
                    "pp_cash": integer(row, "pp_cash", 0),
                    "pp_cash_no": text(row, "pp_cash_no", max_length=255),
                    "pp_receipt_time": text(row, "pp_receipt_time", max_length=100),
                    "pp_time": datetime_value(scalar(row, "pp_time")),
                    "active": bool_char(row, "pp_use", True),
                },
            )
            count += 1
        return count

    def combined_zip(self, row, prefix):
        first = text(row, f"{prefix}1")
        second = text(row, f"{prefix}2")
        merged = (first + second).strip()
        return merged or text(row, prefix)

    def safe_email(self, value):
        """The address, or "" when it is none or longer than an email field holds (a cut one is someone else's)."""
        value = str(value or "").strip()
        return value if "@" in value and len(value) <= EMAIL_MAX_LENGTH else ""

    def safe_ip(self, value):
        value = str(value or "").strip()
        if not value:
            return None
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return None

    def coupon_zone_image_url(self, row):
        image = scalar(row, "cz_file")
        return f"/data/coupon/{image}" if image else ""

    def legacy_post(self, bo_table, wr_id):
        board = Board.objects.filter(bo_table=str(bo_table or "").strip()).first()
        post = Post.objects.filter(board=board, legacy_wr_id=wr_id).order_by("pk").first() if board and wr_id else None
        return board, post

    def report_skipped(self, label, skipped):
        if skipped:
            reasons = ", ".join(f"{reason} {count}" for reason, count in sorted(skipped.items()))
            self.warn(f"{label}: skipped {sum(skipped.values())} row(s): {reasons}")

    def import_member_social(self, rows):
        """g5_member_social_profiles as the identity links the Django social login looks up
        (v1_auth._social_identity_owner): HybridAuth's provider name and identifier are the provider
        and user id Django reads back from the same provider."""
        count = 0
        skipped = Counter()
        links = defaultdict(list)
        for row in rows:
            provider = text(row, "provider").strip().lower()
            identifier = text(row, "identifier").strip()[:255]
            if provider not in SOCIAL_PROVIDER_SPECS:
                skipped["unknown provider"] += 1
            elif not identifier:
                skipped["no identifier"] += 1
            else:
                links[(provider, identifier)].append(row)
        conflicts = []
        for (provider, identifier), link_rows in links.items():
            # social_get_data(): "where provider and identifier ... order by mb_id desc" logs in the first row
            row = max(link_rows, key=lambda link: text(link, "mb_id").strip().casefold())
            mb_id = text(row, "mb_id").strip()
            others = sorted({text(link, "mb_id").strip() for link in link_rows} - {mb_id})
            if others:
                conflicts.append(f"  {provider} {identifier}: {mb_id} (not {', '.join(others)})")
            user = self.legacy_user(mb_id)
            if not user:
                skipped["member not imported"] += 1
                continue
            linked_at = optional_datetime_value(scalar(row, "mp_register_day"))
            payload = {
                "provider": provider,
                "provider_label": SOCIAL_PROVIDER_SPECS[provider].get("label", provider.title()),
                "provider_user_id": identifier,
                "user_id": user.pk,
                "username": user.get_username(),
                "email": user.email,
                "linked_at": (linked_at or timezone.now()).isoformat(),
            }
            Config.objects.update_or_create(
                name=_social_identity_config_name(provider, identifier),
                defaults={"value": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            )
            count += 1
        if conflicts:
            self.warn(
                f"member_social: {len(conflicts)} identity(ies) are linked to more than one member in the source; "
                "each logs in to the member Gnuboard picks (ORDER BY mb_id DESC):"
            )
            for line in sorted(conflicts):
                self.warn(line)
        self.report_skipped("member_social", skipped)
        return count

    def import_qa_content(self, rows):
        """g5_qa_content as 1:1 inquiries. Gnuboard keeps the answer as its own row (qa_type 1,
        qa_parent the question); Django keeps it on the question (iq_answer) and its subject in the
        qa_meta config row, and an inquiry is answered when iq_answer is set."""
        questions = [row for row in rows if integer(row, "qa_type", 0) == 0 and integer(row, "qa_id", 0) > 0]
        answers = {integer(row, "qa_parent", 0): row for row in rows if integer(row, "qa_type", 0) == 1}
        product = _general_qa_product() if questions else None
        items = {}
        for row in questions:
            legacy_id = integer(row, "qa_id", 0)
            username = text(row, "mb_id").strip()
            defaults = {
                "product": product,
                "user": self.legacy_user(username),
                "mb_id": username,
                "mb_nick": text(row, "qa_name", max_length=150),
                "iq_name": text(row, "qa_name", max_length=150),
                # a subject is text in Gnuboard too (get_text); qa_html covers the body only
                "iq_subject": text(row, "qa_subject", max_length=255),
                "iq_question": qa_plain_text(row),
                "iq_email": self.safe_email(scalar(row, "qa_email")),
                "iq_hp": text(row, "qa_hp", max_length=50),
                "iq_time": datetime_value(scalar(row, "qa_datetime")),
            }
            if legacy_id in answers:
                # with no source answer, an answer written in Django since the last run stays
                defaults["iq_answer"] = qa_plain_text(answers[legacy_id])
            items[legacy_id], _ = ShopQA.objects.update_or_create(legacy_qa_id=legacy_id, defaults=defaults)

        unanswered = []
        missing_files = []
        for row in questions:
            legacy_id = integer(row, "qa_id", 0)
            item = items[legacy_id]
            if integer(row, "qa_status", 0) == 1 and not item.iq_answer:
                unanswered.append(legacy_id)
            meta = _qa_empty_meta()
            meta["answer_subject"] = (
                text(answers[legacy_id], "qa_subject") if legacy_id in answers else _qa_load_meta(item.pk)["answer_subject"]
            )
            related = items.get(integer(row, "qa_related", 0))
            if related and related.pk != item.pk:
                # a 추가 질문: Django marks a follow-up with its own id and the question it follows
                meta["parent"] = item.pk
                meta["related"] = related.pk
            for slot in (1, 2):
                copied = self.copy_legacy_qa_file(item, text(row, f"qa_file{slot}"), text(row, f"qa_source{slot}"))
                if copied is None:
                    missing_files.append(legacy_id)
                elif copied:
                    meta["files"][slot - 1] = copied
            if meta != _qa_empty_meta():
                _qa_save_meta(item.pk, meta)
        if unanswered:
            self.warn(
                f"qa_content: {len(unanswered)} inquiry(ies) marked answered in the source have no answer row: qa_id "
                + ", ".join(map(str, unanswered))
            )
        if missing_files:
            self.warn(
                f"qa_content: {len(missing_files)} attachment(s) missing from the source (or of a refused type) "
                "were not imported: qa_id " + ", ".join(map(str, dict.fromkeys(missing_files)))
            )
        return len(items)

    def copy_legacy_qa_file(self, item, filename, source_name):
        """The qa_meta file slot for a data/qa attachment: {} when there is none, None when it cannot
        be imported (missing, outside data/qa, or a type qawrite_update.php would refuse)."""
        filename = self.legacy_filename(filename)
        if not filename:
            return {}
        name = source_name or filename
        base = (self.source_root / "data" / "qa").resolve()
        path = (base / filename).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            return None
        if QA_ACTIVE_EXTENSION_RE.search(filename) or QA_ACTIVE_EXTENSION_RE.search(name):
            return None
        target = f"shop/qas/{item.pk}/{filename}"
        if not default_storage.exists(target):
            with path.open("rb") as source_file:
                target = default_storage.save(target, File(source_file))
        return {"path": target, "name": name, "url": default_storage.url(target)}

    def import_shop_wishes(self, rows):
        count = 0
        skipped = Counter()
        for row in rows:
            user = self.legacy_user(text(row, "mb_id").strip())
            it_id = text(row, "it_id", max_length=40).strip()
            if not user or not it_id:
                skipped["member not imported" if it_id else "no product id"] += 1
                continue
            # the same key the wishlist API adds a product under (shop_cart.wishlist_view)
            ShopWishlist.objects.update_or_create(
                user=user,
                it_id=it_id,
                defaults={
                    "product": ShopProduct.objects.filter(pk=it_id).first(),
                    "wi_time": datetime_value(scalar(row, "wi_time")),
                },
            )
            count += 1
        self.report_skipped("shop_wish", skipped)
        return count

    def import_scraps(self, rows):
        """g5_scrap as Post_scrap, the scraps the member API lists (User_Scrap is an admin-only leftover)."""
        count = 0
        skipped = Counter()
        for row in rows:
            user = self.legacy_user(text(row, "mb_id").strip())
            board, post = self.legacy_post(scalar(row, "bo_table"), integer(row, "wr_id", 0))
            if not user or not post:
                skipped["member not imported" if post else "post not imported"] += 1
                continue
            Post_scrap.objects.update_or_create(
                user=user, board=board, post=post, defaults={"ms_datetime": datetime_value(scalar(row, "ms_datetime"))}
            )
            count += 1
        self.report_skipped("scrap", skipped)
        return count

    def import_board_goods(self, rows):
        """g5_board_good: the vote each member already cast, so good.php's once-per-member rule holds.
        The post's wr_good / wr_nogood totals come with the post itself."""
        count = 0
        skipped = Counter()
        for row in rows:
            flag = text(row, "bg_flag").strip()
            user = self.legacy_user(text(row, "mb_id").strip())
            board, post = self.legacy_post(scalar(row, "bo_table"), integer(row, "wr_id", 0))
            if flag not in ("good", "nogood"):
                skipped["unknown bg_flag"] += 1
                continue
            if not user or not post:
                skipped["member not imported" if post else "post not imported"] += 1
                continue
            Post_good.objects.update_or_create(
                post=post,
                user=user,
                defaults={"board": board, "bg_flag": flag, "bg_datetime": datetime_value(scalar(row, "bg_datetime"))},
            )
            count += 1
        self.report_skipped("board_good", skipped)
        return count

    def import_new_wins(self, rows):
        count = 0
        for row in rows:
            nw_id = integer(row, "nw_id", 0)
            if nw_id <= 0:
                continue
            New_win.objects.update_or_create(
                pk=nw_id,
                defaults={
                    # youngcart adds "shop"; the community popup page shows "both" and "comm"
                    "nw_division": text(row, "nw_division", "comm", max_length=10),
                    "nw_device": text(row, "nw_device", "both", max_length=10),
                    "nw_begin_time": optional_datetime_value(scalar(row, "nw_begin_time")),
                    "nw_end_time": optional_datetime_value(scalar(row, "nw_end_time")),
                    "nw_disable_hours": integer(row, "nw_disable_hours", 0),
                    "nw_left": integer(row, "nw_left", 0),
                    "nw_top": integer(row, "nw_top", 0),
                    "nw_height": integer(row, "nw_height", 0),
                    "nw_width": integer(row, "nw_width", 0),
                    "nw_subject": text(row, "nw_subject"),
                    "nw_content": text(row, "nw_content"),
                    "nw_content_html": integer(row, "nw_content_html", 0),
                },
            )
            count += 1
        return count

    def import_menus(self, rows):
        count = 0
        for row in rows:
            me_id = integer(row, "me_id", 0)
            if me_id <= 0:
                continue
            Site_menu.objects.update_or_create(
                pk=me_id,
                defaults={
                    "me_code": text(row, "me_code", max_length=255),
                    "me_name": text(row, "me_name", max_length=255),
                    "me_link": text(row, "me_link", max_length=255),
                    "me_target": text(row, "me_target", max_length=255),
                    "me_order": integer(row, "me_order", 0),
                    "me_use": integer(row, "me_use", 0),
                    "me_mobile_use": integer(row, "me_mobile_use", 0),
                },
            )
            count += 1
        return count

    def report_admin_auth(self, rows):
        """g5_auth is not imported. Gnuboard grants a sub-admin r/w/d per admin menu code; Django
        admin access is per-model permissions (groups such as setup_admin_role_presets), and a menu
        code does not map onto a set of models without granting more than the source did. The run
        lists each grant so the operator can assign a Django role by hand."""
        grants = defaultdict(list)
        for row in rows:
            mb_id = text(row, "mb_id").strip()
            if mb_id:
                grants[mb_id].append(f"{text(row, 'au_menu').strip()}({text(row, 'au_auth').strip()})")
        if grants:
            self.warn(
                f"auth: {sum(map(len, grants.values()))} admin menu grant(s) for {len(grants)} member(s) were not "
                "imported. Django admin uses per-model permissions, so these members have no admin access; "
                "assign each a Django group (see setup_admin_role_presets) by hand:"
            )
            for mb_id, menus in sorted(grants.items()):
                self.warn(f"  {mb_id}: {' '.join(sorted(menus))}")
        return 0

    def import_shop_reviews(self, rows):
        count = 0
        User = get_user_model()
        for row in rows:
            review_id = integer(row, "is_id", 0)
            product = ShopProduct.objects.filter(pk=scalar(row, "it_id")).first()
            if not review_id or not product:
                continue
            username = text(row, "mb_id", max_length=150)
            user = User.objects.filter(username=username).first() if username else None
            ShopReview.objects.update_or_create(
                pk=review_id,
                defaults={
                    "product": product,
                    "user": user,
                    "mb_id": username,
                    "mb_nick": text(row, "is_name", max_length=150),
                    "is_name": text(row, "is_name", max_length=150),
                    "is_score": integer(row, "is_score", 5),
                    "is_subject": scalar(row, "is_subject") or scalar(row, "is_content")[:80],
                    "is_content": scalar(row, "is_content"),
                    "is_confirm": flag(row, "is_confirm", "1"),
                    "is_time": datetime_value(scalar(row, "is_time")),
                },
            )
            count += 1
        return count

    def import_shop_qna(self, rows):
        count = 0
        User = get_user_model()
        for row in rows:
            iq_id = integer(row, "iq_id", 0)
            product = ShopProduct.objects.filter(pk=scalar(row, "it_id")).first()
            if not iq_id or not product:
                continue
            username = text(row, "mb_id", max_length=150)
            user = User.objects.filter(username=username).first() if username else None
            # keyed by its own source id, not the pk: the 1:1 inquiries share ShopQA's ids
            ShopQA.objects.update_or_create(
                legacy_iq_id=iq_id,
                defaults={
                    "product": product,
                    "user": user,
                    "mb_id": username,
                    "mb_nick": text(row, "iq_name", max_length=150),
                    "iq_name": text(row, "iq_name", max_length=150),
                    "iq_subject": scalar(row, "iq_subject") or scalar(row, "iq_question")[:80],
                    "iq_question": scalar(row, "iq_question"),
                    "iq_answer": scalar(row, "iq_answer"),
                    "iq_secret": integer(row, "iq_secret", 0),
                    "iq_email": self.safe_email(scalar(row, "iq_email")),
                    "iq_hp": text(row, "iq_hp", max_length=50),
                    "iq_time": datetime_value(scalar(row, "iq_time")),
                },
            )
            count += 1
        return count
