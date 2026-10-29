"""AI providers: an operator-configured OpenAI-compatible endpoint (``/embeddings``, ``/chat/completions``).

Local development uses Ollama (``G5_AI_BASE_URL=http://127.0.0.1:11434/v1``, embedding model
``bge-m3``, chat model ``gemma4:e4b``). Tests install deterministic providers with
:func:`provider_override` and :func:`chat_provider_override`; they never call the network.
"""
import json
import logging
import socket
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.views.decorators.debug import sensitive_variables

from . import conf

logger = logging.getLogger(__name__)
_override = []
_chat_override = []
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(HTTPRedirectHandler):
    """urllib keeps the Authorization header across redirects; answer a redirect as an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener(request, timeout):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


class EndpointError(Exception):
    """A provider failure with a short machine-readable ``reason`` (never the key or a body)."""

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


class EmbeddingError(EndpointError):
    pass


class ChatError(EndpointError):
    pass


def _checked_url(base_url, path, model, api_key, error):
    url = conf.endpoint(base_url, path)
    if not url or not str(model or "").strip():
        raise error("invalid_configuration")
    parts = urlsplit(url)
    if api_key and parts.scheme != "https" and (parts.hostname or "") not in LOOPBACK_HOSTS:
        raise error("insecure_configuration", "G5_AI_API_KEY is sent only over https or to this host.")
    return url


@sensitive_variables("headers", "api_key")
def _post_json(opener, url, payload, *, api_key, timeout, error, label):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise error("http_error", f"The {label} endpoint answered HTTP {exc.code}.") from None
    except (TimeoutError, socket.timeout) as exc:
        raise error("timeout") from exc
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise error("timeout") from exc
        raise error("unavailable") from exc
    except OSError as exc:
        raise error("unavailable") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise error("invalid_response") from exc


class OpenAICompatibleEmbeddings:
    def __init__(self, base_url, model, *, dimensions, api_key="", timeout=conf.DEFAULT_TIMEOUT,
                 batch_size=conf.DEFAULT_BATCH_SIZE, opener=_default_opener):
        self.url = _checked_url(base_url, "embeddings", model, api_key, EmbeddingError)
        self.model = str(model).strip()
        self.dimensions = int(dimensions)
        self.timeout = timeout
        self.batch_size = max(1, int(batch_size))
        self._api_key = api_key
        self._opener = opener

    def __repr__(self):
        # Keep the key out of debug pages and logs that print the provider.
        return f"<OpenAICompatibleEmbeddings model={self.model!r} dimensions={self.dimensions}>"

    def embed(self, texts):
        """Return one vector per text, in order. Sends ``batch_size`` texts per request."""
        texts = [str(text or "") for text in texts]
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start:start + self.batch_size]))
        return vectors

    def _embed_batch(self, batch):
        if not batch:
            return []
        data = self._post({"model": self.model, "input": batch})
        try:
            rows = sorted(data["data"], key=lambda row: int(row["index"]))
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("invalid_response") from exc
        if len(vectors) != len(batch):
            raise EmbeddingError("invalid_response", "The provider returned a different number of vectors.")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise EmbeddingError(
                "dimension_mismatch",
                f"Expected {self.dimensions} dimensions; set G5_AI_EMBEDDING_DIMENSIONS to the model's size.",
            )
        return vectors

    def _post(self, payload):
        return _post_json(self._opener, self.url, payload, api_key=self._api_key, timeout=self.timeout,
                          error=EmbeddingError, label="embedding")


class OpenAICompatibleChat:
    """``complete(system, user)`` -> the assistant's text, from one non-streamed chat completion.

    ``reasoning_effort`` (G5_AI_CHAT_REASONING_EFFORT, default "none") turns the "thinking" of
    models such as gemma4 off: a short summary then takes about a second instead of ten. An empty
    value leaves the field out, for providers that reject it.
    """

    def __init__(self, base_url, model, *, api_key="", timeout=conf.DEFAULT_CHAT_TIMEOUT, reasoning_effort="none",
                 opener=_default_opener):
        self.url = _checked_url(base_url, "chat/completions", model, api_key, ChatError)
        self.model = str(model).strip()
        self.timeout = timeout
        self.reasoning_effort = str(reasoning_effort or "").strip()
        self._api_key = api_key
        self._opener = opener

    def __repr__(self):
        return f"<OpenAICompatibleChat model={self.model!r}>"

    def complete(self, system, user, *, max_tokens=400, temperature=0.2):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        data = _post_json(self._opener, self.url, payload, api_key=self._api_key, timeout=self.timeout,
                          error=ChatError, label="chat")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError("invalid_response") from exc
        if not isinstance(content, str) or not content.strip():
            raise ChatError("invalid_response", "The chat endpoint returned no text.")
        return content


@contextmanager
def provider_override(provider):
    """Use ``provider`` instead of the configured embedding endpoint (tests, smoke scripts)."""
    _override.append(provider)
    try:
        yield provider
    finally:
        _override.remove(provider)


@contextmanager
def chat_provider_override(provider):
    """Use ``provider`` instead of the configured chat model (tests, smoke scripts)."""
    _chat_override.append(provider)
    try:
        yield provider
    finally:
        _chat_override.remove(provider)


def _api_key():
    from django.conf import settings

    return str(getattr(settings, "G5_AI_API_KEY", "") or "").strip()


@sensitive_variables("api_key")
def get_provider(*, timeout=None):
    """The active embedding provider, or None when no embedding endpoint is configured.

    ``timeout`` overrides G5_AI_TIMEOUT (search passes the shorter G5_AI_QUERY_TIMEOUT).
    """
    if _override:
        return _override[-1]
    if not conf.embeddings_configured():
        return None
    api_key = _api_key()
    return OpenAICompatibleEmbeddings(
        conf.base_url(), conf.embedding_model(), dimensions=conf.embedding_dimensions(), api_key=api_key,
        timeout=timeout or conf.timeout(), batch_size=conf.batch_size(),
    )


@sensitive_variables("api_key")
def get_chat_provider(*, timeout=None):
    """The active chat provider, or None when G5_AI_BASE_URL or G5_AI_CHAT_MODEL is not set.

    ``timeout`` overrides G5_AI_CHAT_TIMEOUT (the admin briefing waits less than a background job).
    """
    if _chat_override:
        return _chat_override[-1]
    if not conf.chat_configured():
        return None
    api_key = _api_key()
    return OpenAICompatibleChat(
        conf.base_url(), conf.chat_model(), api_key=api_key, timeout=min(timeout or conf.chat_timeout(),
                                                                          conf.chat_timeout()),
        reasoning_effort=conf.chat_reasoning_effort(),
    )


def semantic_search_enabled():
    return conf.semantic_search_requested() and get_provider() is not None
