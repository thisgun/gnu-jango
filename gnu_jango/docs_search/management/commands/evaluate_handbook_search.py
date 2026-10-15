from statistics import median
from time import perf_counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from gnu_jango.docs_search.evaluation import EVALUATION_CASES
from gnu_jango.docs_search.service import docs_group_id


class Command(BaseCommand):
    help = "Measure the handbook question-search quality set and warm-query latency."

    def add_arguments(self, parser):
        parser.add_argument("--no-threshold", action="store_true", help="Report scores without enforcing hit@3 >= 80%%.")

    def handle(self, *args, **options):
        group_id = docs_group_id()
        if not group_id:
            raise CommandError("cf_docs_group is empty. Select a manual group before evaluating search.")

        settings_override = {
            "REST_FRAMEWORK": {
                **settings.REST_FRAMEWORK,
                "DEFAULT_THROTTLE_RATES": {
                    **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                    "docs-ask": "1000/min",
                },
            }
        }
        client = Client()
        hit_at_1 = 0
        hit_at_3 = 0
        elapsed = []
        rows = []
        with override_settings(**settings_override):
            for query, expected_table, expected_chapter in EVALUATION_CASES:
                started = perf_counter()
                response = client.get("/api/v1/docs/ask", {"q": query, "limit": 3})
                elapsed.append((perf_counter() - started) * 1000)
                if response.status_code != 200:
                    raise CommandError(f"Question API returned {response.status_code} for: {query}")
                results = response.json().get("data", {}).get("results", [])
                expected = (expected_table, expected_chapter)
                actual = [(item["bo_table"], item["chapter"]) for item in results]
                one = bool(actual and actual[0] == expected)
                three = expected in actual
                hit_at_1 += one
                hit_at_3 += three
                rows.append((query, expected_chapter, actual[0][1] if actual else "(없음)", "O" if one else "", "O" if three else ""))

        self.stdout.write("질문 | 정답 장 | 1위 결과 | hit@1 | hit@3")
        for row in rows:
            self.stdout.write(" | ".join(row))
        denominator = len(EVALUATION_CASES)
        self.stdout.write(f"hit@1: {hit_at_1}/{denominator} ({hit_at_1 / denominator:.1%})")
        self.stdout.write(f"hit@3: {hit_at_3}/{denominator} ({hit_at_3 / denominator:.1%})")
        self.stdout.write(f"첫 질문: {elapsed[0]:.1f} ms; 이후 질문 중앙값: {median(elapsed[1:]):.1f} ms")
        if hit_at_3 / denominator < 0.8 and not options["no_threshold"]:
            raise CommandError("Sample handbook search did not reach the required 80% hit@3.")
