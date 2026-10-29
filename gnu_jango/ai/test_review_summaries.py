import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from rest_framework.test import APIClient

from gnu_jango.ai.client import ChatError, OpenAICompatibleChat, chat_provider_override
from gnu_jango.ai.models import ReviewSummary
from gnu_jango.ai.review_summaries import MAX_SUMMARY_CHARS, NO_SUMMARY, SYSTEM_PROMPT, clean_summary
from gnu_jango.ai.test_client import FakeOpener
from gnu_jango.ai.testing import FakeChatProvider
from gnu_jango.shop.models import ShopReview

SUMMARIES_ON = {"G5_AI_REVIEW_SUMMARIES": True}


@pytest.fixture
def chat():
    provider = FakeChatProvider()
    with chat_provider_override(provider):
        yield provider


def review(product, score=5, subject="좋아요", content="<p>가볍고 따뜻해요</p>", confirm="1"):
    return ShopReview.objects.create(product=product, is_score=score, is_subject=subject, is_content=content,
                                     is_name="홍길동", mb_id="hong", is_confirm=confirm)


@pytest.fixture
def reviewed(catalogue):
    for text in ("가볍고 따뜻해요", "세탁하니 보풀이 생겨요", "휴대가 편해요"):
        review(catalogue.laptop, content=f"<p>{text}</p>")
    # two published reviews and an unpublished one: under the 3-review minimum
    review(catalogue.mouse)
    review(catalogue.mouse)
    review(catalogue.mouse, confirm="0")
    return catalogue


def summarize(*args):
    out = StringIO()
    call_command("summarize_reviews", "--json", *args, stdout=out)
    return json.loads(out.getvalue())


def detail(it_id):
    response = APIClient().get(f"/api/v1/shop/products/{it_id}")
    assert response.status_code == 200, response.content[:500]
    return response.json()["data"]["ai_review_summary"]


def test_only_products_with_enough_published_reviews_are_summarised(reviewed, chat):
    report = summarize()
    assert report["summarized"] == 1 and report["eligible"] == 1
    row = ReviewSummary.objects.get()
    assert (row.product_id, row.review_count, row.model) == ("NB-1", 3, "fake-chat")
    system, user = chat.calls[0]
    assert system == SYSTEM_PROMPT
    sent = json.loads(user)
    assert sent["product"] == "가벼운 노트북"
    assert sorted(item["text"] for item in sent["reviews"]) == ["가볍고 따뜻해요", "세탁하니 보풀이 생겨요", "휴대가 편해요"]
    # reviewer identity and markup never reach the model
    assert "홍길동" not in user and "hong" not in user and "<p>" not in user


def test_unchanged_reviews_are_not_sent_again_and_a_new_review_rewrites_the_summary(reviewed, chat):
    summarize()
    assert summarize()["unchanged"] == 1
    assert len(chat.calls) == 1
    review(reviewed.laptop, score=2, content="배송이 늦었어요")
    chat.reply = "새 요약입니다."
    assert summarize()["summarized"] == 1
    row = ReviewSummary.objects.get()
    assert (row.summary, row.review_count) == ("새 요약입니다.", 4)


def test_reviews_with_nothing_to_summarise_are_remembered_but_never_shown(reviewed, chat):
    chat.reply = f"{NO_SUMMARY}."
    report = summarize()
    assert (report["insufficient"], report["summarized"]) == (1, 0)
    assert ReviewSummary.objects.get().summary == ""
    with override_settings(**SUMMARIES_ON):
        assert detail("NB-1") is None
    # not asked again until the reviews change
    assert summarize()["unchanged"] == 1 and len(chat.calls) == 1


def test_a_short_answer_that_says_nothing_in_other_words_is_not_shown(reviewed, chat):
    chat.reply = "구매자분들께서는 상품에 대해 구체적인 장점이나 아쉬운 점을 언급하지 않으셨습니다."
    assert summarize()["insufficient"] == 1
    assert ReviewSummary.objects.get().summary == ""


