import json
import posixpath
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.bbs.models import Post_file
from gnu_jango.core.legacy_assets import (
    DEFAULT_LEGACY_GNUBOARD5_SOURCE_ROOT,
    legacy_data_root,
    legacy_source_roots,
)
from gnu_jango.shop.models import ShopProduct


def normalize_url_path(value):
    path = str(value or "").replace("\\", "/").strip()
    if not path:
        return ""
    if "://" in path:
        return ""
    path = path.split("?", 1)[0].split("#", 1)[0].strip("/")
    return posixpath.normpath(path).replace("\\", "/")


def is_safe_relative_path(path):
    return bool(path) and not path.startswith("../") and path != ".." and path != "."


def source_path(source_roots, path):
    normalized = normalize_url_path(path)
    if not is_safe_relative_path(normalized):
        return None
    if normalized == "data":
        return None
    if normalized.startswith("data/"):
        normalized = normalized[5:]
    for source_root in source_roots:
        candidate = legacy_data_root(source_root) / Path(normalized)
        if candidate.is_file():
            return candidate
    return None


def legacy_board_path(post_file):
    fileurl = normalize_url_path(post_file.bf_fileurl)
    if fileurl.startswith("data/file/"):
        return fileurl

    filename = Path(str(post_file.bf_source or "")).name
    board_table = getattr(post_file.board, "bo_table", "")
    if filename and board_table:
        return f"data/file/{board_table}/{filename}"
    return ""


def product_image_paths(product):
    paths = []
    seen = set()

    def add(value):
        path = normalize_url_path(value)
        if not path.startswith("data/item/") or path in seen:
            return
        seen.add(path)
        paths.append(path)

    add(product.image_url)
    for item in product.images or []:
        if isinstance(item, dict):
            add(item.get("url") or item.get("src") or item.get("image_url"))
        else:
            add(item)
    return paths


def exists_on_source(source_roots, path):
    candidate = source_path(source_roots, path)
    return bool(candidate and candidate.is_file())


def media_path(path):
    normalized = normalize_url_path(path)
    if not is_safe_relative_path(normalized):
        return None
    if not normalized.startswith("data/"):
        return None
    return Path(settings.MEDIA_ROOT) / Path(normalized)


def exists_in_media(path):
    candidate = media_path(path)
    return bool(candidate and candidate.is_file())


def storage_exists(name):
    if not name:
        return False
    try:
        return default_storage.exists(str(name))
    except OSError:
        return False


