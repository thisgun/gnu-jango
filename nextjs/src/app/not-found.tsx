"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useRouter } from "@bprogress/next/app";
import { ShopFooter } from "@/components/layout/Footer";
import { Button } from "@/components/ui/button";

/**
 * 없는 주소의 쇼핑몰 경로(/shop/…)는 app/shop/layout.tsx 를 거치지 않고 루트 레이아웃 아래에서 이 화면만 그려진다.
 * 루트는 쇼핑몰 경로에서 <main> 과 커뮤니티 푸터를 그리지 않으므로(CommunityInnerShell · Footer), 쇼핑몰 레이아웃과
 * 같은 틀과 쇼핑몰 푸터를 여기서 둘러 본문 바로가기 · 푸터가 빠지지 않게 한다.
 */
function ShopFrame({ children }: { children: ReactNode }) {
  return (
    <div className="solune-shop-page">
      <div className="solune-shop-wrapper">
        <div className="solune-shop-container">
          <main id="main-content" className="shop-content">{children}</main>
        </div>
      </div>
      <ShopFooter />
    </div>
  );
}

export default function NotFound() {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const isShop = pathname === "/shop" || pathname.startsWith("/shop/");

  const content = (
    <div className="container mx-auto px-4 flex flex-col items-center justify-center min-h-[60vh] text-center">
      <p className="text-7xl font-bold text-muted-foreground">404</p>
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        페이지를 찾을 수 없습니다
      </h1>
      <p className="mt-2 text-muted-foreground max-w-md">
        요청하신 페이지가 존재하지 않거나 이동되었을 수 있습니다.
        주소를 다시 확인해 주세요.
      </p>
      <div className="mt-8 flex gap-3">
        <Button asChild>
          <Link href={isShop ? "/shop" : "/"}>{isShop ? "쇼핑몰로 돌아가기" : "홈으로 돌아가기"}</Link>
        </Button>
        <Button variant="outline" onClick={() => router.back()}>
          이전 페이지
        </Button>
      </div>
    </div>
  );

  return isShop ? <ShopFrame>{content}</ShopFrame> : content;
}
