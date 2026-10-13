import { appUrl, g5PathForRuntime, stripG5BasePath } from "@/lib/config";

const CANONICAL_SHOP_ROOTS = new Set([
  "cart",
  "categories",
  "compare",
  "couponzone",
  "events",
  "largeimage",
  "order",
  "orders",
  "payment",
  "personalpay",
  "products",
  "qas",
  "reviews",
  "search",
  "wishlist",
]);

const LEGACY_SHOP_ROOTS = new Set([
  "_common",
  "_head",
  "_tail",
  "ajax.action",
  "ajax.coupondownload",
  "ajax.list",
  "ajax.orderdatasave",
  "ajax.orderstock",
  "bannerhit",
  "cancel_pg.inc",
  "cartoption",
  "cartupdate",
  "category",
  "coupon",
  "event",
  "img",
  "index",
  "inicis",
  "item",
  "iteminfo",
  "itemoption",
  "itemqa",
  "itemqaform",
  "itemqaformupdate",
  "itemqalist",
  "itemrecommend",
  "itemrecommendmail",
  "itemstocksms",
  "itemstocksmsupdate",
  "itemuse",
  "itemuseform",
  "itemuseformupdate",
  "itemuselist",
  "kakaopay",
  "kcp",
  "lg",
  "list",
  "listtype",
  "mail",
  "mypage",
  "naverpay",
  "nicepay",
  "orderaddress",
  "orderaddressupdate",
  "ordercoupon",
  "ordererrormail",
  "orderform",
  "orderform.sub",
  "orderformupdate",
  "orderinquiry",
  "orderinquiry.sub",
  "orderinquirycancel",
  "orderinquiryview",
  "orderitemcoupon",
  "ordermail1.inc",
  "ordermail2.inc",
  "ordersendcost",
  "ordersendcostcoupon",
  "personalpayform",
  "personalpayform.sub",
  "personalpayformupdate",
  "personalpayresult",
  "price",
  "settle_inicis.inc",
  "settle_inicis_common",
  "settle_kakaopay.inc",
  "settle_kcp.inc",
  "settle_kcp_common",
  "settle_lg.inc",
  "settle_lg_common",
  "settle_naverpay.inc",
  "settle_nicepay.inc",
  "settle_nicepay_common",
  "settle_toss.inc",
  "settle_toss_common",
  "shop.head",
  "shop.tail",
  "taxsave",
  "toss",
  "wishupdate",
]);

const SAFE_MEMBER_ID_RE = /^[a-zA-Z0-9_]+$/;

function normalizeShopSegment(value: string): string {
  try {
    value = decodeURIComponent(value);
  } catch {
    // Keep the original value when it is not a valid encoded segment.
  }

  return value.replace(/\.php$/i, "").toLowerCase();
}

function isReservedShopSegment(value: string): boolean {
  const segment = normalizeShopSegment(value);
  return CANONICAL_SHOP_ROOTS.has(segment) || LEGACY_SHOP_ROOTS.has(segment);
}

function splitPath(value: string): { pathname: string; search: string; hash: string } | null {
  if (!value.startsWith("/")) return null;

  const hashIndex = value.indexOf("#");
  const beforeHash = hashIndex >= 0 ? value.slice(0, hashIndex) : value;
  const hash = hashIndex >= 0 ? value.slice(hashIndex) : "";
  const queryIndex = beforeHash.indexOf("?");
  const pathname = queryIndex >= 0 ? beforeHash.slice(0, queryIndex) : beforeHash;
  const search = queryIndex >= 0 ? beforeHash.slice(queryIndex) : "";

  return { pathname: pathname || "/", search, hash };
}

function withSuffix(pathname: string, search: string, hash: string): string {
  return `${pathname}${search}${hash}`;
}

function firstYoungCartType(search: string): { type: string; search: string } | null {
  if (!search) return null;

  const params = new URLSearchParams(search.slice(1));
  for (let index = 1; index <= 5; index += 1) {
    const key = `it_type${index}`;
    if (params.get(key) === "1") {
      params.delete(key);
      const nextSearch = params.toString();
      return { type: String(index), search: nextSearch ? `?${nextSearch}` : "" };
    }
  }

  return null;
}

function searchParams(search: string): URLSearchParams {
  return new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
}

