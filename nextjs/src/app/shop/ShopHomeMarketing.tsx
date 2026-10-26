"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { ShopBannerCarousel } from "@/components/shop/ShopBannerCarousel";
import type { ShopBanner } from "@/lib/api";
import { selectShopBanners } from "@/lib/shop-banner";
import { getShopHomeData } from "@/services/shop-home";

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const preference = window.matchMedia(query);
    const update = () => setMatches(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** 배너를 받는 동안의 자리 — 진짜 배너와 같은 높이(.solune-banner-stage)라 응답 뒤에 아래가 밀리지 않는다. */
function ShopBannerSkeleton() {
  return (
    <div className="solune-shop-banner" aria-hidden="true">
      <div className="solune-banner">
        <div className="solune-banner-stage">
          <div className="skeleton absolute inset-0 rounded-none" />
        </div>
      </div>
    </div>
  );
}

/** 등록된 배너가 없을 때의 첫 화면 — 배너와 같은 높이에 상품 보기 안내. */
function ShopBannerEmpty() {
  return (
    <section className="solune-shop-banner" aria-label="등록된 쇼핑몰 배너 없음">
      <div className="solune-banner">
        <div className="solune-banner-stage flex items-center bg-base-200">
          <div className="mx-auto w-[min(100%_-_2rem,1216px)] space-y-4">
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-primary">Youngcart shop</p>
            <h1 className="text-3xl font-bold tracking-tight text-base-content md:text-5xl">오늘 필요한 상품을 만나보세요</h1>
            <p className="hidden text-base text-base-content/70 md:block">카테고리별 상품과 새롭게 등록된 상품을 둘러보세요.</p>
            <a href="/shop/products" className="btn btn-neutral btn-sm md:btn-md">
              전체 상품 보기 <ChevronRight className="size-4" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * 쇼핑 홈 메인 배너. 서버 모드는 배너를 HTML 에 구워 받고(banners), 정적 내보내기는 브라우저가 쇼핑 홈
 * 묶음(getShopHomeData)에서 받는다. 접속기기(PC · 모바일)와 받지 못한 그림을 걸러 ShopBannerCarousel 에 넘긴다.
 * 배너 묶음이 바뀌면 key 로 캐러셀을 새로 세운다(번호 · 받은 장 기억이 남은 묶음에 맞지 않으니까).
 */
export function ShopHomeBanners({ banners }: { banners: ShopBanner[] }) {
  const [runtimeBanners, setRuntimeBanners] = useState<ShopBanner[] | null>(null);
  const [failedBannerIds, setFailedBannerIds] = useState<number[]>([]);
  const isMobile = useMediaQuery("(max-width: 767px)");
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");

  useEffect(() => {
    let active = true;
    getShopHomeData()
      .then((home) => {
        if (active) setRuntimeBanners(home.banners);
      })
      .catch(() => {
        // 받지 못하면 서버가 구운 배너(없으면 빈 안내)로 둔다.
        if (active) setRuntimeBanners((current) => current ?? banners);
      });
    return () => {
      active = false;
    };
    // 처음 붙을 때 한 번 받는다. banners 는 서버가 구운 첫 값이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibleBanners = useMemo(
    () => selectShopBanners(runtimeBanners ?? banners, { isMobile, failedIds: failedBannerIds }),
    [runtimeBanners, banners, isMobile, failedBannerIds]
  );
  const handleImageError = useCallback((bannerId: number) => {
    if (!Number.isFinite(bannerId)) return;
    setFailedBannerIds((ids) => (ids.includes(bannerId) ? ids : [...ids, bannerId]));
  }, []);

  if (runtimeBanners === null && banners.length === 0) return <ShopBannerSkeleton />;
  if (visibleBanners.length === 0) return <ShopBannerEmpty />;

  return (
    <ShopBannerCarousel
      key={visibleBanners.map((banner) => banner.bn_id).join(",")}
      banners={visibleBanners}
      reducedMotion={reducedMotion}
      onImageError={handleImageError}
    />
  );
}
