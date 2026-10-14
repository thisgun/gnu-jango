import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.config import sample_data


class Command(BaseCommand):
    help = "Inspect shop samples, or add missing samples and apply home visibility with --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply sample creation and visibility repair.")

    def handle(self, *args, **options):
        try:
            result = sample_data.ensure_shop_sample_data() if options["apply"] else {}
            status = sample_data.get_status()
        except sample_data.SampleDataError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"applied": options["apply"], **result, "shop": status["shop_status"]}, ensure_ascii=False))
