"use client";

import { useEffect } from "react";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import {
  applyClientJsonLd,
  applyClientPageMetadata,
  clientAbsoluteUrl,
  plainTextSummary,
} from "@/lib/client-metadata";
import { g5ShortHref } from "@/lib/g5-short-url";
import { shopProductPath } from "@/lib/product-url";
import { isProductDetailSoldOut } from "@/components/shop/productDetailHelpers";

/**
 * 상품을 받으면 문서 제목 · 설명 · 대표 주소와 구조화 데이터(Product · BreadcrumbList)를 맞춘다
 * (레퍼런스 앱 useProductDetailMetadata 와 같은 나눔). 정적 셸로 열린 상품도 검색엔진이 같은 값을 읽는다.
 */
export function useProductDetailMetadata(
  product: ShopProduct | null,
  productRewriteMode: BbsRewriteMode
): void {
  useEffect(() => {
    if (!product) return;
    const productPath = shopProductPath(product, productRewriteMode);
    const canonical = new URL(g5ShortHref(productPath), window.location.origin).toString();
    const imageUrls = (product.images?.length ? product.images : [product.image_url])
      .map((image) => (image ? clientAbsoluteUrl(image) : undefined))
      .filter(Boolean) as string[];
    const description = product.it_explan || product.it_basic || product.it_name;

    applyClientPageMetadata({
      title: product.it_name,
      description,
      path: productPath,
      // 공유 미리보기에는 원본 — image_url 은 목록용 400px 사본이다.
      image: product.images?.[0] || product.image_url,
    });
    applyClientJsonLd("article", null);
    applyClientJsonLd("product", {
      "@context": "https://schema.org/",
      "@type": "Product",
      name: product.it_name,
      description: plainTextSummary(description, product.it_name),
      sku: product.it_id,
      ...(product.it_brand ? { brand: { "@type": "Brand", name: product.it_brand } } : {}),
      ...(product.it_maker ? { manufacturer: product.it_maker } : {}),
      ...(product.it_origin ? { countryOfOrigin: product.it_origin } : {}),
      ...(imageUrls.length > 0 ? { image: imageUrls } : {}),
      offers: {
        "@type": "Offer",
        url: canonical,
        priceCurrency: "KRW",
        price: product.it_price,
        // 화면의 품절과 같은 판정(영카트 is_soldout — 선택옵션이 모두 품절이어도 품절).
        availability: isProductDetailSoldOut(product)
          ? "https://schema.org/OutOfStock"
          : "https://schema.org/InStock",
        itemCondition: "https://schema.org/NewCondition",
      },
      ...(product.review_count && product.review_avg
        ? {
            aggregateRating: {
              "@type": "AggregateRating",
              ratingValue: product.review_avg,
              reviewCount: product.review_count,
            },
          }
        : {}),
    });
    applyClientJsonLd("breadcrumb", {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "쇼핑몰",
          item: new URL(g5ShortHref("/shop"), window.location.origin).toString(),
        },
        ...(product.ca_id && product.ca_name
          ? [
              {
                "@type": "ListItem",
                position: 2,
                name: product.ca_name,
                item: new URL(
                  g5ShortHref(`/shop/categories/${product.ca_id}`),
                  window.location.origin
                ).toString(),
              },
            ]
          : []),
        {
          "@type": "ListItem",
          position: product.ca_id && product.ca_name ? 3 : 2,
          name: product.it_name,
          item: canonical,
        },
      ],
    });
  }, [product, productRewriteMode]);
}
