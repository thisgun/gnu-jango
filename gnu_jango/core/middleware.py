from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import DisallowedHost
from django.db import OperationalError, ProgrammingError
from django.db.models import F
from django.http import QueryDict
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.html import strip_tags

from .privacy import ip_address_for_storage, is_bot_user_agent, should_skip_user_agent


# How many earlier search requests of the same visitor today are checked for a repeated word.
SEARCH_REPEAT_LOOKBACK = 200

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"


def build_content_security_policy(*, unfold_admin=False, script_nonce=None):
    script_src = ["'self'", "https:", "http://t1.daumcdn.net"]
    if bool(getattr(settings, "G5_CSP_ALLOW_UNSAFE_SCRIPT", getattr(settings, "DEBUG", False))):
        script_src.extend(["'unsafe-inline'", "'unsafe-eval'"])
    elif unfold_admin:
        # Unfold bundles standard Alpine, which evaluates its HTML expressions.
        # Limit this compatibility permission to resolved Django admin views.
        script_src.append("'unsafe-eval'")
    if script_nonce:
        script_src.append(f"'nonce-{script_nonce}'")

    style_src = ["'self'", "'unsafe-inline'", "https:"]
    directives = [
        "default-src 'self'",
        "script-src " + " ".join(script_src),
        "style-src " + " ".join(style_src),
        "img-src 'self' data: blob: https: http:",
        "font-src 'self' data: https:",
        "connect-src 'self' http: https: ws: wss:",
        "frame-src 'self' https: http:",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
    ]
    return "; ".join(directives)


CONTENT_SECURITY_POLICY = build_content_security_policy()

PRIVATE_NOINDEX_PREFIXES = (
    "/admin",
    "/forgot-password",
    "/email-certify",
    "/login",
    "/members/",
    "/mypage",
    "/register",
    "/shop/cart",
    "/shop/order",
    "/shop/orders",
    "/shop/personalpay",
    "/shop/payment/success",
    "/shop/payment/fail",
    "/shop/wishlist",
)

PRIVATE_API_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/members/",
    "/api/v1/scraps",
    "/api/v1/memos",
    "/api/v1/notifications",
    "/api/v1/qas",
    "/api/v1/shop/cart",
    "/api/v1/shop/wishlist",
    "/api/v1/shop/addresses",
    "/api/v1/shop/orders",
    "/api/v1/shop/payment",
    "/api/v1/shop/coupons",
    "/api/v1/shop/points",
    "/api/v1/shop/reviews",
    "/api/v1/shop/personalpay",
    "/api/v1/boards",
    "/api/v1/posts",
    "/api/v1/polls",
)


PUBLIC_API_ASSET_PREFIXES = ("/api/v1/thumbs/",)

# Files that are the same for every visitor: build chunks, uploads, Gnuboard data, picture copies.
ASSET_PATH_PREFIXES = (
    "/_next/",
    # Gnuboard data folders only — a board may itself be called "data" (/data/<wr_id>).
    "/data/item/",
    "/data/banner/",
    "/data/event/",
    "/data/file/",
    "/data/coupon/",
    "/sample-data/",
    "/api/v1/thumbs/",
    "/sw.js",
    "/favicon.ico",
)


def is_asset_path(path):
    static_url = getattr(settings, "STATIC_URL", "/static/") or "/static/"
    media_url = getattr(settings, "MEDIA_URL", "/media/") or "/media/"
    return path.startswith((static_url, media_url, *ASSET_PATH_PREFIXES))


class AssetAwareSessionMiddleware(SessionMiddleware):
    """Django sessions, except that an asset request never saves or refreshes the session.

    SESSION_SAVE_EVERY_REQUEST keeps Gnuboard's sliding three-hour session, but it also saved the
    session and re-sent its cookie on every chunk and picture request (~30 per page). That cost a
    database write each, and the Set-Cookie / "Vary: Cookie" kept browsers and the CDN from
    caching the files. Page and API requests still refresh the session as before.
    """

    def process_response(self, request, response):
        if is_asset_path(unquote(getattr(request, "path", "") or "/")):
            return response
        return super().process_response(request, response)


