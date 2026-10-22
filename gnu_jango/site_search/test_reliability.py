from io import StringIO
import json
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.db import DatabaseError, transaction
from django.test import SimpleTestCase, override_settings

from gnu_jango.config import config
from gnu_jango.config.models import Config
from gnu_jango.core.models import ContentPage
from gnu_jango.core.test_board_api_more import BoardApiTestCase
from gnu_jango.shop.models import ShopProduct
from gnu_jango.site_search.models import SearchDocument, SearchIndexRetry
from gnu_jango.users import point_ledger


class SearchReliabilityTests(BoardApiTestCase):
    def setUp(self):
        self.tokenizer = mock.patch("gnu_jango.docs_search.tokenizer._get_kiwi", return_value=None)
        self.tokenizer.start()
        self.addCleanup(self.tokenizer.stop)
        cache.clear()
        config.clear()
        self.addCleanup(config.clear)

    def rebuild(self):
        call_command("rebuild_search_index", stdout=StringIO())

    def test_literal_mixed_disabled_and_unready_paths_hide_protected_body(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        paid = self.make_board("reliable-paid", bo_read_point=-5)
        secret = self.make_post(self.board, self.owner, wr_subject="공개 제목", wr_content="secretcanary", wr_option="secret")
        paid_post = self.make_post(paid, self.owner, wr_subject="공개 제목", wr_content="paidcanary", legacy_wr_id=800001)
        restricted = self.make_board("reliable-level", bo_list_level=1, bo_read_level=9)
        hidden = self.make_post(restricted, self.owner, wr_subject="공개 제목", wr_content="levelcanary")
        for prepared in (False, True):
            if prepared:
                self.rebuild()
            for enabled in (False, True):
                with override_settings(G5_SEARCH_ENABLED=enabled):
                    for board, post, word in ((self.board, secret, "secretcanary"), (paid, paid_post, "paidcanary"), (restricted, hidden, "levelcanary")):
                        for user in (None, self.other):
                            for fields in ("wr_content", "wr_content||wr_name", "wr_content||ca_name", "unknown"):
                                with self.subTest(prepared=prepared, enabled=enabled, user=bool(user), fields=fields, word=word):
                                    response = self.api(user).get(f"/api/v1/boards/{board.bo_table}/posts", {"stx": word, "sfl": fields})
                                    self.assertEqual(response.status_code, 200)
                                    self.assertEqual(response.json()["data"], [])
        owner = self.api(self.owner).get(f"/api/v1/boards/{paid.bo_table}/posts", {"stx": "paidcanary", "sfl": "wr_content||wr_name"})
        self.assertEqual(len(owner.json()["data"]), 1)
        secret.wr_content = "숨김배나무단서"
        secret.save(update_fields=["wr_content"])
        for selected in ("wr_content", "wr_content||wr_name"):
            own = self.api(self.owner).get(f"/api/v1/boards/{self.board.bo_table}/posts", {"stx": "숨김배나무단서", "sfl": selected})
            self.assertEqual(len(own.json()["data"]), 1)
            hidden_response = self.api(self.other).get(f"/api/v1/boards/{self.board.bo_table}/posts", {"stx": "숨김배나무단서", "sfl": selected})
            self.assertEqual(hidden_response.json()["data"], [])
        point_ledger.insert_point(self.other, 100, "seed", "@reliable", 0, "seed")
        point_ledger.insert_point(self.other, -5, "read", paid.bo_table, 800001, "읽기")
        paid_response = self.api(self.other).get(f"/api/v1/boards/{paid.bo_table}/posts", {"stx": "paidcanary"})
        self.assertEqual(len(paid_response.json()["data"]), 1)

    def test_partial_ascii_codes_and_single_hangul_keep_literal_contract(self):
        post = self.make_post(self.board, wr_subject="GnuJango 꽃병", wr_content="public text")
        product = ShopProduct.objects.create(it_id="SUPER-SKU-12345", it_name="꽃병 GnuJango")
        self.rebuild()
        for query in ("Jango", "꽃"):
            rows = self.api().get(f"/api/v1/boards/{self.board.bo_table}/posts", {"stx": query}).json()["data"]
            self.assertIn(str(post.pk), {str(row["wr_id"]) for row in rows})
        for query in ("SKU-123", "Jango", "꽃"):
            rows = self.api().get("/api/v1/shop/products", {"q": query}).json()["data"]
            self.assertIn(product.pk, {row["it_id"] for row in rows})

    def test_unified_ascii_prefix_has_a_positive_score_on_active_and_bootstrap_paths(self):
        product = ShopProduct.objects.create(it_id="SKU-12345", it_name="GnuJango Desk")
        for prepared in (False, True):
            if prepared:
                self.rebuild()
            for query in ("sku-123", "gnujan"):
                from gnu_jango.site_search.service import ranked_results
                from types import SimpleNamespace
                rows, _ = ranked_results(SimpleNamespace(user=None, session={}), query, result_type="product")
                self.assertIn(product.pk, {row["id"] for row in rows})
                self.assertTrue(all(row["score"] > 0 for row in rows))

    def test_failed_index_write_keeps_source_and_durable_retry_then_repairs(self):
        page = ContentPage.objects.create(co_id="retry", co_subject="Before", co_content="before")
        with mock.patch("gnu_jango.site_search.indexing._write_postings", side_effect=DatabaseError("private exception text")):
            with self.assertLogs("gnu_jango.site_search.signals", "ERROR") as captured:
                page.co_content = "aftercanary"
                page.save(update_fields=["co_content"])
        self.assertNotIn("private exception text", " ".join(captured.output))
        page.refresh_from_db()
        self.assertEqual(page.co_content, "aftercanary")
        work = SearchIndexRetry.objects.get(kind="page", source_id=page.pk)
        self.assertEqual(work.error_type, "DatabaseError")
        call_command("retry_search_index", stdout=StringIO())
        self.assertTrue(SearchIndexRetry.objects.filter(pk=work.pk).exists())
        call_command("retry_search_index", apply=True, stdout=StringIO())
        self.assertFalse(SearchIndexRetry.objects.filter(pk=work.pk).exists())
        self.assertIn("aftercanary".encode().hex(), SearchDocument.objects.get(page=page).body_tokens)

    def test_queue_failure_rolls_back_source_and_outer_rollback_removes_retry(self):
        page = ContentPage.objects.create(co_id="atomic", co_content="before")
        with mock.patch("gnu_jango.site_search.signals.index_instance", side_effect=RuntimeError("index")):
            with mock.patch("gnu_jango.site_search.signals.SearchIndexRetry.objects.using") as manager:
                manager.return_value.update_or_create.side_effect = RuntimeError("queue")
                page.co_content = "after"
                with self.assertRaises(RuntimeError):
                    page.save(update_fields=["co_content"])
        page.refresh_from_db()
        self.assertEqual(page.co_content, "before")
        with self.assertLogs("gnu_jango.site_search.signals", "ERROR"), transaction.atomic():
            with mock.patch("gnu_jango.site_search.signals.index_instance", side_effect=RuntimeError("index")):
                page.co_content = "rolledback"
                page.save(update_fields=["co_content"])
            transaction.set_rollback(True)
        self.assertFalse(SearchIndexRetry.objects.exists())

    def test_bulk_drift_audit_pagination_and_health_detect_and_repair(self):
        ContentPage.objects.create(co_id="audit-a", co_subject="Alpha")
        ContentPage.objects.create(co_id="audit-b", co_subject="Beta")
        self.rebuild()
        ContentPage.objects.filter(pk="audit-b").update(co_subject="Changed")
        output = StringIO()
        call_command("audit_search_index", kind="page", limit=1, stdout=output)
        self.assertTrue(json.loads(output.getvalue())["has_more"])
        with self.assertRaises(CommandError):
            call_command("audit_search_index", kind="page", after="audit-a", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("check_search_health", stdout=StringIO())
        call_command("audit_search_index", kind="page", enqueue=True, stdout=StringIO())
        call_command("retry_search_index", apply=True, stdout=StringIO())
        call_command("check_search_health", stdout=StringIO())

    def test_retry_failure_has_backoff_and_source_delete_cleans_retry(self):
        product = ShopProduct.objects.create(it_id="retry-product", it_name="Retry")
        work = SearchIndexRetry.objects.create(kind="product", source_id=product.pk)
        with mock.patch("gnu_jango.site_search.management.commands.retry_search_index.index_instance", side_effect=RuntimeError("private")):
            with self.assertRaises(CommandError):
                call_command("retry_search_index", apply=True, stdout=StringIO())
        work.refresh_from_db()
        self.assertEqual(work.attempts, 1)
        self.assertEqual(work.error_type, "RuntimeError")
        product.delete()
        self.assertFalse(SearchIndexRetry.objects.exists())

    def test_request_metrics_omit_query_text_and_supply_private_timing(self):
        self.rebuild()
        with self.assertLogs("gnu_jango.site_search.requests", "INFO") as logs:
            response = self.api().get("/api/v1/search/unified", {"q": "privatequerycanary"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("search;dur=", response["Server-Timing"])
        self.assertIn("private", response["Cache-Control"])
        self.assertNotIn("privatequerycanary", " ".join(logs.output))
        with mock.patch("gnu_jango.api.v1_search.ranked_results", side_effect=RuntimeError("privatebodycanary")):
            with self.assertLogs("gnu_jango.site_search.requests", "ERROR") as logs:
                with self.assertRaises(RuntimeError):
                    self.api().get("/api/v1/search/unified", {"q": "privatequerycanary"})
        self.assertNotIn("privatebodycanary", " ".join(logs.output))

    def test_health_rotates_audit_cursor_and_detects_missing_source_documents(self):
        for name in ("rotate-a", "rotate-b", "rotate-c"):
            ContentPage.objects.create(co_id=name, co_subject="Original")
        self.rebuild()
        ContentPage.objects.filter(pk="rotate-c").update(co_subject="Changed")
        call_command("check_search_health", audit_limit=1, stdout=StringIO())
        call_command("check_search_health", audit_limit=1, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("check_search_health", audit_limit=1, stdout=StringIO())
        ContentPage.objects.bulk_create([ContentPage(co_id="missing-index")])
        from gnu_jango.site_search.maintenance import index_health
        self.assertGreater(index_health()["source_count_difference"], 0)
        self.assertFalse(index_health()["ready"])

    def test_postgres_sparse_stats_preserve_prefix_frequencies_and_lengths(self):
        from collections import Counter
        from django.db import connection
        from types import SimpleNamespace
        from gnu_jango.site_search.indexing import encoded, terms
        from gnu_jango.site_search.service import _postgres_scoring_fields, matching_documents, visible_documents
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL scoring projection")
        product = ShopProduct.objects.create(it_id="SKU-12345", it_name="Sky Sky Desk", it_basic="sky sky sky sku-12345")
        self.rebuild()
        docs, body = visible_documents(SimpleNamespace(user=None, session={}), result_type="product")
        query_terms = terms("sk sku-12", 24)
        row = _postgres_scoring_fields(matching_documents(docs, "sk sku-12", allowed_body=body), query_terms).only("pk", "product_id").get(product=product)
        self.assertIn("body_tokens", row.get_deferred_fields())
        stored = SearchDocument.objects.get(product=product)
        for field in ("title", "body"):
            tokens = getattr(stored, f"{field}_tokens").split()
            frequency = Counter(tokens)
            expected = {encoded(term): sum(n for token, n in frequency.items() if token.startswith(encoded(term))) for term in query_terms}
            self.assertEqual(getattr(row, f"_search_{field}_stats"), expected)
            self.assertEqual(getattr(row, f"_search_{field}_length"), len(tokens))
            self.assertFalse(hasattr(row, f"_search_{field}_tokens"))
        from gnu_jango.site_search.service import ranked_results
        current, _ = ranked_results(SimpleNamespace(user=None, session={}), "sk sku-12", result_type="product")
        with mock.patch.object(connection, "pg_version", 140000):
            compatible, _ = ranked_results(SimpleNamespace(user=None, session={}), "sk sku-12", result_type="product")
        self.assertEqual([(r["id"], r["score"]) for r in current], [(r["id"], r["score"]) for r in compatible])

    def test_source_save_reuses_the_resolved_write_database(self):
        page = ContentPage(co_id="routed-save", co_subject="Routed")
        with mock.patch("gnu_jango.site_search.source.router.db_for_write", return_value="default") as route:
            page.save()
        self.assertEqual(sum(call.args[0] is ContentPage for call in route.call_args_list), 1)
        self.assertTrue(SearchDocument.objects.filter(page=page).exists())

    def test_retry_processes_oldest_due_work_before_a_lower_primary_key(self):
        from datetime import timedelta
        from django.utils import timezone
        ContentPage.objects.create(co_id="recent-retry")
        ContentPage.objects.create(co_id="overdue-retry")
        recent = SearchIndexRetry.objects.create(kind="page", source_id="recent-retry", available_at=timezone.now() - timedelta(minutes=1))
        overdue = SearchIndexRetry.objects.create(kind="page", source_id="overdue-retry", available_at=timezone.now() - timedelta(days=1))
        call_command("retry_search_index", apply=True, limit=1, stdout=StringIO())
        self.assertTrue(SearchIndexRetry.objects.filter(pk=recent.pk).exists())
        self.assertFalse(SearchIndexRetry.objects.filter(pk=overdue.pk).exists())


class SearchReleaseWaitTests(SimpleTestCase):
    def wait(self, payload):
        from contextlib import redirect_stdout
        from scripts.wait_search_release import main
        with mock.patch("sys.argv", ["wait", "--revision", "a" * 40, "--attempts", "1"]):
            with mock.patch("scripts.wait_search_release.urlopen") as fetch, redirect_stdout(StringIO()):
                fetch.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
                return main()

    def test_accepts_matching_revision(self):
        self.assertEqual(self.wait({"data": {"deployment_revision": "a" * 40}}), 0)

    def test_rejects_older_revision_and_malformed_response(self):
        self.assertEqual(self.wait({"data": {"deployment_revision": "b" * 40}}), 1)
        self.assertEqual(self.wait(["unexpected"]), 1)
