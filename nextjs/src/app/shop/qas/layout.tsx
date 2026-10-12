import type { ReactNode } from "react";
import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";

export const metadata: Metadata = buildPageMetadata({
  title: "상품 문의",
  description: "상품 문의와 답변을 확인하세요.",
  path: "/shop/qas",
});

export default function ShopQasLayout({ children }: { children: ReactNode }) {
  return children;
}
