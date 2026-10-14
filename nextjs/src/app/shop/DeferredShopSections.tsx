"use client";

import { useEffect, useState } from "react";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { ShopProductRow, ShopProductRowSkeleton } from "@/components/shop/ShopProductRow";
import { getShopHomeData } from "@/services/shop-home";

type SectionKey = "recommended" | "new" | "discount";

type ProductSections = Record<SectionKey, ShopProduct[]>;

const EMPTY_SECTIONS: ProductSections = {
  recommended: [],
  new: [],
  discount: [],
};

const LOADING_SECTION_LABELS = [
  { eyebrow: "NEW ARRIVAL", title: "최신상품", subtitle: "가장 최근에 등록된 상품입니다." },
  { eyebrow: "MD PICK", title: "추천상품", subtitle: "오래 쓰이는 것으로 골랐습니다." },
  { eyebrow: "SALE", title: "할인상품", subtitle: "지금 값을 내린 상품입니다." },
];

export function DeferredShopSections() {
  const [sections, setSections] = useState<ProductSections>(EMPTY_SECTIONS);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;

    getShopHomeData()
      .then((home) => {
        if (!alive) return;
        setError("");
        setSections({ recommended: home.products.type2, new: home.products.type3, discount: home.products.type5 });
        setProductRewriteMode(home.settings.cf_bbs_rewrite);
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
      <>
        {LOADING_SECTION_LABELS.map((section) => (
          <ShopProductRowSkeleton key={section.title} eyebrow={section.eyebrow} title={section.title} subtitle={section.subtitle} />
        ))}
      </>
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
      <ShopProductRow
        eyebrow="NEW ARRIVAL"
        title="최신상품"
        subtitle="가장 최근에 등록된 상품입니다."
        products={sections.new}
        viewAllHref="/shop/type-3"
        productRewriteMode={productRewriteMode}
      />
      <ShopProductRow
        eyebrow="MD PICK"
        title="추천상품"
        subtitle="오래 쓰이는 것으로 골랐습니다."
        products={sections.recommended}
        viewAllHref="/shop/type-2"
        productRewriteMode={productRewriteMode}
      />
      <ShopProductRow
        eyebrow="SALE"
        title="할인상품"
        subtitle="지금 값을 내린 상품입니다."
        products={sections.discount}
        viewAllHref="/shop/type-5"
        productRewriteMode={productRewriteMode}
      />
    </>
  );
}
