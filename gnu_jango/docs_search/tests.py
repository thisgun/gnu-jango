import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Post
from gnu_jango.config import config as site_config
from gnu_jango.config import handbook_samples
from gnu_jango.config.models import Config
from gnu_jango.docs_search.evaluation import EVALUATION_CASES
from gnu_jango.docs_search.llm import generate_answer
from gnu_jango.docs_search.parser import parse_manual_html, slugify_heading
from gnu_jango.docs_search.service import clear_memory_cache, search_documents

API = "/api/v1/docs/ask"
REST_FRAMEWORK_WITH_DOCS_TEST_RATE = {
    **settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "docs-ask": "1000/min",
    },
}


@override_settings(REST_FRAMEWORK=REST_FRAMEWORK_WITH_DOCS_TEST_RATE)
class HandbookAskTests(TestCase):
    def setUp(self):
        cache.clear()
        clear_memory_cache()
        site_config.clear()
        handbook_samples.ensure_samples(stable_dates=True)
        Config.objects.update_or_create(
            name="cf_docs_group", defaults={"value": handbook_samples.GROUP_ID}
        )
        site_config.clear()
        self.client = APIClient()

    def tearDown(self):
        clear_memory_cache()
        site_config.clear()

    def search(self, query, **params):
        return self.client.get(API, {"q": query, **params})

    def test_query_length_is_validated(self):
        self.assertEqual(self.search("a").status_code, 400)
        self.assertEqual(self.search("한" * 201).status_code, 400)
        self.assertEqual(self.search("   ").status_code, 400)
        self.assertEqual(self.search("서버 준비").status_code, 200)

    def test_empty_or_unconfigured_manual_is_a_successful_empty_result(self):
        Config.objects.filter(name="cf_docs_group").update(value="")
        site_config.clear()
        response = self.search("서버 준비")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["results"], [])
        self.assertIsNone(response.json()["data"]["answer"])

    def test_results_include_plain_text_metadata_anchor_and_highlights(self):
        response = self.search("정적 파일을 서버에 올리는 방법")
        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertTrue(results)
        item = results[0]
        self.assertEqual(item["bo_table"], "hb_deploy")
        self.assertEqual(item["chapter"], "정적 파일 올리기")
        self.assertIn("/bbs/hb_deploy/", item["url"])
        self.assertRegex(item["url"], r"#.+-\d+$")
        self.assertIsInstance(item["snippet"], str)
        self.assertIsInstance(item["highlights"], list)
        self.assertGreater(item["score"], 0)
        self.assertNotIn("<mark", item["snippet"])

    def test_results_obey_list_and_read_permissions(self):
        board = Board.objects.get(bo_table="hb_deploy")
        query = "환경 변수 SECRET_KEY"
        board.bo_list_level = 2
        board.bo_read_level = 2
        board.save(update_fields=("bo_list_level", "bo_read_level"))
        guest_results = self.search(query).json()["data"]["results"]
        self.assertFalse(any(item["bo_table"] == board.bo_table for item in guest_results))

        user = get_user_model().objects.create_user(username="ordinary", password="test-pass-123")
        user.profile.user_level = 2
        user.profile.save(update_fields=("user_level",))
        self.client.force_authenticate(user=user)
        member_results = self.search(query).json()["data"]["results"]
        self.assertTrue(any(item["bo_table"] == "hb_deploy" for item in member_results))

        admin = get_user_model().objects.create_superuser(
            username="docs-admin", email="docs-admin@example.test", password="test-pass-123"
        )
        self.client.force_authenticate(user=admin)
        admin_results = self.search(query).json()["data"]["results"]
        self.assertTrue(any(item["bo_table"] == "hb_deploy" for item in admin_results))

    def test_non_searchable_boards_are_excluded(self):
        board = Board.objects.get(bo_table="hb_deploy")
        board.bo_use_search = False
        board.save(update_fields=("bo_use_search",))
        results = self.search("환경 변수 SECRET_KEY").json()["data"]["results"]
        self.assertFalse(any(item["bo_table"] == "hb_deploy" for item in results))

    def test_secret_post_body_is_never_returned_even_to_an_admin(self):
        board = Board.objects.get(bo_table="hb_deploy")
        private_post = Post.objects.create(
            board=board,
            wr_num=-100,
            wr_parent=0,
            wr_subject="개인정보 비밀 안내",
            wr_content="<p>private-sentinel-731 개인정보 보호 내용</p>",
            wr_option="secret",
            ca_name="준비",
            wr_name="편집자",
            wr_datetime=handbook_samples.timezone.now(),
        )
        admin = get_user_model().objects.create_superuser(
            username="secret-admin", email="secret-admin@example.test", password="test-pass-123"
        )
        self.client.force_authenticate(user=admin)
        response = self.search("개인정보 보호")
        results = response.json()["data"]["results"]
        self.assertFalse(any(item["wr_id"] == private_post.pk for item in results))
        self.assertFalse(any("private-sentinel-731" in item["snippet"] for item in results))

    def test_llm_prompt_never_receives_secret_post_content(self):
        board = Board.objects.get(bo_table="hb_dev")
        private_post = Post.objects.create(
            board=board,
            wr_num=-101,
            wr_parent=0,
            wr_subject="개인정보 보호 안내",
            wr_content="<p>개인정보 보호 private-sentinel-947 비밀 내용</p>",
            wr_option="secret",
            ca_name="개인정보",
            wr_name="편집자",
            wr_datetime=handbook_samples.timezone.now(),
        )
        admin = get_user_model().objects.create_superuser(
            username="llm-secret-admin", email="llm-secret-admin@example.test", password="test-pass-123"
        )
        self.client.force_authenticate(user=admin)
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"text": "매뉴얼에서 확인할 수 있습니다. [1]", "citations": [1]}, ensure_ascii=False)
                    }
                }
            ]
        }
        mocked_response = MagicMock()
        mocked_response.__enter__.return_value.read.return_value = json.dumps(response_data).encode("utf-8")
        with override_settings(
            G5_DOCS_LLM_BASE_URL="http://127.0.0.1:11434/v1",
            G5_DOCS_LLM_MODEL="test-model",
            G5_DOCS_LLM_TIMEOUT=3,
        ), patch("gnu_jango.docs_search.llm.urlopen", return_value=mocked_response) as mocked_urlopen:
            response = self.search("개인정보 보호", answer=1)

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertFalse(any(item["wr_id"] == private_post.pk for item in results))
        prompt = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))["messages"][1]["content"]
        self.assertNotIn("private-sentinel-947", prompt)
        self.assertNotIn("private-sentinel-947", response.content.decode("utf-8"))

    def test_question_evaluation_set_reaches_at_least_eighty_percent_hit_at_three(self):
        hits_at_1 = 0
        hits_at_3 = 0
        for question, table, chapter in EVALUATION_CASES:
            with self.subTest(question=question):
                results = self.search(question, limit=3).json()["data"]["results"]
                matches = [item for item in results if item["bo_table"] == table and item["chapter"] == chapter]
                hits_at_1 += bool(results and (results[0]["bo_table"], results[0]["chapter"]) == (table, chapter))
                hits_at_3 += bool(matches)
        self.assertGreaterEqual(hits_at_3 / len(EVALUATION_CASES), 0.8)
        self.assertGreaterEqual(hits_at_1, 1)

    def test_configured_answer_uses_only_visible_search_results_and_valid_citations(self):
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"text": "환경 변수에 저장합니다. [1]", "citations": [1]},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        mocked_response = MagicMock()
        mocked_response.__enter__.return_value.read.return_value = json.dumps(response_data).encode("utf-8")
        results = self.search("Vercel 환경 변수", limit=2).json()["data"]["results"]
        with override_settings(
            G5_DOCS_LLM_BASE_URL="http://127.0.0.1:11434/v1",
            G5_DOCS_LLM_MODEL="test-model",
            G5_DOCS_LLM_TIMEOUT=3,
        ), patch("gnu_jango.docs_search.llm.urlopen", return_value=mocked_response) as mocked_urlopen:
            answer, reason = generate_answer("Vercel 환경 변수", results)

        self.assertIsNone(reason)
        self.assertEqual(answer["citations"], [1])
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/v1/chat/completions")
        prompt = json.loads(request.data.decode("utf-8"))["messages"][1]["content"]
        self.assertIn("Vercel 환경 변수", prompt)
        self.assertNotIn("private-sentinel", prompt)

    def test_answer_rejects_out_of_range_citations_and_handles_timeout(self):
        invalid = MagicMock()
        invalid.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": '{"text":"답변 [2]","citations":[2]}'}}]}
        ).encode("utf-8")
        with override_settings(
            G5_DOCS_LLM_BASE_URL="http://localhost:11434/v1", G5_DOCS_LLM_MODEL="test-model"
        ), patch("gnu_jango.docs_search.llm.urlopen", return_value=invalid):
            answer, reason = generate_answer("질문", [{"snippet": "근거", "book": "책", "part": "", "chapter": "장", "section": ""}])
        self.assertIsNone(answer)
        self.assertEqual(reason, "invalid_citations")

        with override_settings(
            G5_DOCS_LLM_BASE_URL="http://localhost:11434/v1", G5_DOCS_LLM_MODEL="test-model"
        ), patch("gnu_jango.docs_search.llm.urlopen", side_effect=TimeoutError):
            answer, reason = generate_answer("질문", [{"snippet": "근거", "book": "책", "part": "", "chapter": "장", "section": ""}])
        self.assertIsNone(answer)
        self.assertEqual(reason, "unavailable")


