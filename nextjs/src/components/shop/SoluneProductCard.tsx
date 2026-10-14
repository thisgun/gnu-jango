"use client";

import { GalleryThumbnail } from "@/app/boards/[bo_table]/GalleryThumbnail";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { shopProductHref } from "@/lib/product-url";
import { formatProductPrice, isProductSoldOut, productDiscountPercent } from "@/lib/shop-product-state";
import { formatNumber, formatPrice } from "@/lib/utils";
import { CompareToggleButton } from "./ProductGridSection";
import { ProductImageFallback } from "./ProductImageFallback";
import { ProductQuickAdd } from "./ProductQuickAdd";

interface SoluneProductCardProps {
  product: ShopProduct;
  priority?: boolean;
  productRewriteMode?: BbsRewriteMode;
}

/**
 * 레퍼런스 온담 상품 카드(sct_li, 레퍼런스 테마 product-card.tsx). 정사각 사진 · 브랜드 · 이름 ·
 * 할인율/판매가/정가 · 별점/리뷰/담기. 모양은 solune-shop.home.css · solune-shop.list.css 가 입히고,
 * 목록의 리스트/갤러리 모양은 감싼 .shop-product-list 의 data-view 로 CSS 가 정한다.
 * 사진 칸은 링크 안에 단추를 둘 수 없어 div 로 두고 링크를 그 안에 깐다 — 비교 단추(⇄)가 사진 위에 함께 놓인다.
 */
export function SoluneProductCard({ product, priority = false, productRewriteMode }: SoluneProductCardProps) {
  const href = shopProductHref(product, productRewriteMode);
  const discount = productDiscountPercent(product);
  const brand = product.it_brand || product.it_maker || product.ca_name || "";
  const rating = Number(product.review_avg ?? 0);
  const image = product.image_url?.trim() ?? "";

  return (
    <article className="sct_li group">
      <div className="sct_img">
        <Link href={href} className="absolute inset-0 block" aria-label={product.it_name}>
          {image ? (
            <GalleryThumbnail src={image} alt={product.it_name} sizes="(max-width: 780px) 50vw, 300px" priority={priority} />
          ) : (
            <ProductImageFallback compact />
          )}
        </Link>
        {String(product.it_type3 ?? "0") === "1" ? <span className="ondam-card-badge">NEW</span> : null}
        {isProductSoldOut(product) ? <span className="ondam-card-soldout">SOLD OUT</span> : null}
        {/* 레퍼런스에 없는 이 앱의 상품 비교 담기 — 마우스를 올렸을 때만 보이고, NEW 표와 겹치지 않게 사진 오른쪽 아래에 둔다. */}
        <div className="ondam-card-compare absolute bottom-2 right-2 z-10 [&>button]:static">
          <CompareToggleButton product={product} />
        </div>
      </div>
      {brand ? <p className="ondam-card-brand">{brand}</p> : null}
      <Link className="sct_txt" href={href}>
        {product.it_name}
      </Link>
      <div className="ondam-card-prices">
        {discount > 0 ? <span className="ondam-card-off">{discount}%</span> : null}
        <span className="ondam-card-now">{formatProductPrice(product)}</span>
        {discount > 0 ? <span className="ondam-card-was">{formatPrice(product.it_cust_price)}</span> : null}
      </div>
      <div className="ondam-card-meta">
        {rating > 0 ? <span className="ondam-card-star">★ {rating.toFixed(1)}</span> : null}
        <span>리뷰 {formatNumber(Number(product.review_count ?? 0))}</span>
        <ProductQuickAdd product={product} href={href} className="ondam-card-add" />
      </div>
    </article>
  );
}
