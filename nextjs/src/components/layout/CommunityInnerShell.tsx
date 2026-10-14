"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { stripG5BasePath } from "@/lib/config";
import { CommunitySidebar } from "./CommunitySidebar";

/**
 * 레퍼런스(Solune layout-shell)처럼 커뮤니티 안쪽 페이지에는 오른쪽 레일을 레이아웃이 붙인다.
 * 홈은 제 레일을 직접 그리고, 쇼핑 · 마이페이지 · 인증 화면은 제 레이아웃(또는 사이드바)이 있어
 * 레일을 덧대면 두 겹이 된다. 그 경로만 뺀다. 레퍼런스는 /bbs(옛 PHP 주소)도 빼지만 여기서는
 * /bbs/{게시판} 이 공개 게시판 주소라 레일을 둔다.
 */
const RAIL_EXCLUDED_PREFIXES = [
  "/shop",
  "/mypage",
  "/login",
  "/register",
  "/forgot-password",
  "/email-certify",
  "/baby",
  "/organic",
];

export function shouldShowCommunityRail(pathname: string): boolean {
  if (pathname === "/" || pathname === "" || pathname === "/community") return false;
  return !RAIL_EXCLUDED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

function isShopPath(pathname: string): boolean {
  return pathname === "/shop" || pathname.startsWith("/shop/");
}

export function CommunityInnerShell({ children }: { children: ReactNode }) {
  const routerPath = usePathname() || "/";
  // Django 가 내보낸 정적 테마는 자리표시 경로(__g5_static__)로 그려지므로, 붙은 뒤 주소창의 실제 경로로 다시 고른다.
  // 읽은 주소창 경로는 그때의 라우터 경로와 함께 둔다 — 화면을 옮긴 직후에는 아직 옛 경로라, 그대로 쓰면
  // 한 프레임을 옛 레이아웃(레일 유무)으로 그렸다가 바뀌며 페이지 전체가 다시 마운트된다.
  const [browser, setBrowser] = useState<{ forPath: string; path: string } | null>(null);
  useEffect(() => {
    setBrowser({ forPath: routerPath, path: stripG5BasePath(window.location.pathname) || "/" });
  }, [routerPath]);
  const browserPath = browser && browser.forPath === routerPath ? browser.path : null;

  // 쇼핑몰은 레퍼런스 shop-shell 처럼 제 레이아웃(app/shop/layout.tsx)이 <main id="main-content" class="shop-content"> 를 그린다.
  // 쇼핑몰 CSS 가 ".solune-shop-page main …" 으로 안쪽 페이지를 잡으므로 여기서는 main 을 겹치지 않는다.
  // 정적 테마의 자리표시 경로도 /shop 아래라 서버 렌더와 붙은 뒤의 판단이 같다.
  if (isShopPath(routerPath)) {
    // 열(flex column)로 두어 .solune-shop-page 가 푸터까지 남은 높이를 채운다 — 짧은 페이지 아래에 커뮤니티 바탕이 비치지 않게.
    return <div className="flex flex-1 flex-col overflow-x-clip">{children}</div>;
  }

  if (!shouldShowCommunityRail(browserPath ?? routerPath)) {
    return (
      <main id="main-content" className="flex-1 overflow-x-clip">
        {children}
      </main>
    );
  }

  return (
    <div className="solune-content-shell solune-inner-shell">
      <main id="main-content" className="solune-main-content">
        {children}
      </main>
      <CommunitySidebar />
    </div>
  );
}
