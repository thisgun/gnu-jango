"""Compose first-screen data with the same permission rules as the individual GET APIs."""

import hashlib
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.http import QueryDict
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny

from .authentication import SessionJWTAuthentication
from .response import api_response

BOOTSTRAP_VERSION_KEY = "page-bootstrap:version:v1"
# Content writes start a new generation at once (register_bootstrap_invalidation), so the TTL only
# bounds time-based drift such as a banner's display window. Each rebuild costs ~70 queries.
BOOTSTRAP_TTL = 300
_change_batch = ContextVar("page_bootstrap_change_batch", default=None)


class ReadQueryRequest:
    """Override fixed read parameters without changing the original authenticated request."""

    def __init__(self, request, params):
        self._request_source = request
        self.query_params = QueryDict("", mutable=True)
        self.query_params.update({key: str(value) for key, value in params.items()})

    def __getattr__(self, name):
        return getattr(self._request_source, name)


def _data(builder, request, *, params=None, fallback=None, **kwargs):
    response = builder(ReadQueryRequest(request, params or {}), **kwargs)
    if response.status_code >= 400:
        return fallback
    return response.data.get("data", fallback)


def _reads_differ_from_a_guest(request):
    """Whether this visitor may read what an anonymous guest cannot.

    Members and token-bearing requests can. A guest can too after entering a secret post's or
    comment's password (session keys ss_secret_*, see access.secret_post_session_filters). Any other
    cookie (CSRF token, an empty or view-count-only session) changes nothing, and nearly every
    browser carries one, so it must not force a fresh build for each visitor.
    """
    if request.user.is_authenticated or request.headers.get("Authorization"):
        return True
    session = getattr(request, "session", None)
    if session is None:
        return False
    try:
        return any(value and str(key).startswith("ss_secret_") for key, value in session.items())
    except Exception:  # an unreadable session: do not risk sharing a personal view
        return True


def _shared_data(request, kind, build):
    # Visitors who may read more than a guest get their own build. Poll vote
    # state is also visitor-specific and is never stored in this shared snapshot.
    # A production worker's local cache cannot observe writes handled by another worker.
    # Keep those reads fresh unless the configured cache is shared (database/Redis).
    backend = settings.CACHES["default"]["BACKEND"]
    local_cache = backend in {
        "django.core.cache.backends.locmem.LocMemCache",
        "django.core.cache.backends.dummy.DummyCache",
        "django.core.cache.backends.filebased.FileBasedCache",
    }
    if (not settings.DEBUG and local_cache) or _reads_differ_from_a_guest(request):
        return build(request)
    version = cache.get(BOOTSTRAP_VERSION_KEY, "0")
    origin = hashlib.sha256(request.build_absolute_uri("/").encode()).hexdigest()[:16]
    key = f"page-bootstrap:v1:{kind}:{origin}:{version}"
    payload = cache.get(key)
    if payload is None:
        payload = build(request)
        cache.set(key, payload, BOOTSTRAP_TTL)
    return payload


def invalidate_page_bootstrap():
    """Make new reads use a new generation only after the database write has committed."""
    pending = _change_batch.get()
    if pending is not None:
        pending["dirty"] = True
        return
    transaction.on_commit(lambda: cache.set(BOOTSTRAP_VERSION_KEY, secrets.token_hex(12), None))


@contextmanager
def batch_bootstrap_changes():
    """Sample batches need one cache write after commit, rather than one per created row."""
    if _change_batch.get() is not None:
        yield
        return
    pending = {"dirty": False}
    token = _change_batch.set(pending)
    try:
        yield
    finally:
        _change_batch.reset(token)
    if pending["dirty"]:
        invalidate_page_bootstrap()


def _content_changed(sender, **kwargs):
    invalidate_page_bootstrap()


def register_bootstrap_invalidation():
    from django.apps import apps

    for label in (
        "config.Config", "bbs.Group", "bbs.Board", "bbs.Post", "bbs.Comment", "bbs.Post_file",
        "core.FAQMaster", "core.FAQItem", "core.SearchKeywordDaily",
        "shop.ShopCategory", "shop.ShopProduct", "shop.ShopBanner", "shop.ShopReview",
        "shop.ShopCoupon", "shop.ShopOrder", "shop.ShopOrderItem",
    ):
        model = apps.get_model(label)
        for name, signal in (("save", post_save), ("delete", post_delete)):
            signal.connect(_content_changed, sender=model, dispatch_uid=f"bootstrap:{name}:{label}", weak=False)


