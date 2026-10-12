import io
import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.core.deploy_profile import evaluate_deploy_profile
from gnu_jango.core.management.commands.check_deploy_profile import deploy_env


class Command(BaseCommand):
    help = "Run a combined Django/Next/Gnuboard5 production-readiness gate."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary.")
        parser.add_argument(
            "--strict-production",
            action="store_true",
            help="Fail when production-only gates such as live provider credentials, Vercel HTTPS env, or unserved assets are incomplete.",
        )
        parser.add_argument("--skip-next", action="store_true", help="Skip Next.js npm checks.")
        parser.add_argument(
            "--include-build",
            action="store_true",
            help="Run npm run build:theme instead of the faster check:theme-sync.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=3,
            help="Sample size passed to asset audits.",
        )

    def handle(self, *args, **options):
        strict = bool(options["strict_production"])
        checks = []

        checks.append(self.check_django_system())
        checks.append(self.check_assets(options["sample_size"], strict))
        checks.append(self.check_legacy_data_quality(options["sample_size"], strict))
        checks.append(self.check_external_integrations(strict))
        deploy_check = self.check_deploy_profile(strict)
        if deploy_check is not None:
            checks.append(deploy_check)

        if options["skip_next"]:
            checks.append(
                self.result(
                    "nextjs",
                    "Next.js release checks",
                    "skipped",
                    "Skipped by --skip-next.",
                )
            )
        else:
            checks.extend(self.check_nextjs(strict=strict, include_build=bool(options["include_build"])))

        summary = self.summarize(checks, strict)
        report = {
            "strict_production": strict,
            "summary": summary,
            "checks": checks,
        }

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.print_report(report)

        if summary["failed"] > 0:
            raise CommandError(
                f"Release readiness failed: {summary['failed']} failed, "
                f"{summary['warnings']} warning(s), {summary['passed']} passed."
            )

    def check_django_system(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            call_command("check", stdout=stdout, stderr=stderr)
        except Exception as exc:
            return self.result(
                "django_check",
                "Django system check",
                "fail",
                str(exc),
                output=self.tail(stderr.getvalue() or stdout.getvalue()),
            )

        return self.result(
            "django_check",
            "Django system check",
            "pass",
            "Django system check passed.",
            output=self.tail(stdout.getvalue()),
        )

    def check_assets(self, sample_size, strict):
        stdout = io.StringIO()
        try:
            call_command("audit_gnuboard_assets", json=True, sample_size=sample_size, stdout=stdout)
            audit = json.loads(stdout.getvalue())
        except Exception as exc:
            return self.result(
                "gnuboard_assets",
                "Gnuboard5 asset servability",
                "fail",
                str(exc),
                output=self.tail(stdout.getvalue()),
            )

        board = audit["board_files"]
        products = audit["product_images"]
        served_missing = board["served_missing"] + products["served_missing"]
        source_missing = board["source_missing"] + products["source_missing"]
        served_present = board["served_present"] + products["served_present"]
        status = "fail" if strict and served_missing else "warn" if served_missing else "pass"
        details = (
            f"served_present={served_present}, served_missing={served_missing}, "
            f"source_missing={source_missing}"
        )
        action = ""
        if served_missing:
            action = (
                "Restore original data/file and data/item assets, run sync_gnuboard_assets --apply, "
                "then require audit_gnuboard_assets --fail-on-unserved to pass."
            )
        return self.result(
            "gnuboard_assets",
            "Gnuboard5 asset servability",
            status,
            details,
            action=action,
            data={
                "source_roots": audit["source_roots"],
                "board_served_present": board["served_present"],
                "board_served_missing": board["served_missing"],
                "product_served_present": products["served_present"],
                "product_served_missing": products["served_missing"],
                "source_missing": source_missing,
            },
        )

    def check_legacy_data_quality(self, sample_size, strict):
        stdout = io.StringIO()
        try:
            call_command("audit_legacy_data_quality", json=True, sample_size=sample_size, stdout=stdout)
            audit = json.loads(stdout.getvalue())
        except Exception as exc:
            return self.result(
                "legacy_data_quality",
                "Legacy data quality",
                "fail",
                str(exc),
                output=self.tail(stdout.getvalue()),
            )

        issues = int(audit["summary"]["issues"])
        status = "pass" if issues == 0 else "fail" if strict else "warn"
        action = ""
        if issues:
            action = (
                "Review sample rows from audit_legacy_data_quality, repair mojibake values, "
                "and fill missing critical order/product/member fields."
            )
        return self.result(
            "legacy_data_quality",
            "Legacy data quality",
            status,
            f"issues={issues}, models_checked={audit['summary']['models_checked']}",
            action=action,
            data=audit,
        )

    def check_external_integrations(self, strict):
        stdout = io.StringIO()
        try:
            call_command("audit_external_integrations", json=True, stdout=stdout)
            audit = json.loads(stdout.getvalue())
        except Exception as exc:
            return self.result(
                "external_integrations",
                "PG/social/certification production integrations",
                "fail",
                str(exc),
                output=self.tail(stdout.getvalue()),
            )

        summary = audit["summary"]
        production_ready = bool(summary["production_ready"])
        status = "pass" if production_ready else "fail" if strict else "warn"
        details = (
            f"production_ready={str(production_ready).lower()}, "
            f"missing_settings={summary['missing_settings']}, disabled={summary['disabled']}, "
            f"blocked={summary['blocked']}"
        )
        action = ""
        if not production_ready:
            action = (
                "Set live PG/OAuth/certification credentials and implement or delegate provider-authoritative "
                "signature/decrypt/reconciliation flows."
            )
        return self.result(
            "external_integrations",
            "PG/social/certification production integrations",
            status,
            details,
            action=action,
            data=summary,
        )

    def check_deploy_profile(self, strict):
        """Gate on DEPLOY_PROFILE (vps|vercel|split) when it is set; see check_deploy_profile."""
        env = deploy_env()
        profile = str(env.get("DEPLOY_PROFILE", "") or "").strip().lower()
        if not profile:
            return None
        try:
            report = evaluate_deploy_profile(profile, settings_obj=settings, env=env)
        except ValueError as exc:
            return self.result("deploy_profile", "Deploy profile", "fail", str(exc))

        summary = report["summary"]
        status = "fail" if summary["failed"] else "pass" if not summary["warnings"] else "fail" if strict else "warn"
        not_passed = [check for check in report["checks"] if check["status"] != "pass"]
        return self.result(
            "deploy_profile",
            f"Deploy profile ({profile})",
            status,
            f"passed={summary['passed']}, warnings={summary['warnings']}, failed={summary['failed']}",
            action="; ".join(f"{check['label']}: {check['action']}" for check in not_passed if check["action"]),
            data=report,
        )

    def check_nextjs(self, *, strict, include_build):
        if not self.nextjs_root.exists():
            return [
                self.result(
                    "nextjs_root",
                    "Next.js project directory",
                    "fail",
                    f"Missing Next.js project: {self.nextjs_root}",
                )
            ]

        checks = []
        checks.append(self.run_npm("check:vercel-env" if strict else "check:vercel-env:template"))
        checks.append(self.run_npm("build:theme" if include_build else "check:theme-sync"))
        return checks

    @property
    def nextjs_root(self):
        return Path(settings.BASE_DIR) / "nextjs"

    def run_npm(self, script):
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
        result = subprocess.run(
            [npm, "run", script],
            cwd=self.nextjs_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return self.result(
            f"nextjs_{script.replace(':', '_')}",
            f"npm run {script}",
            "pass" if result.returncode == 0 else "fail",
            f"exit={result.returncode}",
            output=self.tail(output),
        )

    def result(self, name, label, status, details="", *, action="", data=None, output=""):
        return {
            "name": name,
            "label": label,
            "status": status,
            "details": details,
            "action": action,
            "data": data or {},
            "output": output,
        }

    def summarize(self, checks, strict):
        passed = sum(1 for check in checks if check["status"] == "pass")
        warnings = sum(1 for check in checks if check["status"] == "warn")
        skipped = sum(1 for check in checks if check["status"] == "skipped")
        failed = sum(1 for check in checks if check["status"] == "fail")
        return {
            "production_ready": failed == 0 and (strict or warnings == 0),
            "strict_gate": strict,
            "passed": passed,
            "warnings": warnings,
            "skipped": skipped,
            "failed": failed,
        }

    def print_report(self, report):
        summary = report["summary"]
        self.stdout.write("Release readiness")
        self.stdout.write(f"  strict production: {'yes' if report['strict_production'] else 'no'}")
        self.stdout.write(f"  production ready: {'yes' if summary['production_ready'] else 'no'}")
        self.stdout.write(
            f"  passed/warn/skipped/failed: "
            f"{summary['passed']}/{summary['warnings']}/{summary['skipped']}/{summary['failed']}"
        )
        self.stdout.write("")
        for check in report["checks"]:
            self.stdout.write(f"- [{check['status']}] {check['label']}: {check['details']}")
            if check.get("action") and check["status"] != "pass":
                self.stdout.write(f"  action: {check['action']}")
            if check.get("output") and check["status"] == "fail":
                self.stdout.write("  output:")
                for line in check["output"].splitlines():
                    self.stdout.write(f"    {line}")

    def tail(self, value, max_lines=12):
        lines = [line.rstrip() for line in str(value or "").splitlines() if line.strip()]
        return "\n".join(lines[-max_lines:])
