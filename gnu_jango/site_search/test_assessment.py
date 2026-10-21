"""Anonymous/member/admin search access and reproducible assessment utilities."""
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core.test_board_api_more import BoardApiTestCase
from scripts.assess_search import expected_rank, latency_summary, run

from . import service
from .indexing import index_instance
from .models import SearchIndexState


@override_settings(G5_SEARCH_ENABLED=True, G5_SEARCH_TRIGRAM=False, CACHES={
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
})
class SearchPermissionMatrixTests(BoardApiTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokenizer_patch = mock.patch("gnu_jango.docs_search.tokenizer._get_kiwi", return_value=None)
        cls.tokenizer_patch.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tokenizer_patch.stop()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        site_config.clear()
        cls.public_board = cls.make_board("matrix-public")
        cls.member_board = cls.make_board("matrix-member", bo_list_level=2, bo_read_level=2)
        cls.high_board = cls.make_board("matrix-high", bo_list_level=9, bo_read_level=9)
        cls.paid_board = cls.make_board("matrix-paid", bo_read_point=-5)
        closed = cls.make_board("matrix-closed", bo_use_search=False)
        cls.public_post = cls.make_post(cls.public_board, cls.owner, wr_subject="공개검색표제", wr_content="publicbodycanary")
        cls.member_post = cls.make_post(cls.member_board, cls.owner, wr_subject="회원검색표제", wr_content="회원본문단서")
        cls.high_post = cls.make_post(cls.high_board, cls.owner, wr_subject="고급검색표제", wr_content="고급본문단서")
        cls.secret_post = cls.make_post(cls.public_board, cls.owner, wr_subject="비밀검색표제",
                                        wr_content="secretbodycanary", wr_option="secret")
        cls.paid_post = cls.make_post(cls.paid_board, cls.owner, wr_subject="유료검색표제", wr_content="paidbodycanary")
        cls.make_post(closed, cls.owner, wr_subject="중지검색표제", wr_content="중지본문기밀")
        call_command("rebuild_search_index", stdout=StringIO())

    def setUp(self):
        cache.clear()
        site_config.clear()

    def tearDown(self):
        site_config.clear()

    def search(self, query, user=None, **params):
        response = self.api(user).get("/api/v1/search/unified", {"q": query, **params}, HTTP_DNT="1")
        self.assertEqual(response.status_code, 200, response.content[:1000])
        return response.json()

    def test_title_visibility_matrix_including_total_counts(self):
        cases = [
            (None, [self.public_post, self.paid_post]),
            (self.other, [self.public_post, self.paid_post, self.member_post]),
            (self.owner, [self.public_post, self.paid_post, self.member_post, self.secret_post]),
            (self.boss, [self.public_post, self.paid_post, self.member_post, self.secret_post, self.high_post]),
        ]
        # List-level restrictions still apply to an author on a restricted board.
        for user, expected in cases:
            with self.subTest(role=getattr(user, "username", "anonymous")):
                data = self.search("검색표제", user)
                self.assertEqual({r["id"] for r in data["data"]["results"]}, {str(p.pk) for p in expected})
                self.assertEqual(data["meta"]["total"], len(expected))

    def test_secret_body_never_matches_even_for_author_or_admin(self):
        for user in (None, self.other, self.owner, self.boss):
            with self.subTest(role=getattr(user, "username", "anonymous")):
                data = self.search("secretbodycanary", user)
                self.assertNotIn(str(self.secret_post.pk), [r["id"] for r in data["data"]["results"]])
                title = self.search("비밀검색표제", user)["data"]["results"]
                self.assertTrue(all(r["snippet"] == "" for r in title if r["id"] == str(self.secret_post.pk)))

    def test_paid_body_is_hidden_from_anonymous_and_unpaid_member(self):
        for user in (None, self.other):
            with self.subTest(role=getattr(user, "username", "anonymous")):
                rows = self.search("paidbodycanary", user)["data"]["results"]
                self.assertNotIn(str(self.paid_post.pk), [r["id"] for r in rows])
                rows = self.search("유료검색표제", user)["data"]["results"]
                row = next(r for r in rows if r["id"] == str(self.paid_post.pk))
                self.assertEqual(row["snippet"], "")

    def test_access_revocation_after_ranking_is_rechecked(self):
        original = service.hydrate_results
        def revoke(request, ranked, query, query_terms):
            type(self.public_board).objects.filter(pk=self.public_board.pk).update(bo_read_level=9)
            return original(request, ranked, query, query_terms)
        with mock.patch.object(service, "hydrate_results", side_effect=revoke):
            self.assertEqual(self.search("publicbodycanary")["data"]["results"], [])

    def test_only_the_selected_page_projects_source_bodies(self):
        for index in range(8):
            self.make_post(self.public_board, wr_subject=f"예산검색 대상 {index}", wr_content="x" * 10000)
        request = SimpleNamespace(user=None, session={})
        with CaptureQueriesContext(connection) as queries:
            rows, meta = service.ranked_results(request, "예산검색", page=2, limit=2)
        source_queries = [q["sql"] for q in queries if '"wr_content"' in q["sql"]]
        self.assertEqual(len(rows), 2)
        self.assertEqual(meta["current_page"], 2)
        self.assertEqual(len(source_queries), 1)
        self.assertIn("SUBSTR", source_queries[0].upper())

    def test_staged_tokens_do_not_match_until_the_generation_is_active(self):
        generation = "b" * 32
        SearchIndexState.objects.filter(kind="post").update(building_generation=generation)
        type(self.public_post).objects.filter(pk=self.public_post.pk).update(wr_subject="pendingcanary")
        index_instance(self.public_post, "post", build_generation=generation)
        before = self.search("pendingcanary")
        self.assertEqual(before["data"]["results"], [])
        self.assertEqual(before["meta"]["total"], 0)
        SearchIndexState.objects.filter(kind="post").update(active_generation=generation, building_generation="")
        after = self.search("pendingcanary")
        self.assertEqual([r["id"] for r in after["data"]["results"]], [str(self.public_post.pk)])

    def test_partial_generation_upgrade_keeps_permission_aware_legacy_search(self):
        SearchIndexState.objects.filter(kind="post").update(active_generation="", building_generation="")
        public = self.search("publicbodycanary")
        self.assertEqual([r["id"] for r in public["data"]["results"]], [str(self.public_post.pk)])
        self.assertNotIn(str(self.paid_post.pk), [r["id"] for r in self.search("paidbodycanary")["data"]["results"]])

    def test_long_body_does_not_dilute_a_matching_title(self):
        chapter = self.make_post(self.public_board, wr_subject="게시판 만들기", wr_content="예시를 설명합니다. " * 300)
        glossary = self.make_post(self.public_board, wr_subject="용어 사전", wr_content="게시판 " * 15)
        ids = [r["id"] for r in self.search("게시판")["data"]["results"]]
        self.assertLess(ids.index(str(chapter.pk)), ids.index(str(glossary.pk)))


class AssessmentUtilityTests(SimpleTestCase):
    def test_expected_rank_checks_type_title_and_board(self):
        rows = [{"type": "post", "title": "same", "bo_table": "other"},
                {"type": "document", "title": "same", "bo_table": "manual"}]
        self.assertEqual(expected_rank(rows, [{"type": "document", "title": "same", "bo_table": "manual"}]), 2)
        self.assertIsNone(expected_rank(rows, [{"title": "missing"}]))

    def test_nearest_rank_p95_and_empty_samples(self):
        self.assertEqual(latency_summary(range(1, 21))["p95_ms"], 19)
        self.assertIsNone(latency_summary([])["p95_ms"])

    def test_errors_are_not_counted_as_hits_or_success_latency(self):
        dataset = {"sites": {"demo": "https://example.test"}, "cases": [
            {"id": "one", "site": "demo", "category": "post", "query": "sample", "expected": [{"title": "answer"}]},
        ]}
        response = {"status": 429, "error": "http_429", "ms": 100, "connection_reused": False,
                    "region": "", "payload": {"data": {"results": [{"title": "answer"}]}}}
        with mock.patch("scripts.assess_search.Client.search", return_value=response):
            report = run(dataset, repeats=0, interval=0, timeout=1)
        self.assertEqual(report["quality"]["all"]["hits_top3"], 0)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["latency"]["demo"]["first_pass"]["count"], 0)
        self.assertFalse(report["cold_start_verified"])

    def test_unexpected_json_shape_is_reported_without_crashing(self):
        dataset = {"sites": {"demo": "https://example.test"}, "cases": [
            {"id": "one", "site": "demo", "category": "post", "query": "sample", "expected": [{"title": "answer"}]},
        ]}
        response = {"status": 200, "error": None, "ms": 10, "payload": {"data": [], "meta": None}}
        with mock.patch("scripts.assess_search.Client.search", return_value=response):
            report = run(dataset, repeats=1, interval=0, timeout=1)
        self.assertEqual(report["errors"], 2)
        self.assertEqual(report["samples"][0]["error"], "invalid_results")