def test_a_hidden_summary_stays_hidden_after_a_rewrite(reviewed, chat):
    summarize()
    ReviewSummary.objects.update(is_hidden=True)
    review(reviewed.laptop, content="또 샀어요")
    summarize()
    assert ReviewSummary.objects.get().is_hidden is True


def test_summaries_of_products_that_no_longer_qualify_are_deleted(reviewed, chat):
    summarize()
    reviewed.laptop.it_use = "0"
    reviewed.laptop.save(update_fields=["it_use"])
    assert summarize()["pruned"] == 1
    assert not ReviewSummary.objects.exists()


def test_dry_run_and_limit(reviewed, chat):
    review(reviewed.mouse)
    dry = summarize("--dry-run")
    assert (dry["would_summarize"], dry["summarized"]) == (2, 0)
    assert chat.calls == [] and not ReviewSummary.objects.exists()
    limited = summarize("--limit", "1")
    assert (limited["summarized"], limited["deferred"]) == (1, 1)


def test_an_unusable_answer_skips_the_product_but_an_endpoint_failure_stops_the_run(reviewed, chat):
    chat.error = ChatError("invalid_response")
    report = summarize()
    assert (report["failed"], report["summarized"]) == (1, 0)
    chat.error = ChatError("unavailable")
    with pytest.raises(CommandError, match="unavailable"):
        call_command("summarize_reviews", stdout=StringIO())


def test_without_a_chat_model_the_command_reports_not_configured(db):
    with override_settings(G5_AI_BASE_URL="", G5_AI_CHAT_MODEL=""):
        assert summarize() == {"configured": False}


def test_clean_summary_drops_markdown_and_cuts_at_a_sentence_end():
    assert clean_summary("**장점:**\n- 가볍습니다.\n- 따뜻합니다.") == "장점: 가볍습니다. 따뜻합니다."
    long = "좋습니다. " * 100
    cleaned = clean_summary(long)
    assert len(cleaned) <= MAX_SUMMARY_CHARS and cleaned.endswith("다.")


def test_the_product_page_shows_a_visible_summary_only_when_the_feature_is_on(reviewed, chat):
    summarize()
    calls = len(chat.calls)
    assert detail("NB-1") is None
    with override_settings(**SUMMARIES_ON):
        shown = detail("NB-1")
        assert shown["text"] == chat.reply and shown["review_count"] == 3
        assert detail("MS-1") is None
        ReviewSummary.objects.update(is_hidden=True)
        assert detail("NB-1") is None
    # the page reads the stored row; it never calls the model
    assert len(chat.calls) == calls


def test_chat_client_turns_thinking_off_and_returns_the_text():
    opener = FakeOpener(lambda payload: {"choices": [{"message": {"content": " 요약 "}}]})
    chat = OpenAICompatibleChat("http://127.0.0.1:11434/v1", "gemma4:e4b", timeout=9, opener=opener)
    assert chat.complete("system", "user") == " 요약 "
    sent = opener.requests[0]
    assert sent["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert sent["payload"]["reasoning_effort"] == "none" and sent["payload"]["stream"] is False
    assert [message["role"] for message in sent["payload"]["messages"]] == ["system", "user"]
    assert sent["timeout"] == 9


def test_chat_client_can_leave_reasoning_effort_out_and_rejects_empty_answers():
    opener = FakeOpener(lambda payload: {"choices": [{"message": {"content": "  "}}]})
    chat = OpenAICompatibleChat("http://127.0.0.1:11434/v1", "m", reasoning_effort="", opener=opener)
    with pytest.raises(ChatError) as raised:
        chat.complete("s", "u")
    assert raised.value.reason == "invalid_response"
    assert "reasoning_effort" not in opener.requests[0]["payload"]


def test_chat_client_sends_a_key_only_over_https_or_to_this_host():
    with pytest.raises(ChatError) as raised:
        OpenAICompatibleChat("http://models.example.com/v1", "m", api_key="secret")
    assert raised.value.reason == "insecure_configuration"