function firstSearchParam(search: string, keys: string[]): string {
  const params = searchParams(search);

  for (const key of keys) {
    const value = params.get(key);
    if (value !== null && value.trim() !== "") {
      return value.trim();
    }
  }

  return "";
}

function safeShopProductSegment(value: string): string {
  const trimmed = value.trim();
  if (trimmed === ".") return "%2E";
  if (trimmed === "..") return "%2E%2E";
  return encodeURIComponent(trimmed);
}

function unsafeShortProductSegment(value: string): boolean {
  const trimmed = value.trim();
  return (
    trimmed === "." ||
    trimmed === ".." ||
    trimmed.includes("/") ||
    trimmed.includes("\\") ||
    isReservedShopSegment(trimmed)
  );
}

function safeRelativeRedirect(value: string): string {
  if (!value) return "";

  let decoded = value;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    // URLSearchParams already decodes valid values; keep the original on malformed input.
  }

  if (
    !decoded.startsWith("/") ||
    decoded.startsWith("//") ||
    decoded.includes("\\") ||
    /[\r\n]/.test(decoded)
  ) {
    return "";
  }

  return decoded;
}

function hasSearchFlag(search: string, keys: string[]): boolean {
  const params = searchParams(search);

  return keys.some((key) => {
    const value = params.get(key);
    if (value === null) return false;

    const normalized = value.trim().toLowerCase();
    return normalized !== "" && normalized !== "0" && normalized !== "false" && normalized !== "no";
  });
}

function isPassthroughLegacyRequest(pathname: string, search: string): boolean {
  return (
    pathname === "/shop/personalpayform.php" &&
    searchParams(search).get("g5_nextjs25_passthrough") === "1"
  );
}

function searchWithChanges(
  search: string,
  drop: string[] = [],
  set: Record<string, string | number | boolean | null | undefined> = {}
): string {
  const params = searchParams(search);

  drop.forEach((key) => params.delete(key));
  Object.entries(set).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false || value === "") {
      params.delete(key);
      return;
    }

    params.set(key, value === true ? "1" : String(value));
  });

  const nextSearch = params.toString();
  return nextSearch ? `?${nextSearch}` : "";
}

function legacyProductShortPath(search: string): string {
  const itemId = firstSearchParam(search, ["it_id"]);
  if (itemId) {
    const encoded = safeShopProductSegment(itemId);
    return unsafeShortProductSegment(itemId)
      ? `/shop/products/${encoded}`
      : `/shop/${encoded}`;
  }

  const seoTitle = firstSearchParam(search, ["it_seo_title"]);
  if (seoTitle && !unsafeShortProductSegment(seoTitle)) {
    return `/shop/${safeShopProductSegment(seoTitle)}/`;
  }

  return "/shop/products";
}

// Board pages are published under /bbs/ (Django serves them; the Next.js route stays /boards).
const BOARD_URL_PREFIX = "/bbs";

function legacyBoardShortPath(search: string): string {
  const boTable = firstSearchParam(search, ["bo_table"]);
  if (!boTable) return BOARD_URL_PREFIX;

  const boardPath = `${BOARD_URL_PREFIX}/${encodeURIComponent(boTable)}`;
  const seoTitle = firstSearchParam(search, ["wr_seo_title"]);
  if (seoTitle) return `${boardPath}/${encodeURIComponent(seoTitle)}/`;

  const wrId = firstSearchParam(search, ["wr_id"]);
  if (/^[0-9]+$/.test(wrId)) return `${boardPath}/${wrId}`;

  return boardPath;
}

function legacyLoginSearch(search: string): string {
  const redirect = safeRelativeRedirect(firstSearchParam(search, ["redirect", "url"]));

  return searchWithChanges(
    search,
    ["redirect", "url", "rewrite"],
    redirect ? { redirect } : {}
  );
}

function legacyMemoType(search: string): "recv" | "send" {
  const kind = firstSearchParam(search, ["kind", "type"]).toLowerCase();
  return kind === "send" ? "send" : "recv";
}

function legacyMemberProfilePath(search: string): string {
  const mbId = firstSearchParam(search, ["mb_id"]);
  return SAFE_MEMBER_ID_RE.test(mbId) ? `/members/${encodeURIComponent(mbId)}` : "/";
}

