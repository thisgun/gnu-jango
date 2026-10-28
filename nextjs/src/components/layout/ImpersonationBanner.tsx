"use client";

import { useEffect, useState } from "react";
import { Eye } from "lucide-react";
import {
  IMPERSONATION_STOP_PATH,
  formatRemaining,
  impersonationExpiryFromCookie,
} from "@/lib/impersonation-banner";

// Shown while an admin previews the storefront as a member. Rendered only after mount, so the
// static HTML and the hydrated tree stay identical for every other visitor.
export function ImpersonationBanner() {
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);

  useEffect(() => {
    const initial = impersonationExpiryFromCookie(document.cookie);
    setExpiresAt(initial);
    setNow(Date.now());
    if (initial === null) return;

    const timer = window.setInterval(() => {
      setExpiresAt(impersonationExpiryFromCookie(document.cookie));
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (expiresAt === null) return null;
  const expired = now >= expiresAt * 1000;

  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-4 z-[70] mx-auto flex w-[calc(100%-2rem)] max-w-2xl flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-950 shadow-lg"
    >
      <Eye className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="font-semibold">관리자 회원 미리보기</span>
      <span>
        {expired
          ? "미리보기 시간이 끝났습니다."
          : `읽기 전용입니다. 주문·글쓰기·정보 변경은 막혀 있습니다. 남은 시간 ${formatRemaining(expiresAt, now)}`}
      </span>
      <a
        href={IMPERSONATION_STOP_PATH}
        className="rounded-md bg-amber-900 px-3 py-1 font-semibold text-amber-50 hover:bg-amber-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-900"
      >
        미리보기 종료
      </a>
    </div>
  );
}
