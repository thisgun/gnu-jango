"""Redirects from old Gnuboard5 URLs (bbs/*.php, shop/*.php, /mobile/...) to the Next.js site."""


import re
from urllib.parse import quote, urlsplit, urlunsplit

from django.http import HttpResponseRedirect
from django.conf import settings





LEGACY_DATA_ALLOWED_AREAS = {"coupon", "event", "file", "item"}


LEGACY_GNUBOARD5_BASE_URL = "http://127.0.0.9"


LEGACY_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# The board pages of the Next.js site live under /bbs/<bo_table>[/<wr_id>|/write] (Gnuboard5's bbs/
# directory); the short /<bo_table> addresses and /boards/... redirect there. Board names are unicode
# slugs (Board.bo_table), so a board segment may hold any word character, Korean included.
BOARD_URL_PREFIX = "/bbs"
BOARD_SAFE_SEGMENT_RE = re.compile(r"^[\w.-]+$")


# Browsers drop tab/newline characters inside a URL ("/\t/evil" becomes "//evil"), so no
# control character may appear in a redirect target.
LEGACY_CONTROL_CHARACTERS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


LEGACY_SHOP_ORIGINAL_PHP_ROOTS = {
    "inicis",
    "kakaopay",
    "kcp",
    "lg",
    "mail",
    "naverpay",
    "nicepay",
    "price",
    "samsungpay",
    "toss",
}


LEGACY_SHOP_PASS_THROUGH_ROOT_FILES = {
    "ajax.action.php",
    "ajax.coupondownload.php",
    "ajax.list.php",
    "ajax.orderdatasave.php",
    "ajax.orderstock.php",
    "bannerhit.php",
    "cartoption.php",
    "cartupdate.php",
    "itemoption.php",
    "itemqalist.php",
    "itemqaformupdate.php",
    "itemuselist.php",
    "itemuseformupdate.php",
    "itemrecommendmail.php",
    "itemstocksmsupdate.php",
    "orderaddressupdate.php",
    "ordercoupon.php",
    "orderformupdate.php",
    "orderitemcoupon.php",
    "ordersendcost.php",
    "ordersendcostcoupon.php",
    "personalpayformupdate.php",
    "taxsave.php",
    "wishupdate.php",
}


def _legacy_first_param(request, keys):
    for key in keys:
        value = request.GET.get(key)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _legacy_has_flag(request, keys):
    for key in keys:
        value = request.GET.get(key)
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized and normalized not in {"0", "false", "no"}:
            return True
    return False


def _legacy_safe_relative_redirect(value):
    if not value or LEGACY_CONTROL_CHARACTERS_RE.search(value):
        return ""
    value = value.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return ""
    return value


def _legacy_clean_segments(path, pattern=LEGACY_SAFE_SEGMENT_RE):
    segments = []
    for segment in (path or "").split("/"):
        value = segment.strip()
        if not value or value in {".", ".."} or not pattern.match(value):
            return []
        segments.append(value)
    return segments


def board_clean_segments(path):
    return _legacy_clean_segments(path, BOARD_SAFE_SEGMENT_RE)


def board_url(bo_table, *rest):
    """Public address of a board page: /bbs/<bo_table>[/<segment>...], every segment %-escaped."""
    segments = [bo_table, *rest]
    return BOARD_URL_PREFIX + "".join(f"/{quote(str(segment), safe='')}" for segment in segments)


def _legacy_encoded_path(prefix, segments):
    encoded = "/".join(quote(segment, safe="") for segment in segments)
    return f"{prefix.rstrip('/')}/{encoded}" if encoded else prefix.rstrip("/") or "/"


def _legacy_query(request, drop=None, set_params=None):
    params = request.GET.copy()
    for key in drop or []:
        params.pop(key, None)
    for key, value in (set_params or {}).items():
        if value is None or value is False or value == "":
            params.pop(key, None)
        else:
            params[key] = "1" if value is True else str(value)
    return params.urlencode()


