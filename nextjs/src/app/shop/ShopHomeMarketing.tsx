"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { ShopBanner } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getShopHomeData } from "@/services/shop-home";
import { ArrowRight, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";

const DEMO_SAMPLE_BANNER_ALT = "차분한 일상을 위한 데모 스토어";

const DEMO_SAMPLE_BANNER_FALLBACKS: ShopBanner[] = [
  {
    bn_id: -2,
    bn_alt: "DESK OBJECTS|책상 위를 더 가볍게",
    bn_url: "/shop/type-1",
    bn_position: "메인",
    bn_device: "both",
    bn_border: 0,
    bn_new_win: 0,
    bn_order: 2,
    image_url: "/sample-data/product-02.webp",
  },
  {
    bn_id: -3,
    bn_alt: "SLOW KITCHEN|매일 쓰는 도구의 온기",
    bn_url: "/shop/type-2",
    bn_position: "메인",
    bn_device: "both",
    bn_border: 0,
    bn_new_win: 0,
    bn_order: 3,
    image_url: "/sample-data/product-04.webp",
  },
];

function withDemoSampleRotation(banners: ShopBanner[]) {
  if (banners.length !== 1 || banners[0].bn_alt.trim() !== DEMO_SAMPLE_BANNER_ALT) {
    return banners;
  }

  return [
    { ...banners[0], bn_alt: `DESK NOTES|${DEMO_SAMPLE_BANNER_ALT}` },
    ...DEMO_SAMPLE_BANNER_FALLBACKS,
  ];
}

function isExternalUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function ShopHomeBanners({ banners }: { banners: ShopBanner[] }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [runtimeBanners, setRuntimeBanners] = useState<ShopBanner[] | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [failedBannerIds, setFailedBannerIds] = useState<number[]>([]);
  const allBanners = withDemoSampleRotation(runtimeBanners ?? banners).filter(
    (banner) => banner.image_url && !failedBannerIds.includes(banner.bn_id)
  );
  const deviceBanners = allBanners.filter((banner) =>
    isMobile
      ? !["pc", "desktop"].includes(banner.bn_device.toLowerCase())
      : !["mobile"].includes(banner.bn_device.toLowerCase())
  );
  const visibleBanners = deviceBanners.length > 0 ? deviceBanners : allBanners;

  useEffect(() => {
    let active = true;
    getShopHomeData()
      .then((home) => {
        if (active) setRuntimeBanners(withDemoSampleRotation(home.banners));
      }).catch(() => undefined);

    return () => { active = false; };
  }, []);

  useEffect(() => {
    const failedIds = Array.from(
      trackRef.current?.querySelectorAll<HTMLImageElement>("img[data-banner-id]") ?? []
    )
      .filter((image) => image.complete && image.naturalWidth === 0)
      .map((image) => Number(image.dataset.bannerId))
      .filter((bannerId) => Number.isFinite(bannerId));

    if (failedIds.length === 0) return;

    setFailedBannerIds((current) => {
      const additions = failedIds.filter((bannerId) => !current.includes(bannerId));
      return additions.length > 0 ? [...current, ...additions] : current;
    });
  }, [visibleBanners]);

  useEffect(() => {
    const preference = window.matchMedia("(max-width: 767px)");
    const updatePreference = () => setIsMobile(preference.matches);
    updatePreference();
    preference.addEventListener("change", updatePreference);
    return () => preference.removeEventListener("change", updatePreference);
  }, []);

  useEffect(() => {
    setActiveIndex((index) => Math.min(index, Math.max(0, visibleBanners.length - 1)));
  }, [visibleBanners.length]);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = () => setReducedMotion(preference.matches);
    updatePreference();
    preference.addEventListener("change", updatePreference);
    return () => preference.removeEventListener("change", updatePreference);
  }, []);

  useEffect(() => {
    if (visibleBanners.length < 2 || !playing || hovered || focused || reducedMotion) return;

    const timer = window.setInterval(() => {
      const nextIndex = (activeIndex + 1) % visibleBanners.length;
      const track = trackRef.current;
      if (track) {
        track.scrollTo({ left: nextIndex * track.clientWidth, behavior: "smooth" });
      }
      setActiveIndex(nextIndex);
    }, 5000);

    return () => window.clearInterval(timer);
  }, [activeIndex, focused, hovered, playing, reducedMotion, visibleBanners.length]);

  const goTo = (index: number) => {
    const nextIndex = (index + visibleBanners.length) % visibleBanners.length;
    const track = trackRef.current;
    if (track) {
      track.scrollTo({
        left: nextIndex * track.clientWidth,
        behavior: reducedMotion ? "auto" : "smooth",
      });
    }
    setActiveIndex(nextIndex);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      goTo(activeIndex - 1);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      goTo(activeIndex + 1);
    }
  };

  return (
    <section
      className="relative isolate w-screen -translate-x-1/2 overflow-hidden bg-base-200"
      style={{ left: "50%" }}
      aria-label={visibleBanners.length > 0 ? "쇼핑몰 추천 배너" : "등록된 쇼핑몰 배너 없음"}
      aria-roledescription={visibleBanners.length > 0 ? "carousel" : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onTouchStart={() => setHovered(true)}
      onTouchEnd={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
      onKeyDown={handleKeyDown}
    >
      {visibleBanners.length > 0 ? (
        <>
          <div
            ref={trackRef}
            className="carousel carousel-center w-full overflow-x-auto scroll-smooth"
            aria-live="off"
            onScroll={(event) => {
              const track = event.currentTarget;
              const index = Math.round(track.scrollLeft / Math.max(track.clientWidth, 1));
              setActiveIndex(Math.min(index, visibleBanners.length - 1));
            }}
          >
            {visibleBanners.map((banner, index) => {
              const href = banner.hit_url || `/shop/bannerhit.php?bn_id=${encodeURIComponent(String(banner.bn_id))}`;
              const openNew = banner.bn_new_win === 1 || isExternalUrl(banner.bn_url);
              const [bannerEyebrow = "", ...headingParts] = (banner.bn_alt || "").split("|");
              const bannerHeading = headingParts.join("|").trim();
              const eyebrow = bannerEyebrow.trim();
              const hasBannerCopy = Boolean(eyebrow && bannerHeading);

              return (
                <div
                  key={banner.bn_id}
                  id={`shop-banner-${banner.bn_id}`}
                  className="carousel-item w-full"
                  role="group"
                  aria-roledescription="slide"
                  aria-label={`${index + 1} / ${visibleBanners.length}`}
                >
                  <a
                    href={href}
                    target={openNew ? "_blank" : undefined}
                    rel={openNew ? "noopener noreferrer" : undefined}
                    aria-label={hasBannerCopy ? `${eyebrow}: ${bannerHeading}` : undefined}
                    className={cn(
                      "solune-shop-banner-slide group relative block aspect-[1.5/1] max-h-[690px] w-full overflow-hidden bg-base-200 md:aspect-[2.05/1]",
                      banner.bn_border === 1 && "border-y border-base-300"
                    )}
                  >
                    <img
                      src={banner.image_url}
                      data-banner-id={banner.bn_id}
                      aria-hidden={hasBannerCopy}
                      alt={banner.bn_alt || `쇼핑몰 배너 ${index + 1}`}
                      className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.01]"
                      loading={index === 0 ? "eager" : "lazy"}
                      onError={() => setFailedBannerIds((ids) =>
                        ids.includes(banner.bn_id) ? ids : [...ids, banner.bn_id]
                      )}
                    />
                    {hasBannerCopy && (
                      <div className="pointer-events-none absolute inset-0 flex items-center bg-gradient-to-r from-base-100/70 via-base-100/35 to-transparent px-5 text-base-content sm:px-8 md:px-16 lg:px-[max(calc((100vw-1216px)/2),6rem)]">
                        <div className="-translate-y-6 max-w-[32rem] md:max-w-[40rem] lg:max-w-[42rem]">
                          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-base-content/70 sm:text-xs">
                            {eyebrow}
                          </p>
                          {/* 레퍼런스 shop-banner 처럼 제목은 strong — 쇼핑몰 CSS 의 "main h2"(16px) 규칙에 걸리지 않는다. */}
                          <strong className="mt-2 block text-[26px] font-bold leading-snug sm:text-3xl md:text-4xl lg:text-[3.5rem]">
                            {bannerHeading}
                          </strong>
                          <span className="btn btn-neutral btn-sm mt-3 min-h-10 gap-2 rounded-none px-5">
                            자세히 보기 <ArrowRight className="size-4" />
                          </span>
                        </div>
                      </div>
                    )}
                  </a>
                </div>
              );
            })}
          </div>
          {visibleBanners.length > 1 && (
            <>
              <div className="pointer-events-none absolute inset-x-0 top-1/2 z-10 hidden -translate-y-1/2 justify-between px-3 md:flex md:px-[max(calc((100vw-1216px)/2),1.5rem)]">
                <button
                  type="button"
                  className="btn btn-circle btn-sm pointer-events-auto border-base-300 bg-base-100/90 text-base-content shadow-sm md:btn-md"
                  onClick={() => goTo(activeIndex - 1)}
                  aria-label="이전 배너"
                >
                  <ChevronLeft className="size-5" />
                </button>
                <button
                  type="button"
                  className="btn btn-circle btn-sm pointer-events-auto border-base-300 bg-base-100/90 text-base-content shadow-sm md:btn-md"
                  onClick={() => goTo(activeIndex + 1)}
                  aria-label="다음 배너"
                >
                  <ChevronRight className="size-5" />
                </button>
              </div>
              <div className="absolute inset-x-4 bottom-3 z-10 flex items-center justify-between md:inset-x-[max(calc((100vw-1216px)/2),1.5rem)] md:bottom-8">
                <div className="flex items-center gap-1.5" role="group" aria-label="배너 선택">
                  {visibleBanners.map((banner, index) => (
                    <button
                      key={banner.bn_id}
                      type="button"
                      className={cn(
                        "h-1 rounded-full transition-all",
                        index === activeIndex ? "w-6 bg-base-content" : "w-6 bg-base-content/30 hover:bg-base-content/60 md:w-8"
                      )}
                      onClick={() => goTo(index)}
                      aria-label={`${index + 1}번 배너 보기`}
                      aria-current={index === activeIndex ? "true" : undefined}
                    />
                  ))}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="shrink-0 whitespace-nowrap rounded-full bg-base-100/85 px-3 py-1.5 text-xs font-semibold tabular-nums text-base-content shadow-sm">
                    {String(activeIndex + 1).padStart(2, "0")} / {String(visibleBanners.length).padStart(2, "0")}
                  </span>
                  {!reducedMotion && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-circle btn-xs bg-base-100/85 text-base-content shadow-sm"
                      onClick={() => setPlaying((current) => !current)}
                      aria-label={playing ? "배너 자동 재생 멈춤" : "배너 자동 재생 시작"}
                    >
                      {playing ? <Pause className="size-3" /> : <Play className="size-3" />}
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      ) : (
        <div className="flex aspect-[1.55/1] max-h-[680px] w-full items-center bg-base-200 px-6 md:aspect-[2.05/1] md:px-[max(calc((100vw-1280px)/2),6.5rem)]">
          <div className="max-w-xl space-y-4">
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-primary">Youngcart shop</p>
            <h1 className="text-3xl font-bold tracking-tight text-base-content md:text-5xl">오늘 필요한 상품을 만나보세요</h1>
            <p className="hidden text-base text-base-content/70 md:block">카테고리별 상품과 새롭게 등록된 상품을 둘러보세요.</p>
            <a href="/shop/products" className="btn btn-neutral btn-sm md:btn-md">전체 상품 보기 <ChevronRight className="size-4" /></a>
          </div>
        </div>
      )}
    </section>
  );
}
