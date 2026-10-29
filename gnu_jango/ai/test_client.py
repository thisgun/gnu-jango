import io
import json
import socket
from urllib.error import HTTPError, URLError

import pytest
from django.test import override_settings

from gnu_jango.ai import conf
from gnu_jango.ai.client import (
    EmbeddingError,
    OpenAICompatibleEmbeddings,
    get_provider,
    provider_override,
    semantic_search_enabled,
)
from gnu_jango.ai.testing import FakeEmbeddingProvider

BASE = "http://127.0.0.1:11434/v1"


class FakeOpener:
    """Stands in for urlopen: records each request and answers with ``respond(payload)``."""

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def __call__(self, request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append({"url": request.full_url, "headers": dict(request.header_items()),
                              "payload": payload, "timeout": timeout})
        result = self.respond(payload)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(json.dumps(result).encode("utf-8"))


def vectors_for(payload, dimensions=3):
    # Answer out of order: the client must sort by "index".
    rows = [{"index": index, "embedding": [float(index + 1)] * dimensions} for index, _ in enumerate(payload["input"])]
    return {"data": list(reversed(rows)), "model": payload["model"]}


def client(opener, **kwargs):
    return OpenAICompatibleEmbeddings(BASE, "bge-m3", dimensions=3, opener=opener, **kwargs)


def test_embed_batches_requests_and_keeps_input_order():
    opener = FakeOpener(vectors_for)
    vectors = client(opener, batch_size=2, timeout=7).embed(["a", "b", "c"])
    assert [len(batch["payload"]["input"]) for batch in opener.requests] == [2, 1]
    assert vectors == [[1.0] * 3, [2.0] * 3, [1.0] * 3]
    first = opener.requests[0]
    assert first["url"] == f"{BASE}/embeddings"
    assert first["payload"]["model"] == "bge-m3"
    assert first["timeout"] == 7


def test_empty_input_makes_no_request():
    opener = FakeOpener(vectors_for)
    assert client(opener).embed([]) == []
    assert opener.requests == []


def test_api_key_is_sent_as_bearer_and_never_shown():
    opener = FakeOpener(vectors_for)
    provider = client(opener, api_key="sk-secret-value")
    provider.embed(["a"])
    assert opener.requests[0]["headers"]["Authorization"] == "Bearer sk-secret-value"
    assert "sk-secret" not in repr(provider)


def test_api_key_requires_https_unless_local():
    with pytest.raises(EmbeddingError) as raised:
        OpenAICompatibleEmbeddings("http://api.example.com/v1", "m", dimensions=3, api_key="k")
    assert raised.value.reason == "insecure_configuration"
    OpenAICompatibleEmbeddings("https://api.example.com/v1", "m", dimensions=3, api_key="k")
    OpenAICompatibleEmbeddings("http://localhost:11434/v1", "m", dimensions=3, api_key="k")


def test_redirects_are_not_followed():
    from gnu_jango.ai.client import _NoRedirect

    assert _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/") is None


def test_no_authorization_header_without_a_key():
    opener = FakeOpener(vectors_for)
    client(opener).embed(["a"])
    assert "Authorization" not in opener.requests[0]["headers"]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (TimeoutError("timed out"), "timeout"),
        (URLError(socket.timeout("timed out")), "timeout"),
        (URLError(ConnectionRefusedError()), "unavailable"),
        (HTTPError(BASE, 500, "boom", {}, io.BytesIO(b"secret body")), "http_error"),
    ],
)
def test_transport_failures_raise_a_clear_reason(failure, reason):
    with pytest.raises(EmbeddingError) as raised:
        client(FakeOpener(lambda payload: failure)).embed(["a"])
    assert raised.value.reason == reason
    assert "secret body" not in str(raised.value)


@pytest.mark.parametrize(
    "answer",
    [{"data": "nope"}, {"unexpected": []}, {"data": [{"index": 0}]}, {"data": []}],
)
def test_malformed_responses_are_invalid(answer):
    with pytest.raises(EmbeddingError) as raised:
        client(FakeOpener(lambda payload: answer)).embed(["a"])
    assert raised.value.reason == "invalid_response"


def test_non_json_body_is_invalid():
    def opener(request, timeout):
        return io.BytesIO(b"<html>proxy error</html>")

    with pytest.raises(EmbeddingError) as raised:
        client(opener).embed(["a"])
    assert raised.value.reason == "invalid_response"


def test_wrong_dimensions_are_rejected():
    with pytest.raises(EmbeddingError) as raised:
        client(FakeOpener(lambda payload: vectors_for(payload, dimensions=5))).embed(["a"])
    assert raised.value.reason == "dimension_mismatch"


@pytest.mark.parametrize(
    "base_url",
    ["", "ftp://host/v1", "http://user:pass@host/v1", "http://host/v1?key=1", "http://host/v1#x", "host/v1"],
)
def test_unsafe_or_empty_base_urls_are_refused(base_url):
    assert conf.endpoint(base_url, "embeddings") is None
    with pytest.raises(EmbeddingError) as raised:
        OpenAICompatibleEmbeddings(base_url, "bge-m3", dimensions=3)
    assert raised.value.reason == "invalid_configuration"


def test_disabled_by_default():
    assert get_provider() is None
    assert semantic_search_enabled() is False


@override_settings(G5_AI_BASE_URL=BASE, G5_AI_EMBEDDING_MODEL="bge-m3", G5_AI_EMBEDDING_DIMENSIONS=1024,
                   G5_AI_TIMEOUT=999, G5_AI_EMBEDDING_BATCH_SIZE=-5, G5_AI_API_KEY="k")
def test_configured_provider_uses_bounded_settings():
    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleEmbeddings)
    assert (provider.model, provider.dimensions, provider.timeout, provider.batch_size) == ("bge-m3", 1024, 120, 1)
    assert get_provider(timeout=2).timeout == 2
    assert conf.query_timeout() == 3
    # The endpoint alone does not turn search on.
    assert semantic_search_enabled() is False
    with override_settings(G5_AI_SEMANTIC_SEARCH=True):
        assert semantic_search_enabled() is True


@override_settings(G5_AI_SEMANTIC_SEARCH=True, G5_AI_SEMANTIC_MIN_SIMILARITY="bad")
def test_override_provider_and_similarity_fallback():
    fake = FakeEmbeddingProvider()
    with provider_override(fake):
        assert get_provider() is fake
        assert semantic_search_enabled() is True
    assert get_provider() is None
    assert conf.min_similarity() == conf.DEFAULT_MIN_SIMILARITY
