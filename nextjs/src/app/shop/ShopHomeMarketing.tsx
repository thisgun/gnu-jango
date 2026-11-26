"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUpRight, ShoppingBag } from "lucide-react";
import { ShopBannerCarousel } from "@/components/shop/ShopBannerCarousel";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopBanner } from "@/lib/api";
import { demoShopHeroBanner, selectShopBanners } from "@/lib/shop-banner";
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

function ShopCatalogHero({
  banner, loading = false, onImageError,
}: {
  banner?: ShopBanner;
  loading?: boolean;
  onImageError?: () => void;
}) {
  return (
    <section className="mx-auto w-full max-w-[1216px] pt-4 sm:pt-7" aria-labelledby="shop-hero-title">
      <div className="grid overflow-hidden rounded-[1.5rem] border border-base-300 bg-base-200 md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <div className="hero min-w-0 px-6 py-7 sm:px-9 sm:py-9 lg:px-12">
          <div className="hero-content w-full max-w-none flex-col items-start gap-0 p-0">
            <p className="text-xs font-semibold tracking-[0.12em] text-base-content/65">
              {banner ? "문구 · 데스크 · 커피" : "쇼핑몰"}
            </p>
            <h1 id="shop-hero-title" className="mt-3 text-balance text-[clamp(1.875rem,4vw,3.5rem)]! leading-[1.14]! font-semibold! tracking-[-0.055em] text-base-content md:max-w-[16ch]">
              {banner ? "작은 도구로 일상을 정돈하다" : "오늘 필요한 상품을 만나보세요"}
            </h1>
            <p className="mt-3 max-w-[30ch] text-pretty text-sm leading-6 text-base-content/75 lg:text-base">
              {banner
                ? "기록을 시작하는 노트부터 책상을 정돈하는 소품, 커피 한 잔을 준비하는 도구까지."
                : "카테고리별 상품과 새롭게 등록된 상품을 둘러보세요."}
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2 sm:mt-6">
              <Link href="/shop/products" className="btn btn-primary">
                전체 상품 보기 <ArrowUpRight size={16} aria-hidden />
              </Link>
              <a href="#shop-categories" className="btn btn-ghost">
                카테고리 <ArrowDown size={15} aria-hidden />
              </a>
            </div>
          </div>
        </div>
        <div className="relative grid aspect-[2/1] place-items-center overflow-hidden bg-base-300 md:aspect-[8/5] md:min-h-80 lg:min-h-[23rem]">
          {banner ? (
            /* This bundled image is already optimized and has the same URL in Django's static export. */
            <img
              alt="햇빛이 드는 책상 위에 펼친 노트와 커피잔"
              className="absolute inset-0 size-full object-cover object-[58%_50%]"
              src={banner.image_url}
              width={800}
              height={400}
              fetchPriority="high"
              onError={onImageError}
            />
          ) : loading ? (
            <div className="skeleton absolute inset-0 rounded-none" aria-hidden />
          ) : (
            <div className="grid size-31 place-items-center rounded-full border border-base-content/15 sm:size-42" aria-hidden>
              <ShoppingBag className="size-12 text-base-content/45 sm:size-16" strokeWidth={1.15} />
            </div>
          )}
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

  const demo = demoShopHeroBanner(runtimeBanners ?? banners);
  if (demo) {
    return (
      <ShopCatalogHero
        banner={failedBannerIds.includes(demo.bn_id) ? undefined : demo}
        onImageError={() => handleImageError(demo.bn_id)}
      />
    );
  }
  if (visibleBanners.length === 0) {
    return <ShopCatalogHero loading={runtimeBanners === null && banners.length === 0} />;
  }

  return (
    <>
      <h1 className="sr-only">쇼핑몰</h1>
      <ShopBannerCarousel
        key={visibleBanners.map((banner) => banner.bn_id).join(",")}
        banners={visibleBanners}
        reducedMotion={reducedMotion}
        onImageError={handleImageError}
      />
    </>
  );
}
