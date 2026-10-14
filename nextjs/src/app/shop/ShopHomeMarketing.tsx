"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ShopBanner, ShopPopup } from "@/lib/api";
import { sanitizeCommerceHtml } from "@/lib/sanitize";
import { cn } from "@/lib/utils";
import { getShopBannersResult } from "@/services/shop";
import { ArrowRight, ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";

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
  const allBanners = (runtimeBanners ?? banners).filter(
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
    getShopBannersResult({ position: "메인", device: "all" }, { cache: "no-store" })
      .then((result) => {
        if (active && result.ok) setRuntimeBanners(result.data);
      });

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

function popupStorageKey(id: number): string {
  return `g5_shop_popup_hidden_until_${id}`;
}

function popupIsHidden(id: number): boolean {
  if (typeof window === "undefined") return false;

  try {
    const raw = window.localStorage.getItem(popupStorageKey(id));
    if (!raw) return false;

    const hiddenUntil = Number(raw);
    if (!Number.isFinite(hiddenUntil) || hiddenUntil <= Date.now()) {
      window.localStorage.removeItem(popupStorageKey(id));
      return false;
    }

    return true;
  } catch {
    return false;
  }
}

function hidePopupForHours(id: number, hours: number) {
  if (typeof window === "undefined") return;

  const safeHours = Math.max(1, hours || 24);
  try {
    window.localStorage.setItem(
      popupStorageKey(id),
      String(Date.now() + safeHours * 60 * 60 * 1000)
    );
  } catch {
    return;
  }
}

export function ShopHomePopups({ popups }: { popups: ShopPopup[] }) {
  const [closedIds, setClosedIds] = useState<number[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(true);
  }, []);

  const visiblePopups = useMemo(() => {
    if (!ready) return [];

    return popups
      .filter((popup) => popup.nw_id > 0)
      .filter((popup) => !closedIds.includes(popup.nw_id))
      .filter((popup) => !popupIsHidden(popup.nw_id))
      .slice(0, 3);
  }, [closedIds, popups, ready]);

  if (visiblePopups.length === 0) return null;

  const closePopup = (id: number) => {
    setClosedIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
  };

  const closeForConfiguredTime = (popup: ShopPopup) => {
    hidePopupForHours(popup.nw_id, popup.nw_disable_hours || 24);
    closePopup(popup.nw_id);
  };

  return (
    <div className="fixed bottom-4 left-4 z-40 flex max-w-[calc(100vw-2rem)] flex-col gap-3 sm:left-auto sm:right-4">
      {visiblePopups.map((popup) => {
        const maxWidth = Math.min(Math.max(popup.nw_width || 360, 280), 520);
        const maxHeight = Math.min(Math.max(popup.nw_height || 260, 180), 620);

        return (
          <section
            key={popup.nw_id}
            className="overflow-hidden rounded-[6px] border border-border bg-base-100 shadow-[0_16px_40px_rgba(15,23,42,0.16)]"
            style={{ width: maxWidth }}
            aria-label={popup.nw_subject || "쇼핑몰 팝업"}
          >
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <h2 className="line-clamp-1 text-sm font-bold text-base-content">
                {popup.nw_subject || "쇼핑몰 안내"}
              </h2>
              <button
                type="button"
                onClick={() => closePopup(popup.nw_id)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                aria-label="팝업 닫기"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div
              className="prose prose-sm max-w-none overflow-auto px-4 py-3 text-sm"
              style={{ maxHeight }}
              dangerouslySetInnerHTML={{
                __html:
                  popup.nw_content_html === 1
                    ? sanitizeCommerceHtml(popup.nw_content)
                    : sanitizeCommerceHtml(popup.nw_content_text),
              }}
            />
            <div className="flex items-center justify-end gap-2 border-t border-border bg-base-200 px-4 py-3">
              <button
                type="button"
                onClick={() => closeForConfiguredTime(popup)}
                className="text-xs font-medium text-muted-foreground hover:text-base-content"
              >
                {popup.nw_disable_hours || 24}시간 보지 않기
              </button>
              <button
                type="button"
                onClick={() => closePopup(popup.nw_id)}
                className="rounded-[4px] bg-primary px-3 py-1.5 text-xs font-bold text-primary-foreground"
              >
                닫기
              </button>
            </div>
          </section>
        );
      })}
    </div>
  );
}