def _legacy_redirect_response(target, status_code=307):
    response = HttpResponseRedirect(target)
    response.status_code = status_code
    return response


def _legacy_script_prefix(request):
    # The mount point of the app (SCRIPT_NAME), as the manifest and service worker use it.
    return (request.META.get("SCRIPT_NAME") or "").rstrip("/")


def _legacy_local_redirect(request, pathname, drop=None, set_params=None, status_code=307):
    split = urlsplit(pathname)
    base_path = urlunsplit(("", "", split.path or "/", "", ""))
    target = request.build_absolute_uri(_legacy_script_prefix(request) + base_path)
    query = _legacy_query(request, drop=drop, set_params=set_params)
    if split.query:
        query = f"{split.query}&{query}" if query else split.query
    if query:
        target = f"{target}?{query}"
    return _legacy_redirect_response(target, status_code=status_code)


def _legacy_php_redirect(request, pathname, drop=None, set_params=None, fallback="/", status_code=307):
    base_url = getattr(settings, "LEGACY_GNUBOARD5_BASE_URL", LEGACY_GNUBOARD5_BASE_URL).rstrip("/")
    if not base_url:
        return _legacy_local_redirect(request, fallback, status_code=status_code)
    if not pathname.startswith("/"):
        pathname = f"/{pathname}"
    target = f"{base_url}{pathname}"
    query = _legacy_query(request, drop=drop, set_params=set_params)
    if query:
        target = f"{target}?{query}"
    return _legacy_redirect_response(target, status_code=status_code)


def _legacy_product_path(request):
    item_id = _legacy_first_param(request, ["it_id"])
    if item_id:
        return f"/shop/{quote(item_id, safe='')}"
    seo_title = _legacy_first_param(request, ["it_seo_title"])
    if seo_title:
        return f"/shop/{quote(seo_title, safe='')}/"
    return "/shop/products"


def _legacy_board_path(request):
    bo_table = _legacy_first_param(request, ["bo_table"])
    if not bo_table:
        return BOARD_URL_PREFIX
    board_path = board_url(bo_table)
    seo_title = _legacy_first_param(request, ["wr_seo_title"])
    if seo_title:
        return f"{board_path}/{quote(seo_title, safe='')}/"
    wr_id = _legacy_first_param(request, ["wr_id"])
    if wr_id.isdigit():
        return f"{board_path}/{wr_id}"
    return board_path


def _legacy_memo_type(request):
    kind = _legacy_first_param(request, ["kind", "type"]).lower()
    return "send" if kind == "send" else "recv"


