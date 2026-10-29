from datetime import date
from unittest import mock

import pytest
from django.core.cache import cache
from django.test import override_settings

from gnu_jango.ai.client import ChatError, chat_provider_override
from gnu_jango.ai.sales_insights import INTERACTIVE_TIMEOUT, model_input, narrate, numbers_in, unverified_numbers
from gnu_jango.ai.testing import FakeChatProvider

REPORT = {
    "month": "2026-10", "start": date(2026, 10, 1), "end": date(2026, 10, 20), "elapsed_days": 20,
    "baseline_start": date(2026, 7, 1), "baseline_end": date(2026, 9, 30), "baseline_months": 3,
    "current": {"orders": 40, "cancels": 12, "receipt": 1_678_300, "refund": 0},
    "findings": [{"key": "cancel_rate", "severity": "high", "severity_label": "주의",
                  "title": "취소율이 0%에서 54%로 올랐습니다", "detail": "주문 52건 중 취소 12건", "numbers": {}}],
}


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


def test_numbers_are_compared_without_thousands_separators():
    assert numbers_in("입금 1,678,300원, 54% (2026-10-05)") == {"1678300", "54", "2026", "10", "5"}
    assert unverified_numbers("입금은 1,678,300원이고 취소율은 54%입니다", "1678300 ... 54%") == set()
    assert unverified_numbers("약 168만 원입니다", "1,678,300원") == {"168"}


def test_the_model_sees_aggregates_and_findings_only():
    sent = model_input(REPORT)
    assert sent["totals"]["입금"] == "1,678,300원"
    assert sent["findings"] == [{"severity": "주의", "title": "취소율이 0%에서 54%로 올랐습니다", "detail": "주문 52건 중 취소 12건"}]


def test_narrate_is_off_without_the_setting():
    assert narrate(REPORT) == (None, "disabled")


def test_a_checked_briefing_is_returned_and_cached():
    chat = FakeChatProvider(reply="**요약** 이번 달 주문 52건 중 취소 12건으로 취소율이 54%입니다. 취소 사유를 확인해 보세요.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        briefing, reason = narrate(REPORT)
        assert reason is None and briefing.startswith("요약 이번 달")
        assert narrate(REPORT) == (briefing, None)
    assert len(chat.calls) == 1


def test_a_briefing_with_a_made_up_number_is_discarded_after_a_second_try():
    chat = FakeChatProvider(reply="취소율이 60%로 크게 올랐습니다.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        assert narrate(REPORT) == (None, "unverified_numbers")
    assert len(chat.calls) == 2


class ScriptedChat(FakeChatProvider):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.temperatures = []

    def complete(self, system, user, **kwargs):
        self.calls.append((system, user))
        self.temperatures.append(kwargs.get("temperature"))
        return self.replies.pop(0)


def test_a_second_try_at_temperature_zero_can_rescue_the_briefing():
    chat = ScriptedChat(["취소율이 약 55%입니다.", "취소율이 0%에서 54%로 올랐습니다. 취소 사유를 확인해 보세요."])
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        briefing, reason = narrate(REPORT)
    assert reason is None and briefing.startswith("취소율이 0%에서 54%")
    assert chat.temperatures == [0.2, 0.0]


def test_dates_in_the_period_do_not_vouch_for_an_invented_number():
    # 20 appears only as the period's last day (2026-10-20)
    chat = FakeChatProvider(reply="취소율이 20%로 올랐습니다.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        assert narrate(REPORT) == (None, "unverified_numbers")


def test_the_month_itself_may_be_named():
    chat = FakeChatProvider(reply="2026년 10월은 취소율이 54%입니다.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        assert narrate(REPORT)[1] is None


def test_a_slow_first_answer_is_not_tried_again():
    chat = FakeChatProvider(reply="취소율이 60%입니다.")
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat), \
            mock.patch("gnu_jango.ai.sales_insights.time.monotonic", side_effect=[0.0, 15.0]):
        assert narrate(REPORT) == (None, "unverified_numbers")
    assert len(chat.calls) == 1


def test_the_briefing_waits_less_than_a_background_job():
    with override_settings(G5_AI_SALES_INSIGHTS=True), \
            mock.patch("gnu_jango.ai.sales_insights.get_chat_provider", return_value=None) as provider:
        narrate(REPORT)
    provider.assert_called_once_with(timeout=INTERACTIVE_TIMEOUT)


def test_endpoint_errors_come_back_as_reasons():
    chat = FakeChatProvider(error=ChatError("unavailable"))
    with override_settings(G5_AI_SALES_INSIGHTS=True), chat_provider_override(chat):
        assert narrate(REPORT) == (None, "unavailable")
