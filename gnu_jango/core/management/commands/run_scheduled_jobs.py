import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.core import scheduled_jobs


class Command(BaseCommand):
    help = (
        "Run the periodic maintenance jobs (pending payment/e-mail expiry, Toss virtual account expiry, "
        "admin privacy cleanup) with --apply. Each job is isolated; exits non-zero if any failed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what each job would do without applying.")
        parser.add_argument(
            "--job",
            action="append",
            default=[],
            choices=scheduled_jobs.JOB_NAMES,
            help="Run only this job (repeatable). Default: all jobs.",
        )
        parser.add_argument("--json", action="store_true", help="Print the machine-readable report.")

    def handle(self, *args, **options):
        report = scheduled_jobs.run_scheduled_jobs(
            dry_run=bool(options["dry_run"]),
            jobs=scheduled_jobs.select_jobs(options["job"]),
        )

        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.print_report(report)

        if report["failed"]:
            raise CommandError(f"{report['failed']} scheduled job(s) failed.")

    def print_report(self, report):
        mode = "dry-run" if report["dry_run"] else "apply"
        if report["skipped"]:
            self.stdout.write(f"Scheduled jobs ({mode}): skipped -- {report['reason']}")
            return
        self.stdout.write(f"Scheduled jobs ({mode}):")
        for job in report["jobs"]:
            line = f"  {job['name']}: {job['status']} ({job['duration_ms']} ms)"
            if job["error"]:
                line += f" -- {job['error']}"
            elif job["summary"]:
                summary = job["summary"]
                if isinstance(summary, dict):
                    summary = " ".join(f"{key}={value}" for key, value in summary.items())
                line += f" -- {summary}"
            self.stdout.write(line)
        self.stdout.write(f"  {report['succeeded']} ok, {report['failed']} failed")
