"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ProductGridSection } from "@/components/shop/ProductGridSection";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { getShopProductList } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";

export function ShopHomePopular() {
  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;

    Promise.all([
      getShopProductList({ it_type4: "1", per_page: 8 }),
      getClientPublicSettings(),
    ])
      .then(([popular, settings]) => {
        if (!alive) return;
        setProducts(popular.products);
        setProductRewriteMode(settings.cf_bbs_rewrite);
        setError(false);
      })
      .catch(() => {
        if (!alive) return;
        setProducts([]);
        setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <section className="home-product-section shop-home-product-row shop-home-popular-section" aria-label="많이 보고 계신 상품 로딩 중">
        <div className="home-product-head">
          <div>
            <p className="home-product-eyebrow">POPULAR</p>
            <div className="h-6 w-28 rounded bg-muted" />
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <div className="size-9 border border-base-300 bg-base-100" />
            <div className="size-9 border border-base-300 bg-base-100" />
            <div className="ml-1 h-4 w-14 rounded bg-muted" />
          </div>
        </div>
        <div className="scrollbar-hide grid w-full min-w-0 max-w-full grid-flow-col auto-cols-[minmax(132px,37%)] gap-1 overflow-x-auto overscroll-x-contain pb-4 sm:auto-cols-[30%] sm:gap-2 md:auto-cols-[26%] md:gap-4 lg:auto-cols-[16%]">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="space-y-3">
              <div className="aspect-square rounded-[8px] bg-muted" />
              <div className="h-4 w-3/4 rounded bg-muted" />
              <div className="h-4 w-1/2 rounded bg-muted" />
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (error || products.length === 0) {
    return (
      <EmptyState
        className="mb-8"
        title="표시할 상품이 없습니다"
        description="상품을 등록하면 쇼핑몰 첫 화면에 표시됩니다."
      />
    );
  }

  return (
    <ProductGridSection
      eyebrow="POPULAR"
      title="많이 보고 계신 상품"
      products={products}
      viewAllHref="/shop/type-4"
      viewAllLabel="전체 보기"
      productRewriteMode={productRewriteMode}
      scroll
      compactCarousel
      className="home-product-section shop-home-popular-section"
    />
  );
}
