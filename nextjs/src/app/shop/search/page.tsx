import { createElement } from "react";
import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import ProductListPage from "../products/page";

export function generateMetadata(): Metadata {
  return buildPageMetadata({
    title: "상품 검색",
    description: "상품명과 분류로 쇼핑몰 상품을 검색하세요.",
    path: "/shop/search",
  });
}

export default function ShopSearchPage() {
  return createElement(ProductListPage);
}