class HandbookHtmlParserTests(TestCase):
    def test_python_anchors_match_shared_page_toc_fixtures(self):
        fixtures = json.loads(Path(__file__).with_name("anchor_fixtures.json").read_text(encoding="utf-8"))
        for fixture in fixtures:
            with self.subTest(text=fixture["text"]):
                self.assertEqual(
                    slugify_heading(fixture["text"], fixture["index"]),
                    fixture["anchor"],
                )

    def test_html_is_extracted_as_plain_paragraphs_and_scripts_are_ignored(self):
        paragraphs = parse_manual_html(
            "<h2>첫 번째 절</h2><p>안전한 <strong>본문</strong></p><script>private()</script>"
            "<h3>하위 절</h3><ul><li>항목</li></ul>"
        )
        self.assertEqual([item.text for item in paragraphs], ["첫 번째 절", "안전한 본문", "하위 절", "항목"])
        self.assertEqual(paragraphs[0].anchor, slugify_heading("첫 번째 절", 0))
        self.assertEqual(paragraphs[2].anchor, slugify_heading("하위 절", 1))
        self.assertNotIn("private", " ".join(item.text for item in paragraphs))

    def test_html_entities_and_unicode_headings_match_page_toc_conventions(self):
        heading = "결제 & 배송 (한글)"
        parsed = parse_manual_html(f"<h2>{heading}</h2><p>&lt;safe&gt;</p>")
        self.assertEqual(parsed[0].anchor, "결제-배송-한글-0")
        self.assertEqual(parsed[1].text, "<safe>")
