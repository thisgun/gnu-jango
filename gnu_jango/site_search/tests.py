from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from gnu_jango.bbs.models import Group, Post
from gnu_jango.config.models import Config
from gnu_jango.config import config as site_config
from gnu_jango.core.models import ContentPage, SearchKeywordDaily
from gnu_jango.core.test_board_api_more import BoardApiTestCase
from gnu_jango.shop.models import ShopCategory, ShopProduct
from gnu_jango.users import point_ledger

from .feedback import query_hash
from .models import SearchClickDaily, SearchDocument, SearchIndexState
from .service import CANDIDATE_LIMIT

API = "/api/v1/search"


@override_settings(G5_SEARCH_ENABLED=True, G5_SEARCH_TRIGRAM=False, G5_SEARCH_CLICK_LOG_ENABLED=True)
class UnifiedSearchTests(BoardApiTestCase):
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
        cls.target = cls.make_post(cls.board, cls.owner, wr_subject="무통장 입금 확인", wr_content="입금 확인은 주문 관리에서 처리합니다.")
        cls.product = ShopProduct.objects.create(it_id="search-001", it_name="무통장 입금 안내 상품", it_basic="입금 확인", it_price=12000)
        cls.page = ContentPage.objects.create(co_id="deposit", co_subject="무통장 입금 안내", co_content="입금 확인 절차")
        docs_group = Group.objects.create(gr_id="search-manual", gr_subject="매뉴얼")
        cls.manual_board = cls.make_board("search-manual", group=docs_group)
        cls.chapter = cls.make_post(cls.manual_board, cls.owner, wr_subject="입금 확인 매뉴얼", wr_content="주문 관리에서 확인합니다.")
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": docs_group.gr_id})
        call_command("rebuild_search_index", stdout=StringIO())

    def setUp(self):
        cache.clear()
        site_config.clear()

    def tearDown(self):
        site_config.clear()

    def search(self, query="입금 확인", user=None, **params):
        response = self.api(user).get(f"{API}/unified", {"q": query, **params})
        self.assertEqual(response.status_code, 200, response.content[:1000])
        return response.json()

    def ids(self, query, user=None, **params):
        return {(row["type"], row["id"]) for row in self.search(query, user, **params)["data"]["results"]}

    def token(self, user=None):
        return next(row["click_token"] for row in self.search(user=user)["data"]["results"] if row["id"] == str(self.target.pk) and row["type"] == "post")

    def test_unified_types_korean_particles_and_price(self):
        data = self.search("입금확인은 어떻게 하나요?")["data"]["results"]
        self.assertEqual({row["type"] for row in data}, {"post", "product", "document"})
        self.assertEqual(next(row["price"] for row in data if row["type"] == "product"), 12000)
        self.assertIn(("document", str(self.chapter.pk)), self.ids("입금", type="document"))
        self.assertEqual({row[0] for row in self.ids("입금", type="product")}, {"product"})
        self.assertNotIn(("post", str(self.chapter.pk)), self.ids("입금", type="post"))

    def test_title_match_ranks_above_a_body_only_match(self):
        self.make_post(self.board, wr_subject="다른 제목", wr_content="입금 확인 " * 3)
        rows = self.search(type="post")["data"]["results"]
        self.assertEqual(rows[0]["id"], str(self.target.pk))

    def test_hidden_boards_secrets_and_disabled_sources_are_absent(self):
        restricted = self.make_board("search-restricted", bo_list_level=9, bo_read_level=9)
        disabled = self.make_board("search-off", bo_use_search=False)
        for board in (restricted, disabled):
            self.make_post(board, wr_subject="입금 확인 hidden")
        secret = self.make_post(self.board, self.owner, wr_subject="입금 확인 secret", wr_content="기밀암호단서", wr_option="secret")
        ShopProduct.objects.filter(pk=self.product.pk).update(it_use="0")
        ContentPage.objects.filter(pk=self.page.pk).update(co_use=0)
        rows = self.search()["data"]["results"]
        self.assertFalse(any("hidden" in row["title"] or "secret" in row["title"] for row in rows))
        self.assertNotIn(("product", self.product.pk), {(r["type"], r["id"]) for r in rows})
        self.assertEqual(self.ids("기밀암호단서", self.owner), set())
        self.assertIn(("post", str(secret.pk)), self.ids("입금 확인", self.owner))

    def test_category_disable_and_permission_changes_apply_without_reindex(self):
        category = ShopCategory.objects.create(ca_id="SC", ca_name="Search", ca_use=True)
        ShopProduct.objects.filter(pk=self.product.pk).update(category=category)
        category.ca_use = False
        category.save()
        self.assertNotIn(("product", self.product.pk), self.ids("입금"))
        type(self.board).objects.filter(pk=self.board.pk).update(bo_read_level=9)
        self.assertNotIn(("post", str(self.target.pk)), self.ids("입금"))

    def test_paid_body_cannot_match_or_influence_rank_for_unpaid_reader(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        type(self.board).objects.filter(pk=self.board.pk).update(bo_read_point=-5)
        post = self.make_post(self.board, self.owner, wr_subject="공개표제", wr_content="가려진본문단서", legacy_wr_id=190001)
        self.assertNotIn(("post", str(post.pk)), self.ids("가려진본문단서"))
        self.assertNotIn(("post", str(post.pk)), self.ids("가려진본문단서", self.other))
        self.assertIn(("post", str(post.pk)), self.ids("가려진본문단서", self.owner))
        self.assertIn(("post", str(post.pk)), self.ids("가려진본문단서", self.boss))
        row = next(r for r in self.search("공개표제")["data"]["results"] if r["id"] == str(post.pk))
        self.assertEqual(row["snippet"], "")
        score = row["score"]
        post.wr_content = "공개표제 " * 100 + "가려진본문단서"
        post.save(update_fields=["wr_content"])
        self.assertEqual(next(r["score"] for r in self.search("공개표제")["data"]["results"] if r["id"] == str(post.pk)), score)
        point_ledger.insert_point(self.other, 100, "seed", "@search", 0, "seed")
        point_ledger.insert_point(self.other, -5, "read", self.board.bo_table, 190001, "읽기")
        self.assertIn(("post", str(post.pk)), self.ids("가려진본문단서", self.other))

    def test_index_tracks_saves_deletes_and_transaction_rollbacks(self):
        self.target.wr_subject, self.target.wr_content = "사과상자", "신선한 사과"
        self.target.save(update_fields=["wr_subject", "wr_content"])
        self.assertIn(("post", str(self.target.pk)), self.ids("사과상자"))
        with transaction.atomic():
            self.target.wr_subject = "롤백제목"
            self.target.save(update_fields=["wr_subject"])
            transaction.set_rollback(True)
        self.assertEqual(self.ids("롤백제목"), set())
        post_id = self.target.pk
        self.target.delete()
        self.assertFalse(SearchDocument.objects.filter(post_id=post_id).exists())

    def test_rebuild_fixes_bulk_updates_and_is_idempotent(self):
        Post.objects.filter(pk=self.target.pk).update(wr_subject="재색인확인", wr_content="새로운 본문")
        call_command("rebuild_search_index", kind="post", stdout=StringIO())
        self.assertIn(("post", str(self.target.pk)), self.ids("재색인확인"))
        doc = SearchDocument.objects.get(post=self.target)
        when = doc.indexed_at
        call_command("rebuild_search_index", kind="post", stdout=StringIO())
        doc.refresh_from_db()
        self.assertEqual(when, doc.indexed_at)

    def test_not_ready_keeps_legacy_apis_available(self):
        SearchIndexState.objects.filter(kind="post").update(ready=False)
        self.assertEqual(self.api().get(f"{API}/unified", {"q": "입금"}).status_code, 503)
        self.assertEqual(self.api().get(API, {"q": "입금"}).status_code, 200)
        SearchIndexState.objects.filter(kind="product").update(tokenizer="different")
        self.assertEqual(self.api().get(f"{API}/unified", {"q": "입금", "type": "product"}).status_code, 503)

    def test_compatibility_api_uses_index_and_preserves_product_price_sort(self):
        grouped = self.api().get(API, {"q": "입금확인은"}).json()["data"]
        self.assertGreater(grouped["total_count"], 0)
        ShopProduct.objects.create(it_id="search-002", it_name="입금 확인 저렴한 상품", it_price=100)
        response = self.api().get("/api/v1/shop/products", {"q": "입금확인은", "sort": "price_asc"})
        self.assertEqual(response.status_code, 200, response.content[:500])
        prices = [row["it_price"] for row in response.json()["data"]]
        self.assertEqual(prices, [100, 12000])

    def test_stop_words_and_oversized_tokens_produce_empty_results(self):
        for query in ("어떻게", "x" * 150):
            self.assertEqual(self.search(query)["data"]["results"], [])
            response = self.api().get("/api/v1/shop/products", {"q": query})
            self.assertEqual(response.status_code, 200, response.content[:500])
            self.assertEqual(response.json()["data"], [])

    def test_click_tokens_deduplicate_revalidate_permissions_and_respect_dnt(self):
        token = self.token()
        client = self.api()
        first = client.post(f"{API}/click", {"token": token}, format="json")
        self.assertTrue(first.json()["data"]["recorded"])
        self.assertFalse(client.post(f"{API}/click", {"token": token}, format="json").json()["data"]["recorded"])
        self.assertEqual(SearchClickDaily.objects.get().query_hash, query_hash("입금 확인"))
        self.assertEqual(SearchClickDaily.objects.get().count, 1)
        self.assertEqual(client.post(f"{API}/click", {"token": token + "x"}, format="json").status_code, 400)
        with mock.patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 901):
            self.assertEqual(client.post(f"{API}/click", {"token": token}, format="json").status_code, 400)
        cache.clear()
        self.assertFalse(client.post(f"{API}/click", {"token": token}, format="json", HTTP_DNT="1").json()["data"]["recorded"])
        self.assertFalse(client.post(f"{API}/click", {"token": token}, format="json", HTTP_USER_AGENT="Googlebot").json()["data"]["recorded"])
        type(self.board).objects.filter(pk=self.board.pk).update(bo_use_search=False)
        self.assertEqual(client.post(f"{API}/click", {"token": token}, format="json").status_code, 404)

    def test_clicks_and_popularity_only_give_bounded_boosts(self):
        before = {row["id"]: row["score"] for row in self.search(type="post")["data"]["results"]}
        doc = SearchDocument.objects.get(post=self.target)
        SearchClickDaily.objects.create(document=doc, query_hash=query_hash("입금 확인"), count=1000000)
        SearchKeywordDaily.objects.create(keyword="입금 확인", source="site", day=timezone.localdate(), count=1000000)
        cache.clear()
        after = {row["id"]: row["score"] for row in self.search(type="post")["data"]["results"]}
        self.assertGreater(after[str(self.target.pk)], before[str(self.target.pk)])
        self.assertLessEqual(after[str(self.target.pk)], before[str(self.target.pk)] * 1.151)
        self.assertEqual(self.ids("관련없는질의"), set())

    def test_validation_pagination_and_private_cache_headers(self):
        for query in ("x", "x" * 201, "aa\x00"):
            self.assertEqual(self.api().get(f"{API}/unified", {"q": query}).status_code, 400)
        self.assertEqual(self.api().get(f"{API}/unified", {"q": "입금", "type": "unknown"}).status_code, 400)
        self.assertEqual(self.api().get(f"{API}/unified", {"q": "입금", "bo_table": "aa\x00"}).status_code, 400)
        first = self.search(limit=1)
        second = self.search(limit=1, page=2)
        self.assertNotEqual(first["data"]["results"], second["data"]["results"])
        self.assertEqual(first["meta"]["candidate_limit"], CANDIDATE_LIMIT)
        response = self.api().get(f"{API}/unified", {"q": "입금"})
        self.assertIn("no-store", response["Cache-Control"])

    def test_bm25_candidate_budget_is_reported_and_enforced(self):
        with mock.patch("gnu_jango.site_search.service.CANDIDATE_LIMIT", 2):
            response = self.search()
        self.assertGreater(response["meta"]["total"], 2)
        self.assertTrue(response["meta"]["truncated"])
        self.assertEqual(len(response["data"]["results"]), 2)

    def test_query_count_does_not_grow_with_board_count(self):
        from types import SimpleNamespace
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .service import ranked_results
        request = SimpleNamespace(user=None, session={})
        ranked_results(request, "입금 확인")  # Warm only the public popularity/config caches.
        with CaptureQueriesContext(connection) as before:
            ranked_results(request, "입금 확인")
        for index in range(12):
            board = self.make_board(f"search-scale-{index}")
            self.make_post(board, wr_subject="입금 확인", wr_content="입금 확인 안내")
        with CaptureQueriesContext(connection) as after:
            ranked_results(request, "입금 확인")
        self.assertEqual(len(before), len(after))
        self.assertLessEqual(len(after), 8)

    def test_postgresql_fts_indexes_are_usable(self):
        from django.db import connection
        from types import SimpleNamespace
        from .service import matching_documents, visible_documents
        if connection.vendor != "postgresql":
            self.skipTest("Requires a real PostgreSQL test database")
        docs, body = visible_documents(SimpleNamespace(user=None, session={}))
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
        plan = matching_documents(docs, "입금 확인", allowed_body=body).explain()
        self.assertTrue("search_title_fts" in plan or "search_body_fts" in plan, plan)

    def test_postgresql_optional_trigram_finds_a_misspelled_title(self):
        from django.db import connection
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL with permission to install pg_trgm")
        # setUpTestData is inside Django's outer transaction; flush deferred FK
        # checks before the DDL, as a normal autocommit management command would.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        call_command("configure_search_postgres", stdout=StringIO())
        product = ShopProduct.objects.create(it_id="search-fuzzy", it_name="wireless keyboard")
        with override_settings(G5_SEARCH_TRIGRAM=True):
            response = self.search("wireles keybord", type="product")
        self.assertTrue(response["meta"]["fuzzy"])
        self.assertIn(product.pk, [row["id"] for row in response["data"]["results"]])

    def test_korean_evaluation_top3_at_least_eighty_percent(self):
        fixtures = [
            ("회원가입 이메일 인증", "이메일인증은 어떻게 하나요"),
            ("관리자 비밀번호 초기화", "비밀번호초기화 방법"),
            ("배송비 설정", "배송비설정은 어디서 하나요"),
            ("상품 재고 관리", "상품재고를 관리하려면"),
            ("주문 취소 환불", "주문취소와 환불은"),
            ("쿠폰 발급", "쿠폰발급 방법"),
            ("적립 포인트 지급", "포인트지급 하려면"),
            ("게시판 생성", "게시판생성은 어떻게"),
            ("테마 변경", "테마변경은 어디서"),
            ("파일 업로드 용량", "업로드용량을 바꾸려면"),
            ("검색 색인 재생성", "색인재생성 방법"),
            ("캡챠 스팸 방지", "스팸방지는 어떻게"),
            ("데이터베이스 백업", "데이터베이스백업 방법"),
            ("PythonAnywhere 배포", "PythonAnywhere에 배포하려면"),
            ("소셜 로그인 설정", "소셜로그인 설정은"),
        ]
        expected = [(self.make_post(self.board, wr_subject=title, wr_content=f"{title} 안내 절차").pk, query) for title, query in fixtures]
        success = 0
        for pk, query in expected:
            rows = self.search(query, type="post", limit=3)["data"]["results"]
            success += any(row["id"] == str(pk) for row in rows)
        self.assertGreaterEqual(success / len(expected), 0.8, f"Top3 {success}/{len(expected)}")

    def test_sqlite_candidate_filter_uses_postings_index(self):
        from django.db import connection
        from .service import matching_documents, visible_documents
        if connection.vendor != "sqlite":
            self.skipTest("SQLite query plan check")
        request = mock.Mock(user=None, session={})
        docs, body = visible_documents(request)
        plan = matching_documents(docs, "입금 확인", allowed_body=body).explain()
        self.assertIn("search_term_field_doc", plan)