def legacy_bbs_php_route(request, legacy_path):
    segments = _legacy_clean_segments(legacy_path)
    if len(segments) != 1:
        if not segments or len(segments) > 3:
            return _legacy_local_redirect(request, "/")
        return _legacy_php_redirect(request, _legacy_encoded_path("/bbs", segments), fallback="/")

    file_name = segments[0].lower()
    if file_name == "login.php":
        redirect = _legacy_safe_relative_redirect(_legacy_first_param(request, ["redirect", "url"]))
        return _legacy_local_redirect(
            request,
            "/login",
            drop=["redirect", "url", "rewrite"],
            set_params={"redirect": redirect or None},
        )
    if file_name in {"register.php", "register_form.php"}:
        return _legacy_local_redirect(request, "/register", drop=["rewrite"])
    if file_name == "register_result.php":
        return _legacy_local_redirect(request, "/register/result", drop=["rewrite"])
    if file_name == "email_certify.php":
        # The mailed certify link of the PHP site (mb_md5) opens the certify page (token).
        return _legacy_local_redirect(
            request, "/email-certify", drop=["mb_md5", "rewrite"], set_params={"token": request.GET.get("mb_md5")}
        )
    if file_name == "password_lost.php":
        return _legacy_local_redirect(request, "/forgot-password", drop=["rewrite"])
    if file_name == "poll_result.php":
        return _legacy_local_redirect(request, "/polls", drop=["rewrite"])
    if file_name == "qalist.php":
        return _legacy_local_redirect(request, "/mypage/qas", drop=["rewrite"])
    if file_name == "qaview.php":
        qa_id = _legacy_first_param(request, ["qa_id"])
        return _legacy_local_redirect(
            request,
            f"/mypage/qas/{qa_id}" if qa_id.isdigit() else "/mypage/qas",
            drop=["qa_id", "rewrite"],
        )
    if file_name == "qawrite.php":
        qa_id = _legacy_first_param(request, ["qa_id"])
        mode = _legacy_first_param(request, ["w"]).lower()
        if mode == "r" and qa_id.isdigit():
            return _legacy_local_redirect(
                request,
                "/mypage/qas/new",
                drop=["qa_id", "w", "rewrite"],
                set_params={"reply_to": qa_id},
            )
        return _legacy_local_redirect(
            request,
            f"/mypage/qas/{qa_id}" if mode == "u" and qa_id.isdigit() else "/mypage/qas/new",
            drop=["qa_id", "w", "rewrite"],
        )
    if file_name == "memo.php":
        memo_type = _legacy_memo_type(request)
        return _legacy_local_redirect(
            request,
            "/mypage/memos",
            drop=["kind", "type", "rewrite"],
            set_params={"type": memo_type if memo_type == "send" else None},
        )
    if file_name == "memo_form.php":
        recv = _legacy_first_param(request, ["recv", "me_recv_mb_id", "mb_id"])
        return _legacy_local_redirect(
            request,
            "/mypage/memos/new",
            drop=["recv", "me_recv_mb_id", "mb_id", "rewrite"],
            set_params={"recv": recv or None},
        )
    if file_name == "memo_view.php":
        memo_id = _legacy_first_param(request, ["me_id"])
        memo_type = _legacy_memo_type(request)
        return _legacy_local_redirect(
            request,
            f"/mypage/memos/{memo_id}" if memo_id.isdigit() else "/mypage/memos",
            drop=["me_id", "kind", "type", "rewrite"],
            set_params={"type": memo_type if memo_type == "send" else None},
        )
    if file_name == "profile.php":
        mb_id = _legacy_first_param(request, ["mb_id"])
        return _legacy_local_redirect(
            request,
            f"/members/{quote(mb_id, safe='')}" if LEGACY_SAFE_SEGMENT_RE.match(mb_id) else "/",
            drop=["mb_id", "rewrite"],
        )
    if file_name == "point.php":
        return _legacy_local_redirect(request, "/mypage/points", drop=["rewrite"])
    if file_name == "scrap.php":
        return _legacy_local_redirect(request, "/mypage/scraps", drop=["rewrite"])
    if file_name == "board.php":
        return _legacy_local_redirect(
            request,
            _legacy_board_path(request),
            drop=["bo_table", "wr_id", "wr_seo_title", "rewrite"],
        )
    if file_name == "write.php":
        bo_table = _legacy_first_param(request, ["bo_table"])
        return _legacy_local_redirect(
            request,
            board_url(bo_table, "write") if bo_table else BOARD_URL_PREFIX,
            drop=["bo_table", "rewrite"],
        )
    if file_name == "content.php":
        content_id = _legacy_first_param(request, ["co_id"])
        if content_id:
            return _legacy_local_redirect(
                request,
                f"/content/{quote(content_id, safe='')}",
                drop=["co_id", "co_seo_title", "rewrite"],
            )
        seo_title = _legacy_first_param(request, ["co_seo_title"])
        return _legacy_local_redirect(
            request,
            f"/content/{quote(seo_title, safe='')}/" if seo_title else "/content",
            drop=["co_id", "co_seo_title", "rewrite"],
        )
    if file_name == "group.php":
        group_id = _legacy_first_param(request, ["gr_id"])
        return _legacy_local_redirect(
            request,
            BOARD_URL_PREFIX,
            drop=["gr_id", "rewrite"],
            set_params={"group": group_id or None},
        )
    if file_name == "faq.php":
        return _legacy_local_redirect(request, "/faq", drop=["rewrite"])
    if file_name == "new.php":
        return _legacy_local_redirect(request, "/recent", drop=["rewrite"])
    if file_name == "search.php":
        keyword = _legacy_first_param(request, ["q", "stx"])
        return _legacy_local_redirect(
            request,
            "/search",
            drop=["stx", "rewrite"],
            set_params={"q": keyword or None},
        )

    return _legacy_php_redirect(request, _legacy_encoded_path("/bbs", segments), fallback="/")


