"""ETag revalidation for read endpoints whose response is the same for every requester.

API responses to a request that carries cookies are normally ``Cache-Control: no-store, private``
(``G5SecurityHeadersMiddleware``), so a member's data never lands in a shared computer's disk
cache. Browsers send cookies with almost every request, which also means public data such as the
site settings or the category tree is downloaded again every time.

``shared_response_etag`` marks a view whose output does not depend on who asks (no
``request.user``, session or per-member fields). Its 200 responses get a content ETag and
``Cache-Control: private, no-cache``: the browser may keep the copy but must revalidate, and an
unchanged response comes back as an empty ``304 Not Modified``.

Never apply it to a view that reads the requester (menus by level, carts, posts with
``can_manage``/``is_scrapped``): the cached copy would be served to whoever asks next in that
browser.
"""

import hashlib
from functools import wraps

from django.utils.cache import get_conditional_response, quote_etag

SHARED_RESPONSE_CACHE_CONTROL = "private, no-cache"


def _mark_shared(response, etag):
    response["ETag"] = etag
    response["Cache-Control"] = SHARED_RESPONSE_CACHE_CONTROL
    # G5SecurityHeadersMiddleware keeps this Cache-Control instead of forcing no-store.
    response.shared_api_response = True
    return response


def shared_response_etag(view):
    """Decorate an ``@api_view`` function (place it between ``@extend_schema`` and ``@api_view``)."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD") or response.status_code != 200:
            return response
        if hasattr(response, "render") and not response.is_rendered:
            response.render()
        etag = quote_etag(hashlib.blake2b(response.content, digest_size=16).hexdigest())
        _mark_shared(response, etag)
        conditional = get_conditional_response(request, etag=etag, response=response)
        if conditional is not response:
            _mark_shared(conditional, etag)
        return conditional

    return wrapped
