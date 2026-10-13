"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  apiBaseUrlForRuntime,
  g5BasePathForRuntime,
  currentPathForRuntime,
  g5PathForRuntime,
  isG5ThemeRuntime,
} from "@/lib/config";
import { toG5ShortPath } from "@/lib/g5-short-url";

const RESERVED_ROOTS = new Set([
  "admin",
  "adm",
  "api",
  "bbs",
  "css",
  "data",
  "faq",
  "forgot-password",
  "img",
  "install",
  "js",
  "lib",
  "login",
  "members",
  "mobile",
  "offline",
  "plugin",
  "polls",
  "recent",
  "register",
  "robots.txt",
  "search",
  "shop",
  "sitemap.xml",
  "sitemap-posts.xml",
  "theme",
]);

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

interface RouteOptions {
  legacySeoPath?: boolean;
}

function encodeRouteSegment(value: string): string {
  try {
    return encodeURIComponent(decodeURIComponent(value));
  } catch {
    return encodeURIComponent(value);
  }
}

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

function _staticRouteFor(pathname: string, options: RouteOptions = {}): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (
    path === "/" ||
    path.startsWith("/admin") ||
    path.startsWith("/boards") ||
    path.startsWith("/content") ||
    path.startsWith("/members") ||
    path.startsWith("/mypage")
  ) {
    return null;
  }

  let match = path.match(/^\/shop\/list-([0-9a-z]+)$/i);
  if (match) return `/shop/categories/${encodeURIComponent(match[1])}`;

  match = path.match(/^\/shop\/type-([1-5])$/);
  if (match) return `/shop/products?it_type${match[1]}=1`;

  match = path.match(/^\/shop\/([^/]+)$/);
  if (match && !options.legacySeoPath && !isReservedShopSegment(match[1])) {
    return `/shop/products/${encodeURIComponent(match[1])}`;
  }

  if (path === "/shop" || path.startsWith("/shop/")) {
    return null;
  }

  match = path.match(/^\/([0-9A-Za-z_]+)$/);
  if (match && !RESERVED_ROOTS.has(match[1])) {
    return `/boards/${encodeURIComponent(match[1])}`;
  }

  match = path.match(/^\/([0-9A-Za-z_]+)\/write$/);
  if (match && !RESERVED_ROOTS.has(match[1])) {
    return `/boards/${encodeURIComponent(match[1])}/write`;
  }

  match = path.match(/^\/([0-9A-Za-z_]+)\/([0-9]+)$/);
  if (match && !RESERVED_ROOTS.has(match[1])) {
    return `/boards/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}`;
  }

  match = path.match(/^\/([0-9A-Za-z_]+)\/([^/]+)$/);
  if (match && !RESERVED_ROOTS.has(match[1]) && match[2] !== "rss") {
    return `/boards/${encodeURIComponent(match[1])}/${encodeRouteSegment(match[2])}`;
  }

  return null;
}

function pathOnly(target: string): string {
  return target.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
}

function requiresDocumentNavigation(target: string): boolean {
  const path = pathOnly(target);
  return [
    /^\/boards\/[^/]+$/,
    /^\/boards\/[^/]+\/(?:[^/]+|write)$/,
    /^\/content\/[^/]+$/,
    /^\/members\/[^/]+$/,
    /^\/mypage\/(?:memos|qas)\/[^/]+$/,
    /^\/shop\/personalpay\/[^/]+\/pay$/,
    /^\/shop\/(?:categories|events|orders|personalpay|products)\/[^/]+$/,
  ].some((pattern) => pattern.test(path));
}

async function resolveSeoRoute(
  pathname: string,
  options: RouteOptions = {}
): Promise<string | null> {
  const path = pathname.replace(/\/+$/, "") || "/";
  const apiBase = apiBaseUrlForRuntime();
  const root = path.split("/")[1] || "";

  if (
    (RESERVED_ROOTS.has(root) && root !== "shop") ||
    path.startsWith("/admin/") ||
    path.startsWith("/boards/") ||
    path.startsWith("/mypage/")
  ) {
    return null;
  }

  const shopRoot = path.match(/^\/shop(?:\/([^/]+))?/);
  if (shopRoot && (!shopRoot[1] || isReservedShopSegment(shopRoot[1]))) {
    return null;
  }

  let match = path.match(/^\/shop\/([^/]+)$/);
  if (match && options.legacySeoPath) {
    return null;
  }

  match = path.match(/^\/content\/([^/]+)$/);
  if (match && options.legacySeoPath) {
    const content = await fetchJson<{ co_id?: string }>(
      `${apiBase}/content/seo/${encodeRouteSegment(match[1])}`
    );
    return content?.co_id ? `/content/${encodeURIComponent(content.co_id)}` : null;
  }

  match = path.match(/^\/([0-9A-Za-z_]+)\/([^/]+)$/);
  if (match && options.legacySeoPath && !RESERVED_ROOTS.has(match[1])) {
    return null;
  }

  return null;
}

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;

    const payload = await response.json();
    if (payload && payload.success && payload.data) {
      return payload.data as T;
    }
  } catch {
    return null;
  }

  return null;
}

export function LegacyRouteBridge() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    let cancelled = false;

    async function normalize() {
      const legacyPath = currentPathForRuntime(pathname || undefined);
      const rawPathname = window.location.pathname || "/";
      const legacySeoPath = legacyPath !== "/" && rawPathname.endsWith("/");
      const query = window.location.search || "";
      const hash = window.location.hash || "";
      const current = `${legacyPath}${query}${hash}`;
      const shortTarget = isG5ThemeRuntime() ? toG5ShortPath(current) : current;

      if (!cancelled && shortTarget !== current) {
        window.location.replace(g5PathForRuntime(shortTarget));
        return;
      }

      const target = legacySeoPath
        ? await resolveSeoRoute(legacyPath, { legacySeoPath })
        : null;

      if (!cancelled && target && target !== `${legacyPath}${query}`) {
        const targetWithHash = `${target}${query}${hash}`;
        if (isG5ThemeRuntime() || g5BasePathForRuntime() || requiresDocumentNavigation(target)) {
          window.location.replace(g5PathForRuntime(targetWithHash));
          return;
        }

        router.replace(targetWithHash);
      }
    }

    normalize();

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  return null;
}
