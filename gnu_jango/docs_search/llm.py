import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


def llm_is_enabled():
    return bool(
        str(getattr(settings, "G5_DOCS_LLM_BASE_URL", "") or "").strip()
        and str(getattr(settings, "G5_DOCS_LLM_MODEL", "") or "").strip()
    )


def _endpoint():
    base_url = str(getattr(settings, "G5_DOCS_LLM_BASE_URL", "") or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return None
    if parsed.query or parsed.fragment:
        return None
    return f"{base_url}/chat/completions"


def generate_answer(question, results):
    """Call only the operator-configured OpenAI-compatible endpoint with visible snippets."""
    if not llm_is_enabled():
        return None, "disabled"
    if not results:
        return None, "no_evidence"
    endpoint = _endpoint()
    model = str(getattr(settings, "G5_DOCS_LLM_MODEL", "") or "").strip()
    if not endpoint:
        return None, "invalid_configuration"

    evidence = [
        {
            "number": index,
            "book": item["book"],
            "part": item["part"],
            "chapter": item["chapter"],
            "section": item["section"],
            "snippet": item["snippet"],
        }
        for index, item in enumerate(results, start=1)
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "주어진 매뉴얼 문단에 있는 내용만 답하세요. 근거가 없으면 모른다고 말하세요. "
                "한국어로 답하고, 각 사실 문장 끝에 근거 번호를 [1] 형식으로 표시하세요. "
                "JSON 객체 {\"text\": 문자열, \"citations\": [정수]} 하나만 출력하세요."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"question": question, "documents": evidence}, ensure_ascii=False),
        },
    ]
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2}, ensure_ascii=False
    ).encode("utf-8")
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        timeout = int(getattr(settings, "G5_DOCS_LLM_TIMEOUT", 20) or 20)
        with urlopen(request, timeout=max(1, min(timeout, 60))) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        content = response_data["choices"][0]["message"]["content"]
        generated = json.loads(content)
        text = str(generated.get("text") or "").strip()
        citations = generated.get("citations")
        if not text or not isinstance(citations, list):
            return None, "invalid_response"
        citations = list(dict.fromkeys(int(item) for item in citations))
        if not citations or any(item < 1 or item > len(evidence) for item in citations):
            return None, "invalid_citations"
        return {"text": text[:2000], "citations": citations}, None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Configured handbook answer model did not return a usable answer (%s).", type(exc).__name__)
        return None, "unavailable"