class Command(BaseCommand):
    help = "Audit imported Gnuboard5 board/product asset references against source files and Django storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-root",
            default=str(DEFAULT_LEGACY_GNUBOARD5_SOURCE_ROOT),
            help="Primary Gnuboard5 PHP root. Defaults to C:\\xampp824\\www\\gnuboard5_3.",
        )
        parser.add_argument(
            "--extra-source-root",
            action="append",
            default=[],
            help="Additional Gnuboard5 PHP/data root to search for legacy assets. Can be used multiple times.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print a machine-readable JSON summary.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=20,
            help="Maximum number of missing/recoverable examples to include per section.",
        )
        parser.add_argument(
            "--fail-on-missing",
            action="store_true",
            help="Exit with an error when any referenced source asset is missing.",
        )
        parser.add_argument(
            "--fail-on-recoverable",
            action="store_true",
            help="Exit with an error when a source board file exists but is not linked in Django storage.",
        )
        parser.add_argument(
            "--fail-on-unserved",
            action="store_true",
            help="Exit with an error when any referenced asset is unavailable from Django storage/media/source roots.",
        )

    def handle(self, *args, **options):
        source_roots = legacy_source_roots([options["source_root"], *(options["extra_source_root"] or [])])
        existing_roots = [root for root in source_roots if root.exists()]
        if not existing_roots:
            roots = ", ".join(str(root) for root in source_roots)
            raise CommandError(f"No Gnuboard5 source roots were found: {roots}")

        sample_size = max(0, int(options["sample_size"]))
        summary = {
            "source_root": str(existing_roots[0]),
            "source_roots": [str(root) for root in existing_roots],
            "board_files": self.audit_board_files(existing_roots, sample_size),
            "product_images": self.audit_product_images(existing_roots, sample_size),
        }

        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.print_summary(summary)

        missing_count = (
            summary["board_files"]["source_missing"]
            + summary["product_images"]["source_missing"]
        )
        recoverable_count = summary["board_files"]["recoverable_missing_storage"]
        unserved_count = summary["board_files"]["served_missing"] + summary["product_images"]["served_missing"]

        if options["fail_on_missing"] and missing_count:
            raise CommandError(f"{missing_count} referenced Gnuboard5 asset(s) are missing from source_root.")
        if options["fail_on_recoverable"] and recoverable_count:
            raise CommandError(
                f"{recoverable_count} board file(s) exist in source_root but are not linked in Django storage."
            )
        if options["fail_on_unserved"] and unserved_count:
            raise CommandError(f"{unserved_count} referenced Gnuboard5 asset(s) are not currently servable.")

    def audit_board_files(self, source_roots, sample_size):
        rows = Post_file.objects.select_related("board", "post").order_by("board__bo_table", "post_id", "bf_no", "pk")
        summary = {
            "references": rows.count(),
            "storage_linked": 0,
            "storage_present": 0,
            "storage_missing": 0,
            "metadata_only": 0,
            "media_present": 0,
            "source_present": 0,
            "source_missing": 0,
            "served_present": 0,
            "served_missing": 0,
            "recoverable_missing_storage": 0,
            "missing_source_samples": [],
            "unserved_samples": [],
            "recoverable_samples": [],
        }

        for row in rows:
            storage_name = getattr(row.bf_file, "name", "") or ""
            storage_present = storage_exists(storage_name)
            legacy_path = legacy_board_path(row)
            media_present = exists_in_media(legacy_path)
            source_present = exists_on_source(source_roots, legacy_path)
            served_present = storage_present or media_present or source_present

            if storage_name:
                summary["storage_linked"] += 1
                if storage_present:
                    summary["storage_present"] += 1
                else:
                    summary["storage_missing"] += 1
            else:
                summary["metadata_only"] += 1

            if media_present:
                summary["media_present"] += 1

            if source_present:
                summary["source_present"] += 1
                if not storage_present:
                    summary["recoverable_missing_storage"] += 1
                    self.append_sample(
                        summary["recoverable_samples"],
                        sample_size,
                        self.board_sample(row, legacy_path, storage_name),
                    )
            else:
                summary["source_missing"] += 1
                self.append_sample(
                    summary["missing_source_samples"],
                    sample_size,
                    self.board_sample(row, legacy_path, storage_name),
                )

            if served_present:
                summary["served_present"] += 1
            else:
                summary["served_missing"] += 1
                self.append_sample(
                    summary["unserved_samples"],
                    sample_size,
                    self.board_sample(row, legacy_path, storage_name),
                )

        return summary

    def audit_product_images(self, source_roots, sample_size):
        summary = {
            "products_with_legacy_images": 0,
            "references": 0,
            "media_present": 0,
            "source_present": 0,
            "source_missing": 0,
            "served_present": 0,
            "served_missing": 0,
            "missing_source_samples": [],
            "unserved_samples": [],
        }

        for product in ShopProduct.objects.order_by("it_id"):
            paths = product_image_paths(product)
            if not paths:
                continue
            summary["products_with_legacy_images"] += 1
            for path in paths:
                summary["references"] += 1
                media_present = exists_in_media(path)
                source_present = exists_on_source(source_roots, path)
                if media_present:
                    summary["media_present"] += 1
                if source_present:
                    summary["source_present"] += 1
                else:
                    summary["source_missing"] += 1
                    self.append_sample(
                        summary["missing_source_samples"],
                        sample_size,
                        {
                            "it_id": product.it_id,
                            "it_name": product.it_name,
                            "path": path,
                        },
                    )
                if media_present or source_present:
                    summary["served_present"] += 1
                else:
                    summary["served_missing"] += 1
                    self.append_sample(
                        summary["unserved_samples"],
                        sample_size,
                        {
                            "it_id": product.it_id,
                            "it_name": product.it_name,
                            "path": path,
                        },
                    )

        return summary

    def board_sample(self, post_file, legacy_path, storage_name):
        return {
            "id": post_file.pk,
            "bo_table": getattr(post_file.board, "bo_table", ""),
            "post_id": post_file.post_id,
            "bf_no": post_file.bf_no,
            "bf_source": post_file.bf_source,
            "legacy_path": legacy_path,
            "storage_name": storage_name,
        }

    def append_sample(self, samples, sample_size, sample):
        if len(samples) < sample_size:
            samples.append(sample)

    def print_summary(self, summary):
        board = summary["board_files"]
        products = summary["product_images"]
        self.stdout.write("Source roots:")
        for root in summary["source_roots"]:
            self.stdout.write(f"  - {root}")
        self.stdout.write("Board file assets:")
        self.stdout.write(f"  references: {board['references']}")
        self.stdout.write(f"  storage linked/present/missing: {board['storage_linked']}/{board['storage_present']}/{board['storage_missing']}")
        self.stdout.write(f"  metadata only: {board['metadata_only']}")
        self.stdout.write(f"  media present: {board['media_present']}")
        self.stdout.write(f"  source present/missing: {board['source_present']}/{board['source_missing']}")
        self.stdout.write(f"  served present/missing: {board['served_present']}/{board['served_missing']}")
        self.stdout.write(f"  recoverable missing storage: {board['recoverable_missing_storage']}")
        self.stdout.write("Product image assets:")
        self.stdout.write(f"  products with legacy images: {products['products_with_legacy_images']}")
        self.stdout.write(f"  references: {products['references']}")
        self.stdout.write(f"  media present: {products['media_present']}")
        self.stdout.write(f"  source present/missing: {products['source_present']}/{products['source_missing']}")
        self.stdout.write(f"  served present/missing: {products['served_present']}/{products['served_missing']}")
