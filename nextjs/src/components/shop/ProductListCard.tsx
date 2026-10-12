"use client";

import { useState } from "react";
import Image from "next/image";
import { PackageSearch } from "lucide-react";
import { ProductTypeBadges } from "@/components/shop/ProductGridSection";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { shouldBypassImageOptimization } from "@/lib/image";
import { shopProductHref } from "@/lib/product-url";
import { formatPrice } from "@/lib/utils";

export function ProductListCard({
  product,
  productRewriteMode,
}: {
  product: ShopProduct;
  productRewriteMode?: BbsRewriteMode;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const isTelInquiry = String(product.it_tel_inq ?? "0") === "1";
  const hasDiscount = !isTelInquiry && product.it_cust_price > 0 && product.it_cust_price > product.it_price;
  const discountPercent = hasDiscount
    ? Math.round(((product.it_cust_price - product.it_price) / product.it_cust_price) * 100)
    : 0;
  const showImage = Boolean(product.image_url && !imageFailed);

  return (
    <a href={shopProductHref(product, productRewriteMode)} className="product-list-card group">
      <div className="product-image-shell">
        {showImage ? (
          <Image
            src={product.image_url}
            alt={product.it_name}
            fill
            className="object-cover transition-transform group-hover:scale-[1.03]"
            sizes="96px"
            unoptimized={shouldBypassImageOptimization(product.image_url)}
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="product-placeholder">
            <PackageSearch aria-hidden="true" className="size-6" />
            <span>상품 이미지 없음</span>
          </div>
        )}
      </div>
      <div className="min-w-0 py-1">
        {product.ca_name && <p className="truncate text-xs font-medium text-[#5f6872]">{product.ca_name}</p>}
        <h3 className="mt-1 line-clamp-2 text-sm font-bold text-[#27313c] group-hover:text-primary">
          {product.it_name}
        </h3>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {hasDiscount && <span className="text-sm font-black text-[#b45309]">{discountPercent}%</span>}
          <span className="text-base font-black text-[#1f2933]">
            {isTelInquiry ? "전화문의" : formatPrice(product.it_price)}
          </span>
          {hasDiscount && (
            <span className="text-xs text-[#5f6872] line-through">{formatPrice(product.it_cust_price)}</span>
          )}
        </div>
        <ProductTypeBadges product={product} className="mt-2" />
      </div>
    </a>
  );
}
