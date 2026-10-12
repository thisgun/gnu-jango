import type { ReactNode } from "react";
import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";

export const metadata: Metadata = buildPageMetadata({
  title: "상품 리뷰",
  description: "구매자 상품 리뷰를 확인하세요.",
  path: "/shop/reviews",
});

export default function ShopReviewsLayout({ children }: { children: ReactNode }) {
  return children;
}
