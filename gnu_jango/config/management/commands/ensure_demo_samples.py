"""Inspect, seed, or remove the small demo dataset tracked by the admin sample-data page."""

import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.config import sample_data


class Command(BaseCommand):
    help = "Inspect demo samples, add missing demo data with --apply, or remove tracked demo data with --remove."

    def add_arguments(self, parser):
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument("--apply", action="store_true", help="Add demo boards, posts, FAQ, menus and missing shop samples.")
        actions.add_argument("--remove", action="store_true", help="Remove tracked demo samples while preserving records with real activity.")

    def handle(self, *args, **options):
        try:
            if options["apply"]:
                result = sample_data.ensure_demo_sample_data()
                payload = {
                    "applied": True,
                    "created_community": result["created_community"],
                    "counts": result["counts"],
                    "shop": sample_data.get_status()["shop_status"],
                }
            elif options["remove"]:
                payload = {"removed": True, **sample_data.remove_sample_data()}
            else:
                status = sample_data.get_status()
                payload = {
                    "applied": False,
                    "has_data": status["has_data"],
                    "has_community_data": status["has_community_data"],
                    "counts": status["counts"],
                    "shop": status["shop_status"],
                }
        except sample_data.SampleDataError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