function legacyGnuboardPhpShortPath(pathname: string, search: string, hash: string): string | null {
  if (pathname === "/bbs/login.php") {
    return withSuffix("/login", legacyLoginSearch(search), hash);
  }

  const staticRoutes: Record<string, string> = {
    "/bbs/register.php": "/register",
    "/bbs/register_form.php": "/register",
    "/bbs/register_result.php": "/register/result",
    "/bbs/password_lost.php": "/forgot-password",
    "/bbs/poll_result.php": "/polls",
    "/bbs/qalist.php": "/mypage/qas",
    "/bbs/point.php": "/mypage/points",
    "/bbs/scrap.php": "/mypage/scraps",
  };

  if (staticRoutes[pathname]) {
    return withSuffix(staticRoutes[pathname], searchWithChanges(search, ["rewrite"]), hash);
  }

  if (pathname === "/bbs/qaview.php") {
    const qaId = firstSearchParam(search, ["qa_id"]);
    return withSuffix(
      /^[0-9]+$/.test(qaId) ? `/mypage/qas/${qaId}` : "/mypage/qas",
      searchWithChanges(search, ["qa_id", "rewrite"]),
      hash
    );
  }

  if (pathname === "/bbs/qawrite.php") {
    const qaId = firstSearchParam(search, ["qa_id"]);
    const mode = firstSearchParam(search, ["w"]).toLowerCase();

    if (mode === "r" && /^[0-9]+$/.test(qaId)) {
      return withSuffix(
        "/mypage/qas/new",
        searchWithChanges(search, ["qa_id", "w", "rewrite"], { reply_to: qaId }),
        hash
      );
    }

    return withSuffix(
      mode === "u" && /^[0-9]+$/.test(qaId) ? `/mypage/qas/${qaId}` : "/mypage/qas/new",
      searchWithChanges(search, ["qa_id", "w", "rewrite"]),
      hash
    );
  }

  if (pathname === "/bbs/memo.php") {
    const type = legacyMemoType(search);
    return withSuffix(
      "/mypage/memos",
      searchWithChanges(search, ["kind", "type", "rewrite"], type === "send" ? { type } : {}),
      hash
    );
  }

  if (pathname === "/bbs/memo_form.php") {
    const recv = firstSearchParam(search, ["recv", "me_recv_mb_id", "mb_id"]);
    return withSuffix(
      "/mypage/memos/new",
      searchWithChanges(search, ["recv", "me_recv_mb_id", "mb_id", "rewrite"], recv ? { recv } : {}),
      hash
    );
  }

  if (pathname === "/bbs/memo_view.php") {
    const memoId = firstSearchParam(search, ["me_id"]);
    const type = legacyMemoType(search);
    return withSuffix(
      /^[0-9]+$/.test(memoId) ? `/mypage/memos/${memoId}` : "/mypage/memos",
      searchWithChanges(search, ["me_id", "kind", "type", "rewrite"], type === "send" ? { type } : {}),
      hash
    );
  }

  if (pathname === "/bbs/profile.php") {
    return withSuffix(
      legacyMemberProfilePath(search),
      searchWithChanges(search, ["mb_id", "rewrite"]),
      hash
    );
  }

  if (pathname === "/bbs/board.php") {
    return withSuffix(
      legacyBoardShortPath(search),
      searchWithChanges(search, ["bo_table", "wr_id", "wr_seo_title", "rewrite"]),
      hash
    );
  }

  if (pathname === "/bbs/write.php") {
    const boTable = firstSearchParam(search, ["bo_table"]);
    return withSuffix(
      boTable ? `${BOARD_URL_PREFIX}/${encodeURIComponent(boTable)}/write` : BOARD_URL_PREFIX,
      searchWithChanges(search, ["bo_table", "rewrite"]),
      hash
    );
  }

  if (pathname === "/bbs/content.php") {
    const contentId = firstSearchParam(search, ["co_id"]);
    if (contentId) {
      return withSuffix(
        `/content/${encodeURIComponent(contentId)}`,
        searchWithChanges(search, ["co_id", "co_seo_title", "rewrite"]),
        hash
      );
    }

    const seoTitle = firstSearchParam(search, ["co_seo_title"]);
    if (seoTitle) {
      return withSuffix(
        `/content/${encodeURIComponent(seoTitle)}/`,
        searchWithChanges(search, ["co_id", "co_seo_title", "rewrite"]),
        hash
      );
    }

    return withSuffix("/content", searchWithChanges(search, ["co_id", "co_seo_title", "rewrite"]), hash);
  }

  if (pathname === "/bbs/group.php") {
    const groupId = firstSearchParam(search, ["gr_id"]);
    return withSuffix(
      BOARD_URL_PREFIX,
      searchWithChanges(search, ["gr_id", "rewrite"], groupId ? { group: groupId } : {}),
      hash
    );
  }

  if (pathname === "/bbs/faq.php") {
    return withSuffix("/faq", searchWithChanges(search, ["rewrite"]), hash);
  }

  if (pathname === "/bbs/new.php") {
    return withSuffix("/recent", searchWithChanges(search, ["rewrite"]), hash);
  }

  if (pathname === "/bbs/search.php") {
    const keyword = firstSearchParam(search, ["q", "stx"]);
    return withSuffix(
      "/search",
      searchWithChanges(search, ["stx", "rewrite"], keyword ? { q: keyword } : {}),
      hash
    );
  }

  return null;
}

