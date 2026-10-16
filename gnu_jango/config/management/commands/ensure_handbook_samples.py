import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.config import handbook_samples


class Command(BaseCommand):
    help = "Create the sample manual for the handbook theme (group manual, boards hb_*), or remove it with --remove."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Delete the sample manual and clear cf_docs_group.")
        parser.add_argument(
            "--stable-dates",
            action="store_true",
            help="Use a fixed post timestamp so generated exports are reproducible.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Also rewrite the body of every chapter whose title is a sample chapter title, to pick up "
            "corrected sample text. Edits made to those chapters are overwritten; other chapters are kept.",
        )

    def handle(self, *args, **options):
        try:
            if options["remove"]:
                result = {"removed": handbook_samples.remove_samples()}
            else:
                result = handbook_samples.ensure_samples(
                    stable_dates=options["stable_dates"], refresh=options["refresh"]
                )
        except handbook_samples.HandbookSampleError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
