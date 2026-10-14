// @g5-server-runtime-only
import { NextRequest, NextResponse } from "next/server";

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

function productIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/shop\/([^/]+)\/?$/i);
  if (!match) return null;

  let productId: string;
  try {
    productId = decodeURIComponent(match[1]);
  } catch {
    return null;
  }

  const normalized = productId.replace(/\.php$/i, "").toLowerCase();
  if (
    !productId ||
    RESERVED_SHOP_SEGMENTS.has(normalized) ||
    /\.php$/i.test(productId) ||
    /^list-[0-9a-z]+$/i.test(productId) ||
    /^type-[1-5]$/i.test(productId)
  ) {
    return null;
  }

  return productId;
}

function apiBaseUrl(): string | null {
  const value = process.env.G5_API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL;
  return value?.trim().replace(/\/+$/, "") || null;
}

async function fetchProductStatus(url: string): Promise<number | null> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return response.status;
  } catch {
    return null;
  }
}

// Next 16 renamed middleware.ts to proxy.ts (it always runs on the Node.js runtime).
export async function proxy(request: NextRequest) {
  const productId = productIdFromPath(request.nextUrl.pathname);
  const baseUrl = apiBaseUrl();
  if (!productId || !baseUrl) return NextResponse.next();

  const encodedId = encodeURIComponent(productId);
  const idStatus = await fetchProductStatus(
    `${baseUrl}/shop/products/${encodedId}`
  );
  if (idStatus !== 404) return NextResponse.next();

  const seoStatus = await fetchProductStatus(
    `${baseUrl}/shop/products/seo/${encodedId}`
  );
  if (seoStatus === 200) {
    // SEO slugs are not part of the generated dynamic route params. Reuse the
    // generated shell so the client can resolve the slug and preserve the
    // configured canonical URL behavior.
    const destination = request.nextUrl.clone();
    destination.pathname = "/shop/products/__g5_static__";
    return NextResponse.rewrite(destination);
  }
  if (seoStatus !== 404) return NextResponse.next();

  return NextResponse.rewrite(new URL("/_not-found", request.url), {
    status: 404,
  });
}

export const config = {
  matcher: ["/shop/:productId"],
};
