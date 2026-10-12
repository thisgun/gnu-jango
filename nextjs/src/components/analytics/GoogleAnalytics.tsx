"use client";

import Script from "next/script";
import { SENSITIVE_QUERY_PATHS } from "@/lib/sensitive-url";

/**
 * GA4 + Enhanced Ecommerce 부트.
 *   NEXT_PUBLIC_GA_ID 가 비어있으면 자동 noop — 빌드 영향 0.
 *
 * 사용:
 *   <GoogleAnalytics id={process.env.NEXT_PUBLIC_GA_ID} />
 *
 * 이커머스 이벤트는 lib/analytics.ts 의 헬퍼 사용 — viewItem / addToCart /
 * beginCheckout / purchase 등.
 *
 * 메일인증 · 비밀번호 재설정 · 소셜 로그인 페이지는 주소의 쿼리에 일회용 토큰이 실리므로
 * page_location 에서 쿼리를 뺀다 (lib/sensitive-url.ts).
 */
export function GoogleAnalytics({ id }: { id?: string }) {
  if (!id) return null;
  const sensitivePaths = JSON.stringify(SENSITIVE_QUERY_PATHS);
  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${id}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){ dataLayer.push(arguments); }
          window.gtag = gtag;
          var g5SensitivePaths = ${sensitivePaths};
          var g5Path = window.location.pathname.replace(/\\/+$/, '') || '/';
          var g5PageLocation = g5SensitivePaths.indexOf(g5Path) >= 0
            ? window.location.origin + window.location.pathname
            : window.location.href;
          gtag('js', new Date());
          gtag('config', '${id}', { anonymize_ip: true, send_page_view: true, page_location: g5PageLocation });
        `}
      </Script>
    </>
  );
}
