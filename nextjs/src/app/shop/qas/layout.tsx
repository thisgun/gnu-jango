import type { ReactNode } from "react";
import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";

export const metadata: Metadata = buildPageMetadata({
  title: "상품문의",
  description: "쇼핑몰 상품문의와 답변 상태를 확인하세요.",
  path: "/shop/qas",
});

export default function ShopQasLayout({ children }: { children: ReactNode }) {
  return children;
}
