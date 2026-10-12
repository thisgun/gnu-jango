import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gnu_jango.core.deploy_profile import PROFILES, evaluate_deploy_profile


def deploy_env():
    """Environment first, then .env (python-decouple), like the settings modules read it."""
    return getattr(settings, "DEPLOY_ENV", None) or os.environ


class Command(BaseCommand):
    help = "Check the current settings against a deployment profile (DEPLOY_PROFILE=vps|vercel|split)."

    def add_arguments(self, parser):
        parser.add_argument("--profile", choices=PROFILES, help="Profile to check. Default: $DEPLOY_PROFILE.")
        parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
        parser.add_argument("--json", action="store_true", help="Print the machine-readable report.")

    def handle(self, *args, **options):
        env = deploy_env()
        profile = options["profile"] or str(env.get("DEPLOY_PROFILE", "") or "").strip().lower()
        if not profile:
            raise CommandError(f"Pass --profile or set DEPLOY_PROFILE ({'|'.join(PROFILES)}).")
        try:
            report = evaluate_deploy_profile(profile, settings_obj=settings, env=env)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            summary = report["summary"]
            self.stdout.write(
                f"Deploy profile '{report['profile']}': "
                f"{summary['passed']} passed, {summary['warnings']} warning(s), {summary['failed']} failed"
            )
            for check in report["checks"]:
                self.stdout.write(f"- [{check['status']}] {check['label']}: {check['details']}")
                if check["action"] and check["status"] != "pass":
                    self.stdout.write(f"  action: {check['action']}")

        summary = report["summary"]
        if summary["failed"] or (options["strict"] and summary["warnings"]):
            raise CommandError(
                f"Deploy profile '{report['profile']}' failed: "
                f"{summary['failed']} failed, {summary['warnings']} warning(s)."
            )
