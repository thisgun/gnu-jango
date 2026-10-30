from pathlib import Path, PurePosixPath, PureWindowsPath

import json
import mimetypes
import posixpath
import re
import secrets
from html import escape
from urllib.parse import quote

from django.shortcuts import render
from django.http import Http404, HttpResponse
from django.conf import settings
from django.utils.feedgenerator import Rss201rev2Feed
from django.template import loader
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.views.static import serve

from gnu_jango.bbs.models import Group, Board, Post
from gnu_jango.shop.models import ShopCategory
from gnu_jango.config import config
from gnu_jango.config.theme_settings import theme_settings_for
from gnu_jango.config.sample_data import SAMPLE_ASSET_SIZES
from gnu_jango.core.legacy_assets import legacy_area_roots
from gnu_jango.core.navigation import navigation_boards, site_menu_items

from gnu_jango.utils.add_sample import add_sample_data
from gnu_jango.utils import lib
from django.views.generic.base import View, TemplateResponseMixin, ContextMixin
from django.utils import timezone

from .models import New_win
from .middleware import build_content_security_policy
from .legacy_redirects import (  # noqa: F401 - views and urls address these through this module
    BOARD_URL_PREFIX,
    board_clean_segments,
    board_url,
    LEGACY_DATA_ALLOWED_AREAS,
    LEGACY_GNUBOARD5_BASE_URL,
    LEGACY_SAFE_SEGMENT_RE,
    LEGACY_SHOP_ORIGINAL_PHP_ROOTS,
    LEGACY_SHOP_PASS_THROUGH_ROOT_FILES,
    _legacy_board_path,
    _legacy_clean_segments,
    _legacy_encoded_path,
    _legacy_first_param,
    _legacy_has_flag,
    _legacy_local_redirect,
    _legacy_memo_type,
    _legacy_mobile_shop_route,
    _legacy_php_redirect,
    _legacy_product_path,
    _legacy_query,
    _legacy_redirect_response,
    _legacy_safe_relative_redirect,
    _legacy_shop_file_redirect,
    legacy_bbs_php_route,
    legacy_mobile_route,
    legacy_shop_php_route,
)


NEXTJS25_FALLBACK_IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
NEXTJS25_BOARD_TABLE_ALIASES = {"cm_free": "free"}


# Gnuboard5 data/.htaccess (install/install_db.php) denies these names anywhere under data/.
LEGACY_DATA_DENIED_NAME_RE = re.compile(
    r"\.(htaccess|htpasswd|php|pht|s?p?html?|inc|cgi|pl|phar|svgz?)", re.IGNORECASE
)
NEXTJS25_THEME_TEMPLATE_DIR = "theme/nextjs_default"
NEXTJS_DEFAULT_THEME = "nextjs_default"
NEXTJS_THEME_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
# RFC 3986 path-segment characters other than unreserved letters/digits (sitemap <loc>).
URI_SEGMENT_SAFE = "!$&'()*+,;=:@-._~"
CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _error_response(template_name, status):
    # The error pages are static.  Rendering them without the request keeps the handlers
    # working when a middleware failed before request.user was set (e.g. a disallowed Host).
    return HttpResponse(render_to_string(template_name), status=status)


def error_400(request, exception):
    return _error_response("400.html", 400)


def error_403(request, exception):
    return _error_response("403.html", 403)


def error_404(request, exception):
    return _error_response("404.html", 404)


def error_500(request):
    return _error_response("500.html", 500)

NEXTJS25_EXACT_ROOT_TEMPLATE_PATHS = {
    "index",
    "login",
    "login/social-callback",
    "register",
    "register/result",
    "forgot-password",
    "email-certify",
    "boards",
    "faq",
    "polls",
    "recent",
    "search",
    "baby",
    "offline",
    "shop",
    "shop/cart",
    "shop/couponzone",
    "shop/compare",
    "shop/events",
    "shop/largeimage",
    "shop/order",
    "shop/orders",
    "shop/payment/fail",
    "shop/payment/success",
    "shop/personalpay",
    "shop/products",
    "shop/qas",
    "shop/reviews",
    "shop/search",
    "shop/wishlist",
    "mypage",
    "mypage/addresses",
    "mypage/comments",
    "mypage/coupons",
    "mypage/memos",
    "mypage/memos/new",
    "mypage/orders",
    "mypage/password",
    "mypage/points",
    "mypage/posts",
    "mypage/profile",
    "mypage/qas",
    "mypage/qas/new",
    "mypage/reviews",
    "mypage/scraps",
    "mypage/sessions",
    "mypage/shop-qas",
    "mypage/wishlist",
}


