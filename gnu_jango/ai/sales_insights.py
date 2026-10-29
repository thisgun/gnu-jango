"""AI briefing of the 매출 이상 징후 findings (optional, G5_AI_SALES_INSIGHTS).

The findings and their numbers come from gnu_jango.shop.sales_anomalies; the chat model only words
them for the operator. It receives the month's totals and the findings (aggregates, no customer
data). A briefing that contains a number not present in that input is discarded, so a made-up
figure never reaches the page; the operator then sees the rule-based findings alone.
"""
import hashlib
import json
import logging
import re
import time

from django.core.cache import cache

from . import conf
from .client import ChatError, get_chat_provider
from .review_summaries import clean_summary

logger = logging.getLogger(__name__)
CACHE_SECONDS = 6 * 60 * 60
MAX_BRIEFING_CHARS = 700
PROMPT_VERSION = "1"
ATTEMPT_TEMPERATURES = (0.2, 0.0)
# The briefing is made inside an admin request: a cold model must not hold the worker for the
# background G5_AI_CHAT_TIMEOUT (two minutes, twice). 20 s for an answer, and the second try only
# when the first came back within 10 s, keeps the request near the common 30 s worker limit.
INTERACTIVE_TIMEOUT = 20
RETRY_WITHIN_SECONDS = 10
SYSTEM_PROMPT = (
    "당신은 쇼핑몰 운영자에게 한 달 매출 점검 결과를 설명합니다. 주어진 JSON의 합계와 발견 사항만 근거로 "
    "한국어 존댓말 3~5문장으로 정리하세요. 가장 중요한 발견부터 말하고, 마지막 문장에는 운영자가 확인해 볼 "
    "만한 점(결제대행사 상태, 프로모션, 취소·환불 사유 등)을 적으세요. 원인은 단정하지 말고 '~일 수 "
    "있습니다'처럼 추측임을 밝히세요. 숫자는 JSON에 있는 값과 표기(예: 1,234,000원, 54%)를 그대로 쓰고, "
    "새로 계산하거나 반올림하거나 만 원 단위로 바꾸지 마세요. 마크다운 없이 문장만 출력하세요."
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def insights_enabled():
    return conf.sales_insights_requested() and get_chat_provider() is not None


def model_input(report):
    """The JSON the model sees: the period, the totals and the findings (no customer data)."""
    current = report["current"]
    return {
        "month": report["month"],
        "period": f"{report['start'].isoformat()} ~ {report['end'].isoformat()}",
        "days": report["elapsed_days"],
        "baseline": f"직전 {report['baseline_months']}개월 "
                    f"({report['baseline_start'].isoformat()} ~ {report['baseline_end'].isoformat()})",
        "totals": {
            "입금": f"{current['receipt']:,}원",
            "주문": f"{current['orders']:,}건",
            "취소": f"{current['cancels']:,}건",
            "환불": f"{current['refund']:,}원",
        },
        "findings": [
            {"severity": finding["severity_label"], "title": finding["title"], "detail": finding["detail"]}
            for finding in report["findings"]
        ],
    }


def _normalize(token):
    token = token.replace(",", "")
    if "." in token:
        value = float(token)
        return str(int(value)) if value.is_integer() else repr(value)
    return str(int(token))


def numbers_in(text):
    return {_normalize(token) for token in _NUMBER.findall(str(text or ""))}


def unverified_numbers(briefing, source_text):
    """The numbers in ``briefing`` that do not appear in ``source_text``."""
    return numbers_in(briefing) - numbers_in(source_text)


def allowed_numbers_text(sent, report):
    """The text a briefing's numbers must come from: the totals, the findings and the year/month.

    The period and baseline dates and the day count are left out: they would let any invented
    figure from 1 to 31 (or the year) through, e.g. "취소율 12%" next to a 12th in the dates.
    """
    return json.dumps([sent["totals"], sent["findings"], report["start"].year, report["start"].month],
                      ensure_ascii=False)


def narrate(report, provider=None):
    """``(briefing, None)`` or ``(None, reason)``; reasons: disabled, unavailable, timeout,
    http_error, invalid_response, unverified_numbers. Briefings are cached per input for 6 hours.

    It runs inside an admin request, so the model gets INTERACTIVE_TIMEOUT seconds (not the
    background G5_AI_CHAT_TIMEOUT), and the second try only follows a quick first answer.
    """
    if provider is None and conf.sales_insights_requested():
        provider = get_chat_provider(timeout=INTERACTIVE_TIMEOUT)
    if provider is None:
        return None, "disabled"
    sent = model_input(report)
    source = json.dumps(sent, ensure_ascii=False, sort_keys=True)
    allowed = allowed_numbers_text(sent, report)
    key = "ai:sales-insight:v1:" + hashlib.sha256(
        f"{PROMPT_VERSION}\0{provider.model}\0{source}".encode("utf-8")).hexdigest()
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached:
        return cached, None
    # A small model now and then rounds or derives a figure; one more try at temperature 0 usually
    # sticks to the given numbers.
    started = time.monotonic()
    for attempt, temperature in enumerate(ATTEMPT_TEMPERATURES):
        if attempt and time.monotonic() - started > RETRY_WITHIN_SECONDS:
            return None, "unverified_numbers"
        try:
            answer = provider.complete(SYSTEM_PROMPT, source, max_tokens=600, temperature=temperature)
        except ChatError as exc:
            logger.warning("Sales briefing unavailable (reason=%s).", exc.reason)
            return None, exc.reason
        briefing = clean_summary(answer, MAX_BRIEFING_CHARS)
        if not briefing:
            return None, "invalid_response"
        stray = unverified_numbers(briefing, allowed)
        if not stray:
            break
        logger.warning("Sales briefing discarded: numbers not in the findings (%s).", ", ".join(sorted(stray)))
    else:
        return None, "unverified_numbers"
    try:
        cache.set(key, briefing, CACHE_SECONDS)
    except Exception:
        logger.warning("Sales briefing not cached.", exc_info=True)
    return briefing, None
