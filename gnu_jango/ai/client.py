"""Embedding provider: an operator-configured OpenAI-compatible ``/embeddings`` endpoint.

Local development uses Ollama (``G5_AI_BASE_URL=http://127.0.0.1:11434/v1``, model ``bge-m3``).
Tests install a deterministic provider with :func:`provider_override`; they never call the network.
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
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(HTTPRedirectHandler):
    """urllib keeps the Authorization header across redirects; answer a redirect as an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener(request, timeout):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


class EmbeddingError(Exception):
    """A provider failure with a short machine-readable ``reason`` (never the key or a body)."""

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


class OpenAICompatibleEmbeddings:
    def __init__(self, base_url, model, *, dimensions, api_key="", timeout=conf.DEFAULT_TIMEOUT,
                 batch_size=conf.DEFAULT_BATCH_SIZE, opener=_default_opener):
        url = conf.endpoint(base_url, "embeddings")
        if not url or not str(model or "").strip():
            raise EmbeddingError("invalid_configuration")
        parts = urlsplit(url)
        if api_key and parts.scheme != "https" and (parts.hostname or "") not in LOOPBACK_HOSTS:
            raise EmbeddingError("insecure_configuration", "G5_AI_API_KEY is sent only over https or to this host.")
        self.url = url
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

    @sensitive_variables("headers", "api_key")
    def _post(self, payload):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = self._api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(self.url, data=body, headers=headers, method="POST")
        try:
            with self._opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise EmbeddingError("http_error", f"The embedding endpoint answered HTTP {exc.code}.") from None
        except (TimeoutError, socket.timeout) as exc:
            raise EmbeddingError("timeout") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise EmbeddingError("timeout") from exc
            raise EmbeddingError("unavailable") from exc
        except OSError as exc:
            raise EmbeddingError("unavailable") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise EmbeddingError("invalid_response") from exc


@contextmanager
def provider_override(provider):
    """Use ``provider`` instead of the configured endpoint (tests, smoke scripts)."""
    _override.append(provider)
    try:
        yield provider
    finally:
        _override.remove(provider)


@sensitive_variables("api_key")
def get_provider(*, timeout=None):
    """The active provider, or None when no embedding endpoint is configured.

    ``timeout`` overrides G5_AI_TIMEOUT (search passes the shorter G5_AI_QUERY_TIMEOUT).
    """
    if _override:
        return _override[-1]
    if not conf.embeddings_configured():
        return None
    from django.conf import settings

    api_key = str(getattr(settings, "G5_AI_API_KEY", "") or "").strip()
    return OpenAICompatibleEmbeddings(
        conf.base_url(), conf.embedding_model(), dimensions=conf.embedding_dimensions(), api_key=api_key,
        timeout=timeout or conf.timeout(), batch_size=conf.batch_size(),
    )


def semantic_search_enabled():
    return conf.semantic_search_requested() and get_provider() is not None
