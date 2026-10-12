import json

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from gnu_jango.shop.models import ShopOrder, ShopPersonalPay, ShopProduct
from gnu_jango.users.models import Profile


SUSPICIOUS_MARKERS = (
    "???",
    "\ufffd",
    "\u00c3",
    "\u00c2",
)

MODEL_RULES = (
    {
        "name": "shop_orders",
        "model": ShopOrder,
        "text_fields": ("od_name", "od_email", "od_addr1", "od_b_name", "od_status", "od_pg"),
        "required_fields": ("od_id", "od_name"),
    },
    {
        "name": "shop_products",
        "model": ShopProduct,
        "text_fields": ("it_id", "it_name", "image_url"),
        "required_fields": ("it_id", "it_name"),
    },
    {
        "name": "personal_pays",
        "model": ShopPersonalPay,
        "text_fields": ("pp_id", "pp_name", "pp_email", "pp_settle_case", "pp_pg"),
        "required_fields": ("pp_id", "pp_name"),
    },
    {
        "name": "member_profiles",
        "model": Profile,
        "text_fields": ("nickname", "realname", "avatar"),
        "required_fields": (),
    },
)


class Command(BaseCommand):
    help = "Audit imported Gnuboard5 data for suspicious mojibake markers and missing critical values."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report.")
        parser.add_argument("--sample-size", type=int, default=5, help="Sample rows per failing rule.")
        parser.add_argument("--fail-on-issues", action="store_true", help="Exit non-zero when issues are found.")
        parser.add_argument(
            "--repair-obvious-placeholders",
            action="store_true",
            help="Replace obvious placeholder/mojibake values that cannot be restored.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Preview repairs without writing changes.")

    def handle(self, *args, **options):
        sample_size = max(int(options["sample_size"]), 1)
        repaired = 0
        if options["repair_obvious_placeholders"]:
            repaired = self.repair_obvious_placeholders(dry_run=bool(options["dry_run"]))
        checks = [self.audit_rule(rule, sample_size) for rule in MODEL_RULES]
        total_issues = sum(row["suspicious_count"] + row["missing_required_count"] for row in checks)
        report = {
            "summary": {
                "models_checked": len(checks),
                "issues": total_issues,
                "repaired": repaired,
                "dry_run": bool(options["dry_run"]),
            },
            "checks": checks,
        }

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.print_report(report)

        if total_issues and options["fail_on_issues"]:
            raise CommandError(f"Legacy data quality audit found {total_issues} issue(s).")

    def audit_rule(self, rule, sample_size):
        model = rule["model"]
        suspicious_q = self.suspicious_query(rule["text_fields"])
        missing_q = self.missing_required_query(rule["required_fields"])
        suspicious = model.objects.filter(suspicious_q) if suspicious_q else model.objects.none()
        missing = model.objects.filter(missing_q) if missing_q else model.objects.none()
        sample_queryset = (suspicious | missing).distinct().order_by(model._meta.pk.name)
        return {
            "name": rule["name"],
            "model": model._meta.label,
            "total_count": model.objects.count(),
            "suspicious_count": suspicious.distinct().count(),
            "missing_required_count": missing.distinct().count(),
            "sample_ids": [str(value) for value in sample_queryset.values_list(model._meta.pk.name, flat=True)[:sample_size]],
        }

    def suspicious_query(self, fields):
        query = Q()
        for field in fields:
            for marker in SUSPICIOUS_MARKERS:
                query |= Q(**{f"{field}__contains": marker})
        return query

    def missing_required_query(self, fields):
        query = Q()
        for field in fields:
            query |= Q(**{field: ""}) | Q(**{f"{field}__isnull": True})
        return query

    def repair_obvious_placeholders(self, *, dry_run):
        repaired = 0
        for rule in MODEL_RULES:
            model = rule["model"]
            fields = rule["text_fields"]
            queryset = model.objects.filter(self.suspicious_query(fields)).distinct()
            for row in queryset.iterator():
                update_fields = []
                for field in fields:
                    value = getattr(row, field, "")
                    repaired_value = self.repaired_text_value(field, value)
                    if repaired_value is not None and repaired_value != value:
                        setattr(row, field, repaired_value)
                        update_fields.append(field)
                if update_fields:
                    repaired += len(update_fields)
                    if not dry_run:
                        row.save(update_fields=update_fields)
        return repaired

    def repaired_text_value(self, field, value):
        text = str(value or "")
        if not any(marker in text for marker in SUSPICIOUS_MARKERS):
            return None

        cleaned = text.replace("\ufffd", "").replace("\u00c3", "").replace("\u00c2", "").strip()
        if "?" in cleaned:
            if "addr" in field:
                return ""
            if field.endswith("name") or field in ("nickname", "realname", "it_name"):
                without_questions = cleaned.replace("?", "").strip()
                return without_questions or "Unknown"
            cleaned = cleaned.replace("?", "").strip()
        return cleaned

    def print_report(self, report):
        summary = report["summary"]
        self.stdout.write("Legacy data quality")
        self.stdout.write(f"  models checked: {summary['models_checked']}")
        self.stdout.write(f"  issues: {summary['issues']}")
        self.stdout.write(f"  repaired: {summary['repaired']} (dry_run={'yes' if summary['dry_run'] else 'no'})")
        for check in report["checks"]:
            self.stdout.write(
                f"- {check['name']}: total={check['total_count']}, "
                f"suspicious={check['suspicious_count']}, "
                f"missing_required={check['missing_required_count']}, "
                f"samples={', '.join(check['sample_ids']) or '-'}"
            )
