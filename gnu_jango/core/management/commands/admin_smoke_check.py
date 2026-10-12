import json

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import NoReverseMatch, reverse


CUSTOM_ADMIN_URL_NAMES = (
    "admin:shop_shoporder_reports",
    "admin:shop_shoporder_sales_rank",
    "admin:shop_shoporder_print",
    "admin:core_notification_mail_tools",
    "admin:core_visitlog_reports",
    "admin:core_searchkeyword_reports",
)


class Command(BaseCommand):
    help = "Run a logged-in smoke check across admin pages and custom admin reports."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="", help="Superuser username to use. Defaults to the first active superuser.")
        parser.add_argument("--json", action="store_true", help="Print JSON output.")
        parser.add_argument("--fail-on-warning", action="store_true", help="Fail when a URL returns 4xx.")

    def handle(self, *args, **options):
        user = self.admin_user(options["username"])
        client = Client(HTTP_HOST="127.0.0.1", raise_request_exception=False)
        client.force_login(user)

        checks = []
        for label, url in self.admin_urls():
            response = client.get(url)
            status = response.status_code
            body = response.content.decode("utf-8", errors="replace")
            result = {
                "label": label,
                "url": url,
                "status_code": status,
                "status": "pass" if status < 400 and "Traceback" not in body else "warn" if status < 500 else "fail",
            }
            checks.append(result)

        summary = {
            "passed": sum(1 for row in checks if row["status"] == "pass"),
            "warnings": sum(1 for row in checks if row["status"] == "warn"),
            "failed": sum(1 for row in checks if row["status"] == "fail"),
            "total": len(checks),
        }
        report = {"user": user.get_username(), "summary": summary, "checks": checks}

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.print_report(report)

        if summary["failed"] or (options["fail_on_warning"] and summary["warnings"]):
            raise CommandError(
                "Admin smoke check failed: "
                f"{summary['failed']} failed, {summary['warnings']} warning(s)."
            )

    def admin_user(self, username):
        user_model = get_user_model()
        queryset = user_model.objects.filter(is_active=True, is_staff=True, is_superuser=True).order_by("pk")
        if username:
            return queryset.get(username=username)
        user = queryset.first()
        if not user:
            raise CommandError("No active superuser exists for admin smoke check.")
        return user

    def admin_urls(self):
        yield ("Admin index", reverse("admin:index"))
        for model, model_admin in sorted(
            admin.site._registry.items(),
            key=lambda item: (item[0]._meta.app_label, item[0]._meta.model_name),
        ):
            opts = model._meta
            url_name = f"admin:{opts.app_label}_{opts.model_name}_changelist"
            try:
                yield (f"{opts.app_label}.{opts.model_name}", reverse(url_name))
            except NoReverseMatch:
                continue
        for url_name in CUSTOM_ADMIN_URL_NAMES:
            try:
                yield (url_name, reverse(url_name))
            except NoReverseMatch:
                continue

    def print_report(self, report):
        summary = report["summary"]
        self.stdout.write(f"Admin smoke check as {report['user']}")
        self.stdout.write(
            f"  passed/warn/failed/total: "
            f"{summary['passed']}/{summary['warnings']}/{summary['failed']}/{summary['total']}"
        )
        for check in report["checks"]:
            if check["status"] != "pass":
                self.stdout.write(f"- [{check['status']}] {check['label']} {check['status_code']} {check['url']}")