class G5SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = unquote(getattr(request, "path", "") or "/")

        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        resolver_match = getattr(request, "resolver_match", None)
        unfold_admin = resolver_match is not None and (
            "admin" in resolver_match.app_names
            or resolver_match.url_name in {"admin-theme-settings", "admin-sample-data"}
        )
        policy = build_content_security_policy(unfold_admin=True) if unfold_admin else CONTENT_SECURITY_POLICY
        response.setdefault("Content-Security-Policy", policy)
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        if path.startswith(PUBLIC_API_ASSET_PREFIXES):
            # Signed picture copies are the same for everyone: keep the view's year-long cache even
            # when the browser sends cookies, and never vary on them (a CDN would not store it).
            response["Referrer-Policy"] = "no-referrer"
        elif path.startswith("/api/"):
            response["Referrer-Policy"] = "no-referrer"
            patch_vary_headers(response, ("Authorization", "Cookie"))
            if (
                request.COOKIES
                or request.headers.get("Authorization")
                or path.startswith(PRIVATE_API_PREFIXES)
                or response.status_code == 404
            ):
                response["Cache-Control"] = "no-store, private"
                response["Pragma"] = "no-cache"
        else:
            response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        if path.endswith(".txt") or path.startswith(PRIVATE_NOINDEX_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow"
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"

        if self._needs_cross_site_session_cookie(request) and settings.SESSION_COOKIE_NAME in response.cookies:
            response.cookies[settings.SESSION_COOKIE_NAME]["samesite"] = "None"
            response.cookies[settings.SESSION_COOKIE_NAME]["secure"] = True

        return response

    def _needs_cross_site_session_cookie(self, request):
        origin = request.headers.get("Origin") or ""
        if not origin:
            return False
        origin_host = urlparse(origin).netloc.lower()
        try:
            request_host = request.get_host().lower()
        except DisallowedHost:
            # the 400 handler answers a bad Host; the cookie tweak must not turn it into a 500
            return False
        if not origin_host or origin_host == request_host:
            return False
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        return request.is_secure() or forwarded_proto == "https" or origin.startswith("https://")


class VisitTrackingMiddleware:
    SEARCH_PARAM_NAMES = ("q", "query", "keyword", "stx", "s")
    SEARCH_PATH_MARKERS = ("/search", "/shop/search", "/api/v1/search")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = unquote(getattr(request, "path", "") or "/")
        logged_values = (
            path,
            request.META.get("QUERY_STRING") or "",
            request.headers.get("Referer") or "",
            request.headers.get("User-Agent") or "",
        )
        if any("\x00" in value for value in logged_values):
            return response
        if self._should_skip(path):
            return response
        user_agent = request.headers.get("User-Agent") or ""
        if should_skip_user_agent(user_agent):
            return response

        try:
            visit = self._record_visit(request, response, path)
            self._record_search_keywords(request, path, visit)
        except (OperationalError, ProgrammingError):
            pass
        return response

    def _should_skip(self, path):
        # Asset requests are not visits: logging them wrote ~30 rows per page (one per Next chunk).
        return is_asset_path(path) or path.startswith(("/robots.txt", "/admin/jsi18n/", "/__debug__/"))

    def _record_visit(self, request, response, path):
        from .models import VisitLog

        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            user = None
        session_key = ""
        if hasattr(request, "session"):
            session_key = request.session.session_key or ""

        return VisitLog.objects.create(
            user=user,
            session_key=session_key,
            ip_address=self._client_ip(request),
            method=(getattr(request, "method", "") or "GET")[:10],
            path=path[:500],
            query_string=(request.META.get("QUERY_STRING") or "")[:2000],
            referer=(request.headers.get("Referer") or "")[:2000],
            user_agent=(request.headers.get("User-Agent") or "")[:2000],
            device=self._device_label(request.headers.get("User-Agent") or ""),
            status_code=getattr(response, "status_code", 0) or 0,
            is_staff_area=path.startswith("/admin/"),
        )

    def _search_keyword(self, params, path):
        """The popular word of a search request, or "" when it is not one.

        search.php runs strip_tags() on the text first, and insert_popular() skips searches whose
        field list includes mb_id, which would otherwise publish member ids as popular words.
        """
        if not any(marker in path for marker in self.SEARCH_PATH_MARKERS):
            return ""
        fields = [field.strip() for field in str(params.get("sfl") or "").split("||")]
        if "mb_id" in fields:
            return ""
        for param_name in self.SEARCH_PARAM_NAMES:
            value = strip_tags(str(params.get(param_name) or "")).strip()
            if value:
                return " ".join(value.split())[:255]
        return ""

    def _searched_today_already(self, visit, source, keyword):
        """insert_popular() keeps one row per word, day and address (unique pp_date, pp_word,
        pp_ip), so a visitor repeating a search does not raise the word. The visit log holds the
        earlier requests of the same address (and session) today."""
        from .models import VisitLog

        if visit is None or not (visit.ip_address or visit.session_key):
            return False
        day_start = timezone.localtime(visit.created_at).replace(hour=0, minute=0, second=0, microsecond=0)
        earlier = (
            VisitLog.objects.filter(
                ip_address=visit.ip_address,
                session_key=visit.session_key,
                created_at__gte=day_start,
                pk__lt=visit.pk,
                path__contains="/search",
            )
            .order_by("-pk")
            .values_list("path", "query_string")[:SEARCH_REPEAT_LOOKBACK]
        )
        for path, query_string in earlier:
            if self._search_source(path) != source:
                continue
            if self._search_keyword(QueryDict(query_string or ""), path) == keyword:
                return True
        return False

    def _record_search_keywords(self, request, path, visit=None):
        keyword = self._search_keyword(request.GET, path)
        if not keyword:
            return

        from .models import SearchKeyword, SearchKeywordDaily

        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            user = None
        now = timezone.now()
        source = self._search_source(path)
        keyword_row, _created = SearchKeyword.objects.get_or_create(
            source=source,
            keyword=keyword,
            defaults={
                "count": 0,
                "last_user": user,
                "last_ip_address": self._client_ip(request),
                "first_searched_at": now,
                "last_searched_at": now,
            },
        )
        SearchKeyword.objects.filter(pk=keyword_row.pk).update(
            count=F("count") + 1,
            last_user=user,
            last_ip_address=self._client_ip(request),
            last_searched_at=now,
        )

        if self._searched_today_already(visit, source, keyword):
            return
        daily_row, _created = SearchKeywordDaily.objects.get_or_create(
            source=source,
            keyword=keyword,
            day=timezone.localdate(now),
            defaults={"count": 0},
        )
        SearchKeywordDaily.objects.filter(pk=daily_row.pk).update(count=F("count") + 1)

    def _client_ip(self, request):
        forwarded_for = request.headers.get("X-Forwarded-For") or ""
        if forwarded_for:
            return ip_address_for_storage(forwarded_for.split(",", 1)[0].strip())
        return ip_address_for_storage(request.META.get("REMOTE_ADDR"))

    def _device_label(self, user_agent):
        normalized = user_agent.lower()
        if is_bot_user_agent(normalized):
            return "bot"
        if "mobile" in normalized or "android" in normalized or "iphone" in normalized:
            return "mobile"
        if "tablet" in normalized or "ipad" in normalized:
            return "tablet"
        return "desktop"

    def _search_source(self, path):
        if path.startswith("/admin/"):
            return "admin"
        if path.startswith("/shop/"):
            return "shop"
        if path.startswith("/api/"):
            return "api"
        return "site"
