import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import { Suspense } from "react";
import LargeImageClientPage from "./ClientPage";
import ProductsLoading from "../products/ProductsLoading";

export function generateMetadata(): Metadata {
  return buildPageMetadata({
    title: "상품 이미지",
    description: "상품 상세 이미지를 확인하세요.",
    path: "/shop/largeimage",
  });
}

export default function LargeImagePage() {
  return (
    <Suspense fallback={<ProductsLoading />}>
      <LargeImageClientPage />
    </Suspense>
  );
}
