import type { ShopProduct, ShopReview } from "@/lib/api";
import { APP_BASE_URL } from "@/lib/config";
import { toG5ShortPath } from "@/lib/g5-short-url";

/**
 * schema.org JSON-LD 헬퍼 — 검색엔진이 상품 카드 / 별점 / 가격 / 재고를 직접 이해.
 *
 *   <ProductJsonLd product={...} reviews={...} />
 *   <BreadcrumbJsonLd items={[{name, url}, ...]} />
 *
 * Next.js App Router 에서는 <script type="application/ld+json"> 을 server
 * component 안에 직접 렌더하면 hydration warning 없이 SEO 효과 그대로.
 */

const SITE = APP_BASE_URL.replace(/\/+$/, "");

function jsonLdScript(payload: object) {
  return (
    <script
      type="application/ld+json"
      // dangerouslySetInnerHTML 대신 children string — Next.js 가 자동 escape.
      // schema.org spec 에서 JSON 본문은 사용자 입력 그대로 두면 XSS 위험이라
      // 안전하게 stringify 후 </script> 만 escape.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(payload).replace(/</g, "\\u003c"),
      }}
    />
  );
}

export function ProductJsonLd({
  product,
  reviews = [],
}: {
  product: ShopProduct;
  reviews?: ShopReview[];
}) {
  const url = `${SITE}${toG5ShortPath(`/shop/products/${product.it_id}`)}`;
  const inStock =
    product.it_soldout !== "1" && (product.it_stock_qty ?? 0) !== 0;

  const payload: Record<string, unknown> = {
    "@context": "https://schema.org/",
    "@type": "Product",
    name: product.it_name,
    description:
      (product.it_explan || product.it_basic || "").replace(/<[^>]+>/g, "").slice(0, 500),
    sku: product.it_id,
    brand: product.it_brand
      ? { "@type": "Brand", name: product.it_brand }
      : undefined,
    manufacturer: product.it_maker || undefined,
    countryOfOrigin: product.it_origin || undefined,
    image: product.images && product.images.length > 0 ? product.images : product.image_url,
    offers: {
      "@type": "Offer",
      url,
      priceCurrency: "KRW",
      price: product.it_price,
      availability: inStock
        ? "https://schema.org/InStock"
        : "https://schema.org/OutOfStock",
      itemCondition: "https://schema.org/NewCondition",
    },
  };

  // 후기 — 1건 이상 있으면 AggregateRating + 최신 review.
  if ((product.review_count ?? 0) > 0 && (product.review_avg ?? 0) > 0) {
    payload.aggregateRating = {
      "@type": "AggregateRating",
      ratingValue: product.review_avg,
      reviewCount: product.review_count,
    };
  }
  if (reviews.length > 0) {
    payload.review = reviews.slice(0, 3).map((r) => ({
      "@type": "Review",
      reviewRating: {
        "@type": "Rating",
        ratingValue: r.is_score,
        bestRating: 5,
      },
      author: { "@type": "Person", name: r.mb_nick || "익명" },
      reviewBody: (r.is_content || "").replace(/<[^>]+>/g, "").slice(0, 200),
    }));
  }

  return jsonLdScript(payload);
}

export function BreadcrumbJsonLd({
  items,
}: {
  items: { name: string; url?: string }[];
}) {
  return jsonLdScript({
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: it.name,
      ...(it.url ? { item: it.url.startsWith("http") ? it.url : `${SITE}${toG5ShortPath(it.url)}` } : {}),
    })),
  });
}

export function OrganizationJsonLd({
  name,
  logo,
  sameAs,
}: {
  name: string;
  logo?: string;
  sameAs?: string[];
}) {
  return jsonLdScript({
    "@context": "https://schema.org",
    "@type": "Organization",
    name,
    url: SITE,
    logo: logo ?? `${SITE}/og-default.png`,
    sameAs: sameAs ?? [],
  });
}

export function WebSiteJsonLd({ name }: { name: string }) {
  return jsonLdScript({
    "@context": "https://schema.org",
    "@type": "WebSite",
    name,
    url: SITE,
    potentialAction: {
      "@type": "SearchAction",
      target: `${SITE}/search?q={search_term_string}`,
      "query-input": "required name=search_term_string",
    },
  });
}
