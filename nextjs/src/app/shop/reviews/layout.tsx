import type { ReactNode } from "react";
import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";

export const metadata: Metadata = buildPageMetadata({
  title: "사용후기",
  description: "쇼핑몰 상품 사용후기를 한곳에서 확인하세요.",
  path: "/shop/reviews",
});

export default function ShopReviewsLayout({ children }: { children: ReactNode }) {
  return children;
}