def _community_data(request):
    from . import v1_board, v1_community

    settings = _data(v1_community.settings_response, request, fallback={})
    boards = _data(v1_board.board_list_response, request, fallback=[])
    configured_gallery = (settings.get("cf_home_gallery") or "").strip()
    gallery_tables = {configured_gallery, "n_gallery", "gallery"}
    gallery_tables.update(
        board["bo_table"] for board in boards
        if re.search(r"gallery|갤러리", f'{board["bo_table"]} {board["bo_subject"]} {board.get("bo_skin", "")}', re.I)
    )
    galleries = [board for board in boards if board["bo_table"] in gallery_tables]
    gallery_board = next((board for board in galleries if board["bo_table"] == configured_gallery), None)
    if not configured_gallery:
        gallery_board = next((board for board in galleries if board.get("post_count", 0) > 0), None)
        gallery_board = gallery_board or next(iter(galleries), None)
    regular = [board for board in boards if board["bo_table"] not in gallery_tables]
    by_table = {board["bo_table"]: board for board in regular}
    configured = [by_table[table.strip()] for table in (settings.get("cf_home_boards") or "").split(",") if table.strip() in by_table]
    if not configured:
        candidates = [board for board in regular if board.get("post_count", 0) > 0] or regular
        configured, subjects = [], set()
        for board in sorted(candidates, key=lambda row: -row.get("post_count", 0)):
            subject = (board.get("bo_subject") or board["bo_table"]).strip().lower()
            if subject not in subjects:
                configured.append(board)
                subjects.add(subject)

    def posts(board, limit):
        return _data(v1_board.board_posts_response, request, params={"per_page": limit}, bo_table=board["bo_table"], fallback=[])

    gallery = None
    if gallery_board:
        gallery = {"board": gallery_board, "posts": [row for row in posts(gallery_board, 8) if row.get("thumbnail") or row.get("images")]}
    faq = _data(v1_community.faqs_response, request, params={"per_page": 4}, fallback={})
    return {
        "settings": settings,
        "boardPanels": [{"board": board, "posts": posts(board, 5)[:5]} for board in configured[:3]],
        "gallery": gallery,
        "faqs": faq.get("items", [])[:4],
        "comments": _data(v1_community.recent_response, request, params={"view": "c", "limit": 6}, fallback=[]),
        "popularKeywords": _data(v1_community.popular_search_response, request, params={"limit": 5, "days": 3}, fallback=[]),
        "visit": settings.get("visit"),
        "rewriteMode": settings.get("cf_bbs_rewrite", 0),
    }


def _shop_data(request):
    from gnu_jango.shop.shop_display import home_display

    from . import v1_board, v1_community, v1_shop
    from .shop_reviews import reviews_response

    boards = _data(v1_board.board_list_response, request, fallback=[])
    notice = next((board for board in boards if board["bo_table"] == "notice"), None)
    notice = notice or next((board for board in boards if "공지" in board.get("bo_subject", "")), None)
    # Admin display settings: a switched-off section is not fetched, the others fetch enough for the
    # larger of the PC (mod x row) and mobile layouts. Saving them writes Config rows, which starts
    # a new snapshot generation (register_bootstrap_invalidation).
    display = home_display()
    products = {
        key: _data(v1_shop.products_response, request, params={f"it_type{key[4:]}": 1}, limit=section["count"], fallback=[])
        if section["use"] else []
        for key, section in display.items()
    }
    # Catalog items without merchandising flags still have a truthful place on the home page,
    # in the hit section's slot, so only while that section is switched on.
    catalog_preview = (
        _data(v1_shop.products_response, request, limit=display["type1"]["count"], fallback=[])
        if display["type1"]["use"] and not any(products.values()) else []
    )
    return {
        "settings": _data(v1_community.settings_response, request, fallback={}),
        "categories": _data(v1_shop.categories_response, request, fallback=[]),
        "banners": _data(v1_shop.banners_response, request, params={"position": "메인", "device": "all"}, fallback=[]),
        "popups": _data(v1_shop.popups_response, request, params={"device": "all", "limit": 5}, fallback=[]),
        "products": products,
        "display": display,
        "catalogPreview": catalog_preview,
        "reviews": _data(reviews_response, request, params={"per_page": 12}, fallback=[]),
        "noticeBoard": notice,
        "noticePosts": _data(v1_board.board_posts_response, request, params={"per_page": 3}, bo_table=notice["bo_table"], fallback=[])[:3] if notice else [],
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([SessionJWTAuthentication, BasicAuthentication])
def community_home_view(request):
    from .community_polls import poll_current_response

    payload = dict(_shared_data(request, "community", _community_data))
    payload["poll"] = _data(poll_current_response, request)
    response = api_response(data=payload)
    # Server-side caching can be invalidated immediately. Do not cache a poll's voter state
    # or keep stale generated content in a browser/CDN after a sample-data operation.
    response["Cache-Control"] = "no-store, private"
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([SessionJWTAuthentication, BasicAuthentication])
def shop_home_view(request):
    response = api_response(data=_shared_data(request, "shop", _shop_data))
    response["Cache-Control"] = "no-store, private"
    return response