export function toG5ShortPath(value: string): string {
  const parts = splitPath(value);
  if (!parts) return value;

  const pathname = stripG5BasePath(parts.pathname);
  const { search, hash } = parts;

  if (isPassthroughLegacyRequest(pathname, search)) {
    return withSuffix(pathname, search, hash);
  }

  if (pathname === "/mobile" || pathname === "/mobile/" || pathname === "/mobile/index.php") {
    return withSuffix("/", search, hash);
  }

  if (pathname === "/mobile/group.php") {
    const groupId = firstSearchParam(search, ["gr_id"]);

    return withSuffix(
      BOARD_URL_PREFIX,
      searchWithChanges(search, ["gr_id"], groupId ? { group: groupId } : {}),
      hash
    );
  }

  if (pathname === "/mobile/content.php") {
    const contentId = firstSearchParam(search, ["co_id"]);
    if (contentId) {
      return withSuffix(
        `/content/${encodeURIComponent(contentId)}`,
        searchWithChanges(search, ["co_id", "co_seo_title"]),
        hash
      );
    }

    const seoTitle = firstSearchParam(search, ["co_seo_title"]);
    if (seoTitle) {
      return withSuffix(
        `/content/${encodeURIComponent(seoTitle)}/`,
        searchWithChanges(search, ["co_id", "co_seo_title"]),
        hash
      );
    }

    return withSuffix("/", searchWithChanges(search, ["co_id", "co_seo_title"]), hash);
  }

  const legacyGnuboardPhpShortPathValue = legacyGnuboardPhpShortPath(pathname, search, hash);
  if (legacyGnuboardPhpShortPathValue !== null) {
    return legacyGnuboardPhpShortPathValue;
  }

  if (pathname === "/mobile/shop" || pathname === "/mobile/shop/" || pathname === "/mobile/shop/index.php") {
    return withSuffix("/shop", search, hash);
  }

  if (pathname === "/mobile/shop/cart.php") {
    return withSuffix("/shop/cart", search, hash);
  }

  if (pathname === "/mobile/shop/wishlist.php") {
    return withSuffix("/shop/wishlist", search, hash);
  }

  const staticMobileShopPhpRoutes: Record<string, string> = {
    "/mobile/shop/coupon.php": "/mypage/coupons",
    "/mobile/shop/largeimage.php": "/shop/largeimage",
    "/mobile/shop/mypage.php": "/mypage",
    "/mobile/shop/orderaddress.php": "/mypage/addresses",
    "/mobile/shop/orderinquiry.php": "/shop/orders",
    "/mobile/shop/personalpay.php": "/shop/personalpay",
    "/mobile/shop/search.php": "/shop/search",
  };

  if (staticMobileShopPhpRoutes[pathname]) {
    return withSuffix(staticMobileShopPhpRoutes[pathname], search, hash);
  }

  if (pathname === "/mobile/shop/category.php" || pathname === "/mobile/shop/list.php") {
    const caId = firstSearchParam(search, ["ca_id"]);
    return withSuffix(
      caId ? `/shop/list-${encodeURIComponent(caId)}` : "/shop/products",
      searchWithChanges(search, ["ca_id"]),
      hash
    );
  }

  if (pathname === "/mobile/shop/event.php") {
    const evId = firstSearchParam(search, ["ev_id"]);
    return withSuffix(
      evId ? `/shop/events/${encodeURIComponent(evId)}` : "/shop/events",
      searchWithChanges(search, ["ev_id"]),
      hash
    );
  }

  if (pathname === "/mobile/shop/item.php") {
    return withSuffix(legacyProductShortPath(search), searchWithChanges(search, ["it_id", "it_seo_title"]), hash);
  }

  if (pathname === "/mobile/shop/iteminfo.php") {
    const itemId = firstSearchParam(search, ["it_id"]);
    const info = firstSearchParam(search, ["info"]).toLowerCase();
    const tab =
      info === "use" || info === "review" || info === "reviews"
        ? "reviews"
        : info === "qa" || info === "qna"
          ? "qa"
          : "";

    return withSuffix(
      itemId ? `/shop/${encodeURIComponent(itemId)}` : "/shop/products",
      searchWithChanges(search, ["it_id", "info"], tab ? { tab } : {}),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemqa.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { tab: "qa" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemqaform.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { tab: "qa", form: "qa" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemrecommend.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { modal: "recommend" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemstocksms.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { modal: "restock" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemuse.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { tab: "reviews" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/itemuseform.php") {
    return withSuffix(
      legacyProductShortPath(search),
      searchWithChanges(search, ["it_id", "it_seo_title"], { tab: "reviews", form: "review" }),
      hash
    );
  }

  if (pathname === "/mobile/shop/listtype.php") {
    const type = firstSearchParam(search, ["type"]);
    return withSuffix(
      /^[1-5]$/.test(type) ? `/shop/type-${type}` : "/shop/products",
      searchWithChanges(search, ["type"]),
      hash
    );
  }

  if (pathname === "/mobile/shop/orderform.php") {
    const direct = hasSearchFlag(search, ["sw_direct", "direct"]);
    return withSuffix("/shop/order", searchWithChanges(search, ["sw_direct"], direct ? { direct: 1 } : {}), hash);
  }

  if (pathname === "/mobile/shop/orderinquiryview.php") {
    const orderId = firstSearchParam(search, ["od_id"]);
    return withSuffix(
      orderId ? `/shop/orders/${encodeURIComponent(orderId)}` : "/shop/orders",
      searchWithChanges(search, ["od_id"]),
      hash
    );
  }

  if (pathname === "/mobile/shop/personalpayform.php") {
    const ppId = firstSearchParam(search, ["pp_id"]);
    return withSuffix(
      ppId ? `/shop/personalpay/${encodeURIComponent(ppId)}/pay` : "/shop/personalpay",
      searchWithChanges(search, ["pp_id"]),
      hash
    );
  }

  if (pathname === "/mobile/shop/personalpayresult.php") {
    const ppId = firstSearchParam(search, ["pp_id"]);
    return withSuffix(
      ppId ? `/shop/personalpay/${encodeURIComponent(ppId)}` : "/shop/personalpay",
      searchWithChanges(search, ["pp_id"]),
      hash
    );
  }

  // The internal /boards route is published under /bbs. Board names may be Korean (any segment).
  if (pathname === "/boards" || pathname === "/boards/") {
    return withSuffix(BOARD_URL_PREFIX, search, hash);
  }

  let match = pathname.match(/^\/boards\/([^/]+)\/rss$/);
  if (match) return withSuffix(`/rss/${match[1]}`, search, hash);

  match = pathname.match(/^\/boards\/([^/]+)(\/(?:[^/]+\/?)?)?$/);
  if (match) return withSuffix(`${BOARD_URL_PREFIX}/${match[1]}${match[2] || ""}`, search, hash);

  match = pathname.match(/^\/shop\/categories\/([0-9A-Za-z]+)$/);
  if (match) return withSuffix(`/shop/list-${match[1]}`, search, hash);

  const staticShopPhpRoutes: Record<string, string> = {
    "/shop/index.php": "/shop",
    "/shop/cart.php": "/shop/cart",
    "/shop/wishlist.php": "/shop/wishlist",
    "/shop/couponzone.php": "/shop/couponzone",
    "/shop/search.php": "/shop/search",
    "/shop/largeimage.php": "/shop/largeimage",
    "/shop/mypage.php": "/mypage",
    "/shop/orderinquiry.php": "/shop/orders",
    "/shop/personalpay.php": "/shop/personalpay",
  };

  if (staticShopPhpRoutes[pathname]) {
    return withSuffix(staticShopPhpRoutes[pathname], search, hash);
  }

  if (pathname === "/shop/item.php") {
    return withSuffix(legacyProductShortPath(search), searchWithChanges(search, ["it_id", "it_seo_title"]), hash);
  }

  if (pathname === "/shop/iteminfo.php") {
    const itemId = firstSearchParam(search, ["it_id"]);
    const info = firstSearchParam(search, ["info"]).toLowerCase();
    const tab =
      info === "use" || info === "review" || info === "reviews"
        ? "reviews"
        : info === "qa" || info === "qna"
          ? "qa"
          : "";

    return withSuffix(
      itemId ? `/shop/${encodeURIComponent(itemId)}` : "/shop/products",
      searchWithChanges(search, ["it_id", "info"], tab ? { tab } : {}),
      hash
    );
  }

  if (pathname === "/shop/category.php" || pathname === "/shop/list.php") {
    const caId = firstSearchParam(search, ["ca_id"]);
    return withSuffix(
      caId ? `/shop/list-${encodeURIComponent(caId)}` : "/shop/products",
      searchWithChanges(search, ["ca_id"]),
      hash
    );
  }

  if (pathname === "/shop/listtype.php") {
    const type = firstSearchParam(search, ["type"]);
    return withSuffix(
      /^[1-5]$/.test(type) ? `/shop/type-${type}` : "/shop/products",
      searchWithChanges(search, ["type"]),
      hash
    );
  }

  if (pathname === "/shop/event.php") {
    const evId = firstSearchParam(search, ["ev_id"]);
    return withSuffix(
      evId ? `/shop/events/${encodeURIComponent(evId)}` : "/shop/events",
      searchWithChanges(search, ["ev_id"]),
      hash
    );
  }

  if (pathname === "/shop/orderform.php") {
    const direct = hasSearchFlag(search, ["sw_direct", "direct"]);
    return withSuffix("/shop/order", searchWithChanges(search, ["sw_direct"], direct ? { direct: 1 } : {}), hash);
  }

  if (pathname === "/shop/orderinquiryview.php" || pathname === "/shop/orderinquirycancel.php") {
    const orderId = firstSearchParam(search, ["od_id"]);
    return withSuffix(
      orderId ? `/shop/orders/${encodeURIComponent(orderId)}` : "/shop/orders",
      searchWithChanges(search, ["od_id", "token", "cancel_memo"]),
      hash
    );
  }

  if (pathname === "/shop/personalpayform.php") {
    const ppId = firstSearchParam(search, ["pp_id"]);
    return withSuffix(
      ppId ? `/shop/personalpay/${encodeURIComponent(ppId)}/pay` : "/shop/personalpay",
      searchWithChanges(search, ["pp_id"]),
      hash
    );
  }

  if (pathname === "/shop/personalpayresult.php") {
    const ppId = firstSearchParam(search, ["pp_id"]);
    return withSuffix(
      ppId ? `/shop/personalpay/${encodeURIComponent(ppId)}` : "/shop/personalpay",
      searchWithChanges(search, ["pp_id"]),
      hash
    );
  }

  match = pathname.match(/^\/shop\/products\/([^/]+)\/$/);
  if (match && !isReservedShopSegment(match[1])) {
    return withSuffix(`/shop/${match[1]}/`, search, hash);
  }

  match = pathname.match(/^\/shop\/products\/([^/]+)$/);
  if (match && !isReservedShopSegment(match[1])) {
    return withSuffix(`/shop/${match[1]}`, search, hash);
  }

  if (pathname === "/shop/products") {
    const type = firstYoungCartType(search);
    if (type) return withSuffix(`/shop/type-${type.type}`, type.search, hash);
  }

  return withSuffix(pathname, search, hash);
}

export function g5ShortHref(value: string): string {
  return g5PathForRuntime(toG5ShortPath(value));
}

export function appShortUrl(value: string): string {
  return appUrl(toG5ShortPath(value));
}
