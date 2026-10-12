import json

from django.core.files.base import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.bbs.models import Post_file
from gnu_jango.core.legacy_assets import DEFAULT_LEGACY_GNUBOARD5_SOURCE_ROOT, legacy_source_roots
from gnu_jango.core.management.commands.audit_gnuboard_assets import (
    legacy_board_path,
    normalize_url_path,
    product_image_paths,
    source_path,
)
from gnu_jango.shop.models import ShopProduct


def safe_target_name(path):
    normalized = normalize_url_path(path)
    if not normalized or normalized in {".", "data"} or normalized.startswith("../"):
        return ""
    if not normalized.startswith("data/"):
        return ""
    return normalized


class Command(BaseCommand):
    help = "Copy recoverable Gnuboard5 board/product assets into Django media storage under data/..."

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
            help="Additional Gnuboard5 PHP/data root to search. Can be used multiple times.",
        )
        parser.add_argument(
            "--only",
            action="append",
            choices=("board", "product"),
            help="Limit sync to board or product assets. Can be used multiple times.",
        )
        parser.add_argument("--apply", action="store_true", help="Actually copy files. Without this, dry-run only.")
        parser.add_argument("--overwrite", action="store_true", help="Replace existing media files.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary.")
        parser.add_argument(
            "--sample-size",
            type=int,
            default=20,
            help="Maximum number of sample copied/missing paths to include per section.",
        )

    def handle(self, *args, **options):
        source_roots = legacy_source_roots([options["source_root"], *(options["extra_source_root"] or [])])
        existing_roots = [root for root in source_roots if root.exists()]
        if not existing_roots:
            roots = ", ".join(str(root) for root in source_roots)
            raise CommandError(f"No Gnuboard5 source roots were found: {roots}")

        selected = set(options["only"] or ("board", "product"))
        sample_size = max(0, int(options["sample_size"]))
        context = {
            "source_roots": existing_roots,
            "apply": bool(options["apply"]),
            "overwrite": bool(options["overwrite"]),
            "sample_size": sample_size,
        }
        summary = {
            "applied": context["apply"],
            "overwrite": context["overwrite"],
            "source_roots": [str(root) for root in existing_roots],
            "board_files": self.sync_board_files(context) if "board" in selected else None,
            "product_images": self.sync_product_images(context) if "product" in selected else None,
        }

        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.print_summary(summary)

    def sync_board_files(self, context):
        rows = Post_file.objects.select_related("board", "post").order_by("board__bo_table", "post_id", "bf_no", "pk")
        summary = self.empty_summary(rows.count())
        seen = set()
        for row in rows:
            legacy_path = legacy_board_path(row)
            if legacy_path in seen:
                continue
            seen.add(legacy_path)
            self.sync_one(legacy_path, context, summary)
        summary["unique_references"] = len(seen)
        return summary

    def sync_product_images(self, context):
        products = ShopProduct.objects.order_by("it_id")
        summary = self.empty_summary(0)
        seen = set()
        products_with_images = 0
        for product in products:
            paths = product_image_paths(product)
            if not paths:
                continue
            products_with_images += 1
            for path in paths:
                summary["references"] += 1
                if path in seen:
                    summary["duplicate_references"] += 1
                    continue
                seen.add(path)
                self.sync_one(path, context, summary)
        summary["products_with_legacy_images"] = products_with_images
        summary["unique_references"] = len(seen)
        return summary

    def empty_summary(self, references):
        return {
            "references": references,
            "unique_references": 0,
            "duplicate_references": 0,
            "source_present": 0,
            "source_missing": 0,
            "copied": 0,
            "would_copy": 0,
            "skipped_existing": 0,
            "invalid_target": 0,
            "copied_samples": [],
            "missing_samples": [],
        }

    def sync_one(self, legacy_path, context, summary):
        target_name = safe_target_name(legacy_path)
        if not target_name:
            summary["invalid_target"] += 1
            return

        source = source_path(context["source_roots"], target_name)
        if not source:
            summary["source_missing"] += 1
            self.append_sample(summary["missing_samples"], context["sample_size"], target_name)
            return

        summary["source_present"] += 1
        if default_storage.exists(target_name) and not context["overwrite"]:
            summary["skipped_existing"] += 1
            return

        if not context["apply"]:
            summary["would_copy"] += 1
            self.append_sample(summary["copied_samples"], context["sample_size"], target_name)
            return

        if default_storage.exists(target_name) and context["overwrite"]:
            default_storage.delete(target_name)
        with source.open("rb") as source_file:
            default_storage.save(target_name, File(source_file))
        summary["copied"] += 1
        self.append_sample(summary["copied_samples"], context["sample_size"], target_name)

    def append_sample(self, samples, sample_size, sample):
        if len(samples) < sample_size:
            samples.append(sample)

    def print_summary(self, summary):
        self.stdout.write(f"Applied: {'yes' if summary['applied'] else 'no (dry-run)'}")
        self.stdout.write(f"Overwrite: {'yes' if summary['overwrite'] else 'no'}")
        self.stdout.write("Source roots:")
        for root in summary["source_roots"]:
            self.stdout.write(f"  - {root}")
        if summary["board_files"] is not None:
            self.print_section("Board file assets", summary["board_files"])
        if summary["product_images"] is not None:
            self.print_section("Product image assets", summary["product_images"])

    def print_section(self, label, section):
        self.stdout.write(label + ":")
        for key in (
            "references",
            "unique_references",
            "duplicate_references",
            "products_with_legacy_images",
            "source_present",
            "source_missing",
            "would_copy",
            "copied",
            "skipped_existing",
            "invalid_target",
        ):
            if key in section:
                self.stdout.write(f"  {key}: {section[key]}")
