import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import LoginPageClient from "./LoginPageClient";

export const metadata: Metadata = buildPageMetadata({
  title: "로그인",
  description: "그누보드5 계정으로 로그인합니다.",
  path: "/login",
  noindex: true,
});

export default function LoginPage() {
  return <LoginPageClient />;
}
