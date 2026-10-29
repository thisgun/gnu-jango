"""Settings accessors for the optional AI features.

Nothing here performs I/O. With no ``G5_AI_*`` settings every helper reports "disabled", so the
site behaves exactly as it does without this app (the Vercel demos have no model).
"""
from urllib.parse import urlsplit

from django.conf import settings

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
DEFAULT_QUERY_TIMEOUT = 3
DEFAULT_BATCH_SIZE = 16
MAX_BATCH_SIZE = 256
DEFAULT_MAX_CHARS = 3000
DEFAULT_MIN_SIMILARITY = 0.5


def _text(name):
    return str(getattr(settings, name, "") or "").strip()


def _int(name, default, minimum, maximum):
    try:
        value = int(getattr(settings, name, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def endpoint(base_url, path):
    """Join an OpenAI-compatible base URL and a path, or None when the URL is unsafe.

    Same rule as docs_search/llm.py: http(s) only, a host, and no credentials, query or
    fragment in the URL (a key belongs in G5_AI_API_KEY, which is never logged).
    """
    base_url = str(base_url or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    return f"{base_url}/{path.lstrip('/')}"


def base_url():
    return _text("G5_AI_BASE_URL")


def embedding_model():
    return _text("G5_AI_EMBEDDING_MODEL")


def embedding_dimensions():
    return _int("G5_AI_EMBEDDING_DIMENSIONS", 1024, 1, 16000)


def timeout():
    return _int("G5_AI_TIMEOUT", DEFAULT_TIMEOUT, 1, MAX_TIMEOUT)


def query_timeout():
    """Search waits at most this long for the query embedding, then answers lexically."""
    return min(_int("G5_AI_QUERY_TIMEOUT", DEFAULT_QUERY_TIMEOUT, 1, MAX_TIMEOUT), timeout())


def batch_size():
    return _int("G5_AI_EMBEDDING_BATCH_SIZE", DEFAULT_BATCH_SIZE, 1, MAX_BATCH_SIZE)


def max_chars():
    return _int("G5_AI_EMBEDDING_MAX_CHARS", DEFAULT_MAX_CHARS, 200, 32000)


def min_similarity():
    try:
        value = float(getattr(settings, "G5_AI_SEMANTIC_MIN_SIMILARITY", DEFAULT_MIN_SIMILARITY))
    except (TypeError, ValueError):
        value = DEFAULT_MIN_SIMILARITY
    return max(-1.0, min(value, 1.0))


def semantic_search_requested():
    return bool(getattr(settings, "G5_AI_SEMANTIC_SEARCH", False))


def embeddings_configured():
    return bool(endpoint(base_url(), "embeddings") and embedding_model())