def legacy_shop_php_route(request, legacy_path):
    segments = _legacy_clean_segments(legacy_path)
    if not segments:
        return _legacy_local_redirect(request, "/shop")

    first = segments[0].lower()
    file_name = segments[-1].lower()
    if first in LEGACY_SHOP_ORIGINAL_PHP_ROOTS or len(segments) > 1:
        return _legacy_php_redirect(request, _legacy_encoded_path("/shop", segments), fallback="/shop")
    if file_name in LEGACY_SHOP_PASS_THROUGH_ROOT_FILES:
        return _legacy_php_redirect(request, _legacy_encoded_path("/shop", segments), fallback="/shop")

    return _legacy_shop_file_redirect(request, file_name)


def _legacy_shop_file_redirect(request, file_name):
    if file_name == "index.php":
        return _legacy_local_redirect(request, "/shop")
    if file_name == "cart.php":
        return _legacy_local_redirect(request, "/shop/cart")
    if file_name in {"category.php", "list.php"}:
        ca_id = _legacy_first_param(request, ["ca_id"])
        return _legacy_local_redirect(
            request,
            f"/shop/list-{quote(ca_id, safe='')}" if ca_id else "/shop/products",
            drop=["ca_id"],
        )
    if file_name == "coupon.php":
        return _legacy_local_redirect(request, "/mypage/coupons")
    if file_name == "couponzone.php":
        return _legacy_local_redirect(request, "/shop/couponzone")
    if file_name == "event.php":
        ev_id = _legacy_first_param(request, ["ev_id"])
        return _legacy_local_redirect(
            request,
            f"/shop/events/{quote(ev_id, safe='')}" if ev_id else "/shop/events",
            drop=["ev_id"],
        )
    if file_name == "item.php":
        return _legacy_local_redirect(request, _legacy_product_path(request), drop=["it_id", "it_seo_title"])
    if file_name == "iteminfo.php":
        item_id = _legacy_first_param(request, ["it_id"])
        info = _legacy_first_param(request, ["info"]).lower()
        tab = "reviews" if info in {"use", "review", "reviews"} else "qa" if info in {"qa", "qna"} else None
        return _legacy_local_redirect(
            request,
            f"/shop/{quote(item_id, safe='')}" if item_id else "/shop/products",
            drop=["it_id", "info"],
            set_params={"tab": tab},
        )
    if file_name == "itemqa.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"tab": "qa"},
        )
    if file_name == "itemqaform.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"tab": "qa", "form": "qa"},
        )
    if file_name == "itemrecommend.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"modal": "recommend"},
        )
    if file_name == "itemstocksms.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"modal": "restock"},
        )
    if file_name == "itemuse.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"tab": "reviews"},
        )
    if file_name == "itemuseform.php":
        return _legacy_local_redirect(
            request,
            _legacy_product_path(request),
            drop=["it_id", "it_seo_title"],
            set_params={"tab": "reviews", "form": "review"},
        )
    if file_name == "largeimage.php":
        return _legacy_local_redirect(request, "/shop/largeimage")
    if file_name == "listtype.php":
        item_type = _legacy_first_param(request, ["type"])
        return _legacy_local_redirect(
            request,
            f"/shop/type-{item_type}" if item_type in {"1", "2", "3", "4", "5"} else "/shop/products",
            drop=["type"],
        )
    if file_name == "mypage.php":
        return _legacy_local_redirect(request, "/mypage")
    if file_name == "orderaddress.php":
        return _legacy_local_redirect(request, "/mypage/addresses")
    if file_name == "orderform.php":
        return _legacy_local_redirect(
            request,
            "/shop/order",
            drop=["sw_direct"],
            set_params={"direct": 1 if _legacy_has_flag(request, ["sw_direct", "direct"]) else None},
        )
    if file_name == "orderinquiry.php":
        return _legacy_local_redirect(request, "/shop/orders")
    if file_name in {"orderinquiryview.php", "orderinquirycancel.php"}:
        order_id = _legacy_first_param(request, ["od_id"])
        return _legacy_local_redirect(
            request,
            f"/shop/orders/{quote(order_id, safe='')}" if order_id else "/shop/orders",
            drop=["od_id"],
        )
    if file_name == "personalpay.php":
        return _legacy_local_redirect(request, "/shop/personalpay")
    if file_name == "personalpayform.php":
        # the checkout lives on the Next.js pay page (the old nextjs_handoff=1 stub ended there too)
        pp_id = _legacy_first_param(request, ["pp_id"])
        return _legacy_local_redirect(
            request,
            f"/shop/personalpay/{quote(pp_id, safe='')}/pay" if pp_id else "/shop/personalpay",
            drop=["pp_id", "nextjs_handoff"],
        )
    if file_name == "personalpayresult.php":
        pp_id = _legacy_first_param(request, ["pp_id"])
        return _legacy_local_redirect(
            request,
            f"/shop/personalpay/{quote(pp_id, safe='')}" if pp_id else "/shop/personalpay",
            drop=["pp_id"],
        )
    if file_name == "search.php":
        return _legacy_local_redirect(request, "/shop/search")
    if file_name == "wishlist.php":
        return _legacy_local_redirect(request, "/shop/wishlist")

    return _legacy_php_redirect(request, f"/shop/{quote(file_name, safe='')}", fallback="/shop")


