"use client";

import { useEffect, useState } from "react";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { ProductGridSection } from "@/components/shop/ProductGridSection";
import { getShopProductList } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";

type SectionKey = "recommended" | "new" | "discount";

type ProductSections = Record<SectionKey, ShopProduct[]>;

const EMPTY_SECTIONS: ProductSections = {
  recommended: [],
  new: [],
  discount: [],
};

const LOADING_SECTION_LABELS = [
  { eyebrow: "NEW ARRIVAL", title: "최신상품" },
  { eyebrow: "MD PICK", title: "추천상품" },
  { eyebrow: "SALE", title: "할인상품" },
];

export function DeferredShopSections() {
  const [sections, setSections] = useState<ProductSections>(EMPTY_SECTIONS);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;

    Promise.all([
      getShopProductList({ it_type2: "1", per_page: 8 }),
      getShopProductList({ it_type3: "1", per_page: 8 }),
      getShopProductList({ it_type5: "1", per_page: 8 }),
      getClientPublicSettings(),
    ])
      .then(([recommended, latest, discount, settings]) => {
        if (!alive) return;
        setError("");
        setSections({
          recommended: recommended.products,
          new: latest.products,
          discount: discount.products,
        });
        setProductRewriteMode(settings.cf_bbs_rewrite);
      })
      .catch(() => {
        if (!alive) return;
        setSections(EMPTY_SECTIONS);
        setError("상품 섹션을 불러오지 못했습니다.");
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
      <div aria-label="상품 섹션 로딩 중" className="space-y-8">
        {LOADING_SECTION_LABELS.map((section) => (
          <section key={section.title} className="home-product-section shop-home-product-row">
            <div className="home-product-head">
              <div className="space-y-2">
                <p className="home-product-eyebrow">{section.eyebrow}</p>
                <div className="h-6 w-32 rounded bg-muted" aria-label={section.title} />
                <div className="h-4 w-48 rounded bg-muted" />
              </div>
              <div className="h-4 w-14 rounded bg-muted" />
            </div>
            <div className="scrollbar-hide grid w-full min-w-0 max-w-full grid-flow-col auto-cols-[minmax(132px,37%)] gap-1 overflow-x-auto overscroll-x-contain pb-4 sm:auto-cols-[30%] sm:gap-2 md:auto-cols-[26%] md:gap-4 lg:auto-cols-[16%]">
              {Array.from({ length: 4 }).map((__, itemIndex) => (
                <div key={itemIndex} className="space-y-3">
                  <div className="aspect-square rounded-[8px] bg-muted" />
                  <div className="h-4 w-3/4 rounded bg-muted" />
                  <div className="h-4 w-1/2 rounded bg-muted" />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p role="status" className="rounded-[4px] border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }

  if (
    sections.recommended.length === 0 &&
    sections.new.length === 0 &&
    sections.discount.length === 0
  ) {
    return null;
  }

  return (
    <>
      {sections.new.length > 0 && (
        <ProductGridSection
          eyebrow="NEW ARRIVAL"
          title="최신상품"
          subtitle="가장 최근에 등록된 상품입니다."
          products={sections.new}
          viewAllHref="/shop/type-3"
          viewAllLabel="전체 보기"
          productRewriteMode={productRewriteMode}
          scroll
          compactCarousel
        />
      )}
      {sections.recommended.length > 0 && (
        <ProductGridSection
          eyebrow="MD PICK"
          title="추천상품"
          subtitle="오래 쓰이는 것으로 골랐습니다."
          products={sections.recommended}
          viewAllHref="/shop/type-2"
          viewAllLabel="전체 보기"
          productRewriteMode={productRewriteMode}
          scroll
          compactCarousel
        />
      )}
      {sections.discount.length > 0 && (
        <ProductGridSection
          eyebrow="SALE"
          title="할인상품"
          subtitle="지금 값을 내린 상품입니다."
          products={sections.discount}
          viewAllHref="/shop/type-5"
          viewAllLabel="전체 보기"
          productRewriteMode={productRewriteMode}
          scroll
          compactCarousel
        />
      )}
    </>
  );
}