def _safe_relative_path(value):
    """Return value as a relative "a/b" path, or None when it could leave its base folder.

    Both separators count, and "..", drive letters ("C:"), colons, NUL and other control
    characters are refused, so the result can be joined to any root on any OS.
    """
    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized or ":" in normalized or CONTROL_CHARACTERS_RE.search(normalized):
        return None
    if PureWindowsPath(normalized).drive or PurePosixPath(normalized).is_absolute():
        return None
    if ".." in normalized.split("/"):
        return None
    return normalized


def _is_nextjs_export(name):
    """Whether theme/<name> is a complete Next.js export: its pages and its theme_static/<name>/_next/static."""
    if not NEXTJS_THEME_NAME_RE.fullmatch(str(name or "")):
        return False
    root = Path(settings.TEMPLATES_DIR)
    return (root / "theme" / name / "index.html").is_file() and (root / "theme_static" / name / "_next" / "static").is_dir()


def _nextjs_theme_name():
    """Folder name under theme/ of the Next.js export that serves the site.

    The active theme (cf_theme) when it is an installed export. nextjs25, the classic themes and a
    folder that is not a complete export keep being served from nextjs_default, as before.
    """
    name = str(getattr(config, "cf_theme", "") or "")
    if name not in {"", "nextjs25", NEXTJS_DEFAULT_THEME} and _is_nextjs_export(name):
        return name
    return NEXTJS_DEFAULT_THEME


def _theme_template_dir():
    return f"theme/{_nextjs_theme_name()}"


def _clean_nextjs25_template_path(template_path):
    raw_path = str(template_path or "").replace("\\", "/").strip("/")
    if not raw_path or raw_path == ".":
        return "index"
    clean_path = _safe_relative_path(raw_path)
    if clean_path is None:
        raise Http404("Template not found")
    # The static export must stay inside the theme directory.
    template_dir = _theme_template_dir()
    resolved = posixpath.normpath(f"{template_dir}/{clean_path}")
    if not resolved.startswith(f"{template_dir}/"):
        raise Http404("Template not found")
    return clean_path


def _nextjs25_find_template(candidates):
    """First existing template name, or None.  A name the file system cannot hold (too long,
    NUL, a Windows colon) is a missing page, not a server error."""
    for template_name in candidates:
        try:
            loader.get_template(template_name)
        except (TemplateDoesNotExist, OSError, ValueError):
            continue
        return template_name
    return None


def _nextjs25_public_metadata_path(path):
    clean_path = (path or "/").split("?", 1)[0].strip("/")
    if not clean_path:
        return "/"
    parts = clean_path.split("/")
    if parts[0] == "boards":
        # The internal /boards route is published under /bbs.
        return "/".join([BOARD_URL_PREFIX, *parts[1:]])
    if parts[0] == "shop" and len(parts) >= 3:
        if parts[1] == "products":
            return "/shop/" + "/".join(parts[2:])
        if parts[1] == "categories":
            return f"/shop/list-{parts[2]}"
    return "/" + clean_path


