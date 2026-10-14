import { RedirectIfAuthenticated } from "./redirect-if-authenticated";
import type { Metadata } from "next";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    // auth-page · auth-shell: 레퍼런스와 같은 손잡이 — solune-theme.internal-pages.css 가 폭(536 · 회원가입 640)과 카드 모양을 정한다.
    <div className="auth-page flex items-center justify-center min-h-[calc(100vh-8rem)] py-12 px-4">
      <div className="auth-shell w-full max-w-md">
        <RedirectIfAuthenticated>{children}</RedirectIfAuthenticated>
      </div>
    </div>
  );
}