def legacy_mobile_route(request, legacy_path=""):
    segments = _legacy_clean_segments(legacy_path)
    if not segments:
        return _legacy_local_redirect(request, "/")

    first = segments[0].lower()
    file_name = segments[-1].lower()
    if first == "shop":
        return _legacy_mobile_shop_route(request, segments[1:])
    if file_name == "index.php":
        return _legacy_local_redirect(request, "/")
    if file_name == "group.php":
        group_id = _legacy_first_param(request, ["gr_id"])
        return _legacy_local_redirect(request, BOARD_URL_PREFIX, drop=["gr_id"], set_params={"group": group_id or None})
    if file_name == "content.php":
        content_id = _legacy_first_param(request, ["co_id"])
        if content_id:
            return _legacy_local_redirect(
                request,
                f"/content/{quote(content_id, safe='')}",
                drop=["co_id", "co_seo_title"],
            )
        seo_title = _legacy_first_param(request, ["co_seo_title"])
        return _legacy_local_redirect(
            request,
            f"/content/{quote(seo_title, safe='')}/" if seo_title else "/content",
            drop=["co_id", "co_seo_title"],
        )

    return _legacy_php_redirect(request, _legacy_encoded_path("/mobile", segments), fallback="/")


def _legacy_mobile_shop_route(request, segments):
    if not segments:
        return _legacy_local_redirect(request, "/shop")

    first = segments[0].lower()
    file_name = segments[-1].lower()
    if first in LEGACY_SHOP_ORIGINAL_PHP_ROOTS or len(segments) > 1:
        return _legacy_php_redirect(request, _legacy_encoded_path("/mobile/shop", segments), fallback="/shop")
    if file_name in LEGACY_SHOP_PASS_THROUGH_ROOT_FILES:
        return _legacy_local_redirect(request, f"/shop/{quote(file_name, safe='')}")
    if file_name == "coupon.php":
        return _legacy_local_redirect(request, "/mypage/coupons")

    return _legacy_shop_file_redirect(request, file_name)