def _rewrite_nextjs25_runtime_config(content, request):
    origin = request.build_absolute_uri("/").rstrip("/")
    api_base_url = request.build_absolute_uri("/api/v1").rstrip("/")
    built_canonical = re.search(
        r'<link\b(?=[^>]*\brel=["\']canonical["\'])[^>]*\bhref=["\'](https?://[^/"\']+)',
        content,
        flags=re.I,
    )
    built_origin = built_canonical.group(1) if built_canonical else ""
    if not built_origin:
        built_og_image = re.search(r'(https?://[^/"\s]+)/(?:og-default\.png)', content)
        if built_og_image:
            built_origin = built_og_image.group(1)
    if built_origin:
        if built_origin != origin:
            content = content.replace(built_origin, origin)
    current_path = request.path or "/"
    if current_path.endswith(".txt"):
        current_path = current_path[:-4] or "/"
    metadata_path = _nextjs25_public_metadata_path(current_path)
    public_query = request.GET.copy()
    for key in list(public_query.keys()):
        if key.startswith("utm_") or key in {
            "_rsc",
            "legacy-shop-passthrough-smoke",
            "metadata-smoke",
            "runtime-noindex-check",
            "runtime-public-asset-check",
        }:
            public_query.pop(key, None)
    current_url = request.build_absolute_uri(metadata_path)
    if metadata_path != "/":
        current_url = current_url.rstrip("/")
    public_query_string = public_query.urlencode()
    if public_query_string:
        current_url = f"{current_url}?{public_query_string}"
    runtime_config = {
        "currentPath": current_path,
        "apiBaseUrl": api_base_url,
        "g5BaseUrl": origin,
        "appBaseUrl": origin,
    }
    # What differs per installation but cannot be baked into the shared export (the handbook theme's
    # manual group). The default theme needs none, so its pages stay as they were.
    theme_settings = theme_settings_for(_nextjs_theme_name(), config.get_all())
    if theme_settings is not None:
        runtime_config["themeSettings"] = theme_settings
    # The site's own menus and public boards: menus baked into the export at build time belong to
    # the build machine's database and point at boards other installations do not have.
    runtime_config["menus"] = site_menu_items(current_path, getattr(request, "user", None))
    runtime_config["navBoards"] = navigation_boards()
    replacements = {
        "https://your-django-api.example.com/api/v1": api_base_url,
        "https://your-django-api.example.com": origin,
        "https://your-vercel-app.example.com": origin,
        "https:\\/\\/your-django-api.example.com\\/api\\/v1": api_base_url.replace("/", "\\/"),
        "https:\\/\\/your-django-api.example.com": origin.replace("/", "\\/"),
        "https:\\/\\/your-vercel-app.example.com": origin.replace("/", "\\/"),
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    runtime_prefix = "window.__G5_NEXTJS25_CONFIG__ = Object.assign({"
    if runtime_prefix in content and '"currentPath"' not in content:
        prefix_index = content.find(runtime_prefix)
        prefix_end = prefix_index + len(runtime_prefix)
        current_path_config = f'"currentPath":{_nextjs25_script_json(current_path)},'
        if content[prefix_end : prefix_end + 2] == '\\"':
            current_path_config = current_path_config.replace('"', '\\"')
        content = content[:prefix_end] + current_path_config + content[prefix_end:]

    direct_config_script = (
        "<script>window.__G5_NEXTJS25_CONFIG__ = "
        f"{_nextjs25_script_json(runtime_config)};</script>"
    )
    object_assign_script = "<script>window.__G5_NEXTJS25_CONFIG__ = Object.assign"
    if object_assign_script in content and "window.__G5_NEXTJS25_CONFIG__ = {" not in content:
        content = content.replace(object_assign_script, direct_config_script + object_assign_script, 1)

    escaped_current_url = escape(current_url, quote=True)

    # Callables, so a backslash in the URL is never read as a regex group reference.
    def with_html_url(match):
        return f"{match.group(1)}{escaped_current_url}{match.group(2)}"

    def with_json_url(match):
        return f"{match.group(1)}{_nextjs25_script_json(current_url)[1:-1]}{match.group(2)}"

    content = re.sub(r'(<meta\s+property="og:url"\s+content=")[^"]*(")', with_html_url, content)
    content = re.sub(r'(<link\s+rel="canonical"\s+href=")[^"]*(")', with_html_url, content)
    if not re.search(r'<link\b(?=[^>]*\brel=["\']canonical["\'])[^>]*>', content, flags=re.I):
        content = content.replace("</head>", f'<link href="{escaped_current_url}" rel="canonical"/></head>', 1)
    content = re.sub(r'("property":"og:url","content":")[^"]*(")', with_json_url, content)
    if not re.search(r'<meta\b(?=[^>]*\bproperty=["\']og:url["\'])[^>]*>', content, flags=re.I):
        content = content.replace("</head>", f'<meta property="og:url" content="{escaped_current_url}"/></head>', 1)
    return content


def _nextjs25_script_json(value):
    # Runtime paths are request input: keep them inside the script's JSON value.
    return json.dumps(value, separators=(",", ":")).translate(
        str.maketrans({"<": "\\u003C", ">": "\\u003E", "&": "\\u0026"})
    )


def _render_nextjs25_template(request, template_path):
    clean_path = _clean_nextjs25_template_path(template_path)
    template_name = _nextjs25_find_template(
        [
            f"{_theme_template_dir()}/{clean_path}.html",
            f"{_theme_template_dir()}/{clean_path}/index.html",
        ]
    )
    if template_name is None:
        raise Http404("Template not found")
    content = render_to_string(template_name, {"IS_NEXTJS25_THEME": True}, request=request)
    content = _rewrite_nextjs25_runtime_config(content, request)
    # Django serves trusted export files dynamically, including Next's inline
    # bootstrap and the request-specific runtime config. Authorize this response
    # with a fresh nonce instead of enabling arbitrary inline scripts.
    nonce = secrets.token_urlsafe(24)
    content = re.sub(r"<script\b", lambda match: f'{match.group(0)} nonce="{nonce}"', content, flags=re.I)
    response = HttpResponse(content)
    response["Content-Security-Policy"] = build_content_security_policy(script_nonce=nonce)
    return response


def _render_nextjs25_text_payload(request, template_path):
    clean_path = _clean_nextjs25_template_path(template_path)
    template_name = _nextjs25_find_template(
        [
            f"{_theme_template_dir()}/{clean_path}.txt",
            f"{_theme_template_dir()}/{clean_path}/index.txt",
        ]
    )
    if template_name is None:
        raise Http404("Payload not found")
    content = render_to_string(template_name, {"IS_NEXTJS25_THEME": True}, request=request)
    content = _rewrite_nextjs25_runtime_config(content, request)
    return HttpResponse(content, content_type="text/x-component; charset=utf-8")


def _nextjs25_public_scope(request):
    script_name = request.META.get("SCRIPT_NAME", "").rstrip("/")
    return f"{script_name}/" if script_name else "/"


def _nextjs25_public_path(request, path):
    scope = _nextjs25_public_scope(request).rstrip("/")
    normalized = path if path.startswith("/") else f"/{path}"
    return f"{scope}{normalized}" if scope else normalized


def _nextjs25_manifest_response(request, path):
    manifest_path = settings.TEMPLATES_DIR / "theme" / _nextjs_theme_name() / path
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        manifest = {
            "name": "Gnuboard5 Community",
            "short_name": "Gnuboard5",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#2563eb",
            "icons": [],
        }

    manifest["start_url"] = _nextjs25_public_scope(request)
    manifest["scope"] = _nextjs25_public_scope(request)
    manifest["icons"] = [
        {
            **icon,
            "src": _nextjs25_public_path(request, icon.get("src", "")),
        }
        for icon in manifest.get("icons", [])
        if isinstance(icon, dict) and icon.get("src")
    ]
    content_type = "application/manifest+json" if path.endswith(".webmanifest") else "application/json"
    return HttpResponse(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        content_type=f"{content_type}; charset=utf-8",
    )


def _nextjs25_robots_response(request):
    origin = request.build_absolute_uri("/").rstrip("/")
    lines = [
        "User-Agent: *",
        "Allow: /",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /forgot-password",
        "Disallow: /email-certify",
        "Disallow: /mypage",
        "Disallow: /admin",
        "Disallow: /api",
        "Disallow: /shop/cart",
        "Disallow: /shop/order",
        "Disallow: /shop/orders",
        "Disallow: /shop/payment",
        "Disallow: /shop/personalpay",
        "Disallow: /shop/search",
        "Disallow: /shop/subscriptions",
        "Disallow: /shop/wishlist",
        "",
        f"Host: {origin}",
        f"Sitemap: {origin}/sitemap.xml",
        f"Sitemap: {origin}/sitemap-posts.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


def _nextjs25_sitemap_urlset(request, paths):
    origin = request.build_absolute_uri("/").rstrip("/")
    urls = []
    for path in paths:
        normalized = path if path.startswith("/") else f"/{path}"
        # Sitemaps need RFC 3986 URLs: anything outside the path characters is %-escaped,
        # already-escaped "%XX" sequences are kept.
        encoded = quote(normalized, safe=URI_SEGMENT_SAFE + "/%")
        urls.append(f"<url><loc>{escape(origin + encoded)}</loc></url>")
    body = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            *urls,
            "</urlset>",
            "",
        ]
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")


def _nextjs25_sitemap_response(request):
    paths = [
        "/",
        BOARD_URL_PREFIX,
        "/faq",
        "/recent",
        "/search",
        "/shop",
        "/shop/products",
        "/shop/events",
        "/shop/couponzone",
        "/polls",
        "/content/company",
        "/content/privacy",
        "/content/provision",
    ]
    from gnu_jango.api.shop_common import on_sale_products

    categories = ShopCategory.objects.filter(ca_use=True).order_by("ca_order", "ca_id")[:100]
    # YoungCart item.php hides a product whose category is switched off (ca_use) as well.
    products = on_sale_products().order_by("-created_at", "it_id")[:100]
    paths.extend(f"/shop/list-{quote(category.ca_id, safe=URI_SEGMENT_SAFE)}" for category in categories)
    paths.extend(f"/shop/{quote(product.it_id, safe=URI_SEGMENT_SAFE)}" for product in products)
    return _nextjs25_sitemap_urlset(request, dict.fromkeys(paths))


def _nextjs25_posts_sitemap_response(request):
    # Only posts a guest may open: boards a guest (level 1) can list and read, outside
    # access-restricted groups (bbs/rss.php and board.php), and never secret posts.
    posts = (
        Post.objects.select_related("board")
        .filter(board__bo_read_level__lt=2, board__bo_list_level__lt=2)
        .exclude(board__group__gr_use_access__gt=0)
        .exclude(wr_option__contains="secret")
        .order_by("-wr_datetime", "-pk")[:500]
    )
    paths = [post.get_absolute_url() for post in posts]
    return _nextjs25_sitemap_urlset(request, dict.fromkeys(paths))


def _map_nextjs25_root_template_path(template_path):
    clean_path = _clean_nextjs25_template_path(template_path)
    parts = clean_path.split("/")
    first = parts[0]

    if clean_path in NEXTJS25_EXACT_ROOT_TEMPLATE_PATHS:
        return clean_path

    if first == "boards":
        if len(parts) == 1:
            return "boards"
        if len(parts) == 3 and parts[2] == "write":
            return "boards/__g5_static__/write"
        if len(parts) >= 3:
            return "boards/__g5_static__/0"
        return "boards/__g5_static__"

    if first == "content" and len(parts) >= 2:
        return "content/__g5_static__"

    if first == "members" and len(parts) >= 2:
        return "members/__g5_static__"

    if first == "mypage":
        if len(parts) == 1:
            return "mypage"
        if parts[1] == "qas" and len(parts) >= 3:
            return "mypage/qas/new" if parts[2] == "new" else "mypage/qas/0"
        if parts[1] == "memos" and len(parts) >= 3:
            return "mypage/memos/new" if parts[2] == "new" else "mypage/memos/0"
        return clean_path

    if first == "shop":
        if len(parts) == 1:
            return "shop"
        section = parts[1]
        if clean_path in NEXTJS25_EXACT_ROOT_TEMPLATE_PATHS:
            return clean_path
        if section.startswith("list-") or section == "categories":
            return "shop/categories/__g5_static__"
        if section.startswith("type-"):
            return "shop/products"
        if section == "products" and len(parts) >= 3:
            return "shop/products/__g5_static__"
        if section == "orders" and len(parts) >= 3:
            return "shop/orders/__g5_static__"
        if section == "events" and len(parts) >= 3:
            return "shop/events/0"
        if section == "personalpay" and len(parts) >= 3:
            if len(parts) >= 4 and parts[3] == "pay":
                return "shop/personalpay/__g5_static__/pay"
            return "shop/personalpay/__g5_static__"
        if len(parts) == 2:
            return "shop/products/__g5_static__"
        return clean_path

    return clean_path


# Create your views here.
# INDEX 화면
def index(request):
    request.user.is_user = True if request.user.is_authenticated else False
    request.user.is_guest = not request.user.is_user
    request.user.is_admin = True if request.user.is_superuser else False
    request.user.is_auth = request.user.is_admin
    request.user.is_mobile = lib.is_mobile(request)
    request.user.member = {}

    boards = Board.objects.all()

    # print( timezone.now() )
    # 최초 install 인지 체크한다.
    if not boards:
        from gnu_jango.config.models import Config

        configs = Config.objects.all()
        if not configs:
            groups = Group.objects.all()
            if not groups:

                # 환경설정 값도 없고 그룹값도 없고 BOARD값도 없으면 그룹과 공지사항, 질문답변, 자유게시판, 갤러리 게시판을 생성합니다.
                boards = add_sample_data()

    context = {
        "boards": boards,
        "IS_INDEX_PAGE": True,
    }

    # template = loader.get_template(
    #     "theme/" + getattr(config, "cf_theme", "basic") + "/index.html"
    # )

    # return HttpResponse(template.render(context, request))

    popup_render = popup_newwin(request)
    # popup_render.render()
    # popup_content = popup_render.rendered_content
    popup_content = popup_render

    context.update(
        {
            "popup_content": popup_content,
        }
    )

    theme_name = getattr(config, "cf_theme", "basic")
    if theme_name in {"nextjs25", NEXTJS_DEFAULT_THEME} or _is_nextjs_export(theme_name):
        return _render_nextjs25_template(request, "index")

    return render(
        request,
        "theme/" + theme_name + "/index.html",
        context,
    )


def popup_newwin(request):
    pop_division = "comm"

    # datetime_value = defaults.TIME_YMDHIS

    # datetime_value = defaults.SERVER_TIME

    datetime_value = timezone.now()

    newwin_result = New_win.objects.filter(
        nw_begin_time__lte=datetime_value,
        nw_end_time__gte=datetime_value,
        nw_device__in=["both", "mobile"],
        nw_division__in=["both", pop_division],
    ).order_by("pk")

    context = {
        "newwin_result": newwin_result,
    }

    # return render(
    #     request,
    #     "theme/" + getattr(config, "cf_theme", "basic") + "/popup.html",
    #     context,
    # )

    try:
        return render_to_string(
            "theme/" + getattr(config, "cf_theme", "basic") + "/popup.html", context, request=request
        )
    except TemplateDoesNotExist:
        return ""


def nextjs25_theme(request, template_path=""):
    return _render_nextjs25_template(request, template_path)


def nextjs25_root_theme(request, template_path=""):
    mapped_path = _map_nextjs25_root_template_path(template_path)
    return _render_nextjs25_template(request, mapped_path)


def nextjs25_root_text_payload(request, template_path=""):
    mapped_path = _map_nextjs25_root_template_path(template_path)
    return _render_nextjs25_text_payload(request, mapped_path)


def nextjs25_boards_canonical_redirect(request, board_path=""):
    """/boards[/...] (the internal Next.js route) moves to the public /bbs/... address."""
    segments = board_clean_segments(board_path)
    if not segments:
        return _legacy_local_redirect(request, BOARD_URL_PREFIX, status_code=308)
    if len(segments) == 2 and segments[1].lower() == "rss":
        return _legacy_local_redirect(request, f"/rss/{quote(segments[0], safe='')}", status_code=308)
    return _legacy_local_redirect(request, board_url(*segments), status_code=308)


def nextjs25_shop_products_canonical_redirect(request, product_path=""):
    if not product_path:
        for item_type in range(1, 6):
            key = f"it_type{item_type}"
            if _legacy_has_flag(request, [key]):
                return _legacy_local_redirect(request, f"/shop/type-{item_type}", drop=[key], status_code=308)
        return nextjs25_root_theme(request, "shop/products")

    segments = _legacy_clean_segments(product_path)
    if not segments:
        return nextjs25_root_theme(request, "shop/products")
    target = "/shop/" + "/".join(quote(segment, safe="") for segment in segments)
    return _legacy_local_redirect(request, target, status_code=308)


def nextjs25_shop_categories_canonical_redirect(request, category_path):
    segments = _legacy_clean_segments(category_path)
    if not segments:
        return nextjs25_root_theme(request, "shop/products")
    target = f"/shop/list-{quote(segments[0], safe='')}"
    return _legacy_local_redirect(request, target, status_code=308)


def _rss_item_description(post):
    """bbs/rss.php conv_content($content, $html): an html post keeps its (sanitized) markup,
    a plain-text post is escaped with its spacing and line breaks kept."""
    content = post.wr_content or ""
    if "html" in (post.wr_option or ""):
        from gnu_jango.utils.sanitize import sanitize_html

        return sanitize_html(content)
    text = escape(content, quote=True).replace("\r\n", "\n")
    text = text.replace("  ", "&nbsp; ").replace("\n ", "\n&nbsp;")
    return text.replace("\n", "<br/>")


def nextjs25_board_rss(request, bo_table):
    board_key = NEXTJS25_BOARD_TABLE_ALIASES.get(bo_table, bo_table)
    board = Board.objects.filter(bo_table=board_key).first()
    if not board:
        raise Http404("Board not found")
    if not board.bo_use_rss_view or board.bo_read_level >= 2:
        raise Http404("RSS feed is unavailable")

    site_title = getattr(config, "cf_title", "Gnuboard5")
    board_title = board.bo_subject or board.bo_table
    feed = Rss201rev2Feed(
        title=f"{site_title} - {board_title}",
        link=request.build_absolute_uri(board_url(board.bo_table)),
        description=f"{board_title} RSS",
        language="ko",
    )
    posts = (
        Post.objects.filter(board=board)
        .exclude(wr_option__contains="secret")
        .order_by("-wr_datetime", "-pk")[: max(int(board.bo_page_rows or 15), 1)]
    )
    for post in posts:
        feed.add_item(
            title=post.wr_subject or "",
            link=request.build_absolute_uri(post.get_absolute_url()),
            description=_rss_item_description(post),
            author_name=post.wr_name or "",
            pubdate=post.wr_datetime,
        )
    return HttpResponse(feed.writeString("utf-8"), content_type="application/rss+xml; charset=utf-8")


def _nextjs25_board_template(bo_table, board_path):
    """Exported placeholder page of a board address; a board that does not exist is a 404."""
    board_key = NEXTJS25_BOARD_TABLE_ALIASES.get(bo_table, bo_table)
    if not Board.objects.filter(bo_table=board_key).exists():
        raise Http404("Board not found")
    if board_path == "write":
        return "boards/__g5_static__/write"
    if board_path:
        return "boards/__g5_static__/0"
    return "boards/__g5_static__"


def nextjs25_board_theme(request, bo_table, board_path=""):
    """/bbs/<bo_table>[/<wr_id>|/<seo-title>/|/write]: the board pages of the Next.js site."""
    return _render_nextjs25_template(request, _nextjs25_board_template(bo_table, board_path))


def nextjs25_board_text_payload(request, bo_table, board_path=""):
    return _render_nextjs25_text_payload(request, _nextjs25_board_template(bo_table, board_path))


def nextjs25_short_board_redirect(request, bo_table, board_path=""):
    """The old short addresses (/<bo_table>[/<wr_id>]) move to /bbs/... for good."""
    _nextjs25_board_template(bo_table, board_path)  # 404 for an address that is not a board
    target = board_url(bo_table, board_path) if board_path else board_url(bo_table)
    if board_path and request.path.endswith("/"):
        target += "/"  # an SEO-title post address keeps its trailing slash
    return _legacy_local_redirect(request, target, status_code=308)


# Next names every file under these folders after its content, so a new build never reuses a name.
# The build-id folder (_buildManifest.js) keeps one name across builds and must be revalidated.
NEXT_HASHED_STATIC_DIRS = ("chunks/", "css/", "media/")
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, s-maxage=31536000, immutable"


def _next_static_roots():
    """_next/static folders of the installed Next.js exports, the active theme's first.

    A theme's files are named after their content (and its build-id folder after the theme), so
    one theme never shadows another's; looking in every export lets a theme that is not active be
    previewed and keeps already-open pages of the previous theme working after a switch.
    """
    theme_static = Path(settings.TEMPLATES_DIR) / "theme_static"
    active = _nextjs_theme_name()
    roots = [theme_static / active / "_next" / "static"]
    try:
        others = sorted(p.name for p in theme_static.iterdir() if p.is_dir() and p.name != active)
    except OSError:
        others = []
    roots.extend(theme_static / name / "_next" / "static" for name in others if _is_nextjs_export(name))
    return roots


def nextjs25_static(request, path):
    response = None
    for document_root in _next_static_roots():
        try:
            response = serve(request, path, document_root=document_root)
        except Http404:
            continue
        break
    if response is None:
        raise Http404("Asset not found")
    # Without this every page load re-requested ~30 chunks; on Vercel each one ran the Django function
    # because the CDN only caches responses that say it may (s-maxage).
    hashed = path.startswith(NEXT_HASHED_STATIC_DIRS) and ".." not in path.replace("\\", "/").split("/")
    if response.status_code in (200, 304) and hashed:
        response["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
    return response


def nextjs25_public_asset(request, path):
    allowed_assets = {
        "icon-192.png",
        "icon-512.png",
        "img/logo.png",
        "img/shop-logo.png",
        "manifest.json",
        "manifest.webmanifest",
        "og-default.png",
        "robots.txt",
        "sitemap-posts.xml",
        "sitemap.xml",
        "sw.js",
        # Images that admin-created sample posts, products and banners link to.
        *(f"sample-data/{name}" for name in SAMPLE_ASSET_SIZES),
    }
    if path not in allowed_assets:
        raise Http404("Asset not found")
    if path in {"manifest.json", "manifest.webmanifest"}:
        return _nextjs25_manifest_response(request, path)
    if path == "robots.txt":
        return _nextjs25_robots_response(request)
    if path == "sitemap.xml":
        return _nextjs25_sitemap_response(request)
    if path == "sitemap-posts.xml":
        return _nextjs25_posts_sitemap_response(request)
    document_root = settings.TEMPLATES_DIR / "theme" / _nextjs_theme_name()
    response = serve(request, path, document_root=document_root)
    if path == "sw.js":
        response["Service-Worker-Allowed"] = _nextjs25_public_scope(request)
    elif path.startswith("sample-data/") or path in {"img/logo.png", "img/shop-logo.png", "og-default.png"}:
        # These are allowlisted public files. They can be served by the CDN without
        # invoking Django again; stable filenames are revalidated rather than immutable.
        response["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return response


def legacy_data_asset(request, area, path):
    if area not in LEGACY_DATA_ALLOWED_AREAS:
        raise Http404("Asset not found")
    # Drive letters, absolute and ".." paths are refused before any file is looked at, so an
    # outside file that exists answers exactly like a missing one.
    clean_path = _safe_relative_path(path)
    if LEGACY_DATA_DENIED_NAME_RE.search(path or ""):
        raise Http404("Asset not found")

    for root in legacy_area_roots(area) if clean_path else ():
        try:
            resolved_root = root.resolve()
            candidate = (resolved_root / clean_path).resolve()
            if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
                continue
            response = serve(request, clean_path, document_root=resolved_root)
        except (OSError, ValueError):
            continue
        return _legacy_data_download_headers(response, clean_path)

    # A missing (or unsafe) image name gets the default image; it never reveals a real file.
    if PurePosixPath(str(path or "").replace("\\", "/")).suffix.lower() in NEXTJS25_FALLBACK_IMAGE_EXTENSIONS:
        fallback_root = settings.TEMPLATES_DIR / "theme" / _nextjs_theme_name()
        return serve(request, "og-default.png", document_root=fallback_root)

    raise Http404("Asset not found")


def _legacy_data_download_headers(response, clean_path):
    # Only images open inline; any other upload is a download, never a page on this origin.
    response["X-Content-Type-Options"] = "nosniff"
    content_type, _encoding = mimetypes.guess_type(clean_path)
    if not (content_type or "").startswith("image/"):
        # FileResponse already wrote 'inline; filename="..."'; keep the file name.
        disposition = response.get("Content-Disposition", "")
        response["Content-Disposition"] = re.sub(r"^inline\b", "attachment", disposition) or "attachment"
    return response


class Common_Gnu_View(View):

    # def dispatch(self, request, *args, **kwargs):

    def setup(self, request, *args, **kwargs):

        # is_member   = True if request.user.is_authenticated else False
        # is_guest    = False if is_member else True
        # is_admin    = True if request.user.is_superuser else False
        # is_auth     = is_admin
        # is_mobile   = lib.is_mobile(request)
        # member      = []

        # self.is_member   = True if request.user.is_authenticated else False
        # self.is_guest    = False if self.is_member else True
        # self.is_admin    = True if request.user.is_superuser else False
        # self.is_auth     = self.is_admin
        # self.is_mobile   = lib.is_mobile(request)
        # self.member      = []

        request.user.is_user = True if request.user.is_authenticated else False
        request.user.is_guest = False if request.user.is_user else True
        request.user.is_admin = True if request.user.is_superuser else False
        request.user.is_auth = request.user.is_admin
        request.user.is_mobile = lib.is_mobile(request)
        request.user.member = {}

        return super().setup(request, *args, **kwargs)


class Common_Gnu_TemplateView(TemplateResponseMixin, ContextMixin, Common_Gnu_View):
    """
    Render a "detail" view of an object.

    By default this is a model instance looked up from `self.queryset`, but the
    view will support display of *any* object by overriding `self.get_object()`.
    """
