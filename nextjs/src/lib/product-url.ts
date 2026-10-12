import type { ShopProduct } from "@/lib/api";
import { isBbsSeoRewrite, type BbsRewriteMode } from "@/lib/board-url";
import { g5ShortHref } from "@/lib/g5-short-url";

type ProductUrlSource = Pick<ShopProduct, "it_id"> & Partial<Pick<ShopProduct, "it_seo_title">>;

const RESERVED_SHOP_SEGMENTS = new Set([
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

const LEGACY_SHOP_SEGMENTS = new Set([
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

function encodeRouteSegment(value: string): string {
  const trimmed = value.trim();
  if (trimmed === ".") return "%2E";
  if (trimmed === "..") return "%2E%2E";

  try {
    return encodeURIComponent(decodeURIComponent(trimmed));
  } catch {
    return encodeURIComponent(trimmed);
  }
}

function normalizeShopSegment(value: string): string {
  return value.replace(/\.php$/i, "").toLowerCase();
}

function isReservedShopSegment(value: string): boolean {
  const normalized = normalizeShopSegment(value);
  return RESERVED_SHOP_SEGMENTS.has(normalized) || LEGACY_SHOP_SEGMENTS.has(normalized);
}

function safeProductSeoTitle(product: ProductUrlSource): string {
  const seoTitle = String(product.it_seo_title || "").trim();
  if (!seoTitle) return "";

  const normalized = seoTitle.replace(/^\/+|\/+$/g, "");
  if (
    !normalized ||
    normalized === "." ||
    normalized === ".." ||
    normalized.includes("/") ||
    normalized.includes("\\") ||
    isReservedShopSegment(normalized) ||
    /^list-[0-9a-z]+$/i.test(normalized) ||
    /^type-[1-5]$/i.test(normalized)
  ) {
    return "";
  }

  return normalized;
}

export function shopProductPath(
  product: ProductUrlSource,
  rewriteMode?: BbsRewriteMode
): string {
  const seoTitle = safeProductSeoTitle(product);
  if (isBbsSeoRewrite(rewriteMode) && seoTitle) {
    return `/shop/products/${encodeRouteSegment(seoTitle)}/`;
  }

  return `/shop/products/${encodeRouteSegment(String(product.it_id))}`;
}

export function shopProductHref(
  product: ProductUrlSource,
  rewriteMode?: BbsRewriteMode
): string {
  return g5ShortHref(shopProductPath(product, rewriteMode));
}
