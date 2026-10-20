"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { shopRowItemClass, shopRowLimit, shopRowStyle, type ShopHomeSectionDisplay } from "@/lib/shop-display";
import { cn } from "@/lib/utils";
import { SoluneProductCard } from "./SoluneProductCard";


interface ShopProductRowProps {
  eyebrow: string;
  title: string;
  subtitle?: string;
  products: ShopProduct[];
  /** 제목과 "전체 보기"가 가리키는 곳 */
  viewAllHref: string;
  productRewriteMode?: BbsRewriteMode;
  /** 마지막 한 장을 반쯤 걸쳐 둔다(레퍼런스 peek — 2.5 · 3.5 · 4.5 · 5.5칸). 아니면 2 · 3 · 4 · 5칸. */
  peek?: boolean;
  /**
   * 관리자 진열 설정(1줄당 상품 수 · 표시 수, PC/모바일). 주면 한 화면 칸 수를 그 값으로 두고, 폰에서는
   * 모바일 수 · 넓은 화면에서는 PC 수를 넘는 상품을 CSS 로 감춘다. 없으면 기본 칸 수(2.5 ~ 5.5)로 모두 보인다.
   */
  display?: ShopHomeSectionDisplay;
  className?: string;
}

interface TrackState {
  canPrev: boolean;
  canNext: boolean;
  /** 한 화면에 다 들어가 넘길 것이 없다 — 화살표와 진행 막대를 감춘다(Swiper 의 lock 과 같다). */
  locked: boolean;
  /** 진행 막대 채움(0~1) — Swiper progressbar 처럼 (현재 칸 + 1) / 넘김 칸 수. */
  progress: number;
}

const INITIAL_STATE: TrackState = { canPrev: false, canNext: false, locked: true, progress: 0 };

const SKELETON_CARD_COUNT = 6;

/** 자리 잡기 카드 — 레퍼런스 shop-home-skeletons 의 카드와 같은 sct_li 틀이라 진짜 카드와 같은 높이로 선다. */
function ProductCardSkeleton({ index }: { index: number }) {
  return (
    <article className="sct_li solune-skel-card" aria-hidden="true">
      <div className="sct_img skeleton" />
      <p className="ondam-card-brand">
        <span className={`skeleton solune-skel-line ${index % 2 === 0 ? "w-16" : "w-12"}`} />
      </p>
      <p className="sct_txt">
        <span className={`skeleton solune-skel-line ${index % 3 === 0 ? "w-[88%]" : "w-[78%]"}`} />
        <br />
        <span className={`skeleton solune-skel-line ${index % 2 === 0 ? "w-1/2" : "w-2/5"}`} />
        {/* 폰 폭(두 장 반)의 좁은 칸에서는 상품명이 대개 세 줄이다 — 그때만 셋째 줄을 둔다. */}
        <br className="solune-skel-narrow" />
        <span className="skeleton solune-skel-line solune-skel-narrow w-1/3" />
      </p>
      <div className="ondam-card-prices">
        <span className="ondam-card-now">
          <span className="skeleton solune-skel-line w-20" />
        </span>
      </div>
      <div className="ondam-card-meta">
        <span>
          <span className="skeleton solune-skel-line w-9" />
        </span>
        <span>
          <span className="skeleton solune-skel-line w-12" />
        </span>
        <span className="skeleton solune-skel-chip ml-auto" />
      </div>
    </article>
  );
}

/**
 * 진열 줄을 받는 동안의 자리 — 진짜 줄(ShopProductRow)과 같은 머리 · 트랙 마크업이라, 상품이 오면 그 자리에
 * 그대로 바뀌어 아래 구역이 밀리지 않는다. 화살표는 아직 넘길 것이 없으니 옅게(disabled) 둔다.
 */
export function ShopProductRowSkeleton({
  eyebrow,
  title,
  subtitle,
  peek = true,
  className,
}: Pick<ShopProductRowProps, "eyebrow" | "title" | "subtitle" | "peek" | "className">) {
  return (
    <section className={cn("solune-shop-product-section solune-shop-row", className)} aria-label={`${title} 불러오는 중`} aria-busy="true">
      <header className="solune-shop-section-head solune-shop-section-head--row">
        <span className="solune-shop-eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <div className="solune-shop-swiper-nav">
          <button type="button" className="solune-shop-swiper-prev swiper-button-disabled" aria-label={`${title} 이전`} disabled>
            <ChevronLeft size={18} aria-hidden />
          </button>
          <button type="button" className="solune-shop-swiper-next swiper-button-disabled" aria-label={`${title} 다음`} disabled>
            <ChevronRight size={18} aria-hidden />
          </button>
        </div>
        {subtitle ? <p className="solune-shop-section-sub">{subtitle}</p> : null}
      </header>
      <div className="swiper solune-shop-swiper solune-shop-scroll-track" data-solune-swiper-peek={peek ? "1" : undefined}>
        <div className="swiper-wrapper sct">
          {Array.from({ length: SKELETON_CARD_COUNT }).map((_, index) => (
            <div key={index} className="swiper-slide">
              <ProductCardSkeleton index={index} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** 한 칸 넘김 폭 — 칸 너비 + 칸 사이 간격(오른쪽 여백). */
function slideStep(track: HTMLElement): number {
  const slide = track.querySelector<HTMLElement>(".swiper-slide");
  if (!slide) return track.clientWidth;
  return slide.getBoundingClientRect().width + (Number.parseFloat(getComputedStyle(slide).marginRight) || 0);
}

/**
 * 쇼핑 홈의 진열 한 줄 — 레퍼런스 테마 shop-row.tsx(solune_shop_product_section)와 같은 마크업:
 * 왼쪽에 눈썹 · 제목 · 전체 보기, 오른쪽 끝에 네모 화살표 둘, 머리 아래 선 위에 진행 막대, 그 아래 상품 카드 줄.
 * 레퍼런스는 Swiper 로 넘기지만 이 앱은 Swiper 를 싣지 않는다. 칸 폭 · 간격은 Swiper 가 서기 전 규칙
 * (solune-shop.carousel.css 의 --pre-spv · --pre-gap)이 레퍼런스와 같은 값으로 세우고, 넘김은 가로 스크롤
 * (스냅)로 한다. 화살표는 한 칸씩 넘기고, 넘길 것이 없으면 Swiper 처럼 화살표와 막대를 잠근다.
 */
export function ShopProductRow({
  eyebrow,
  title,
  subtitle,
  products,
  viewAllHref,
  productRewriteMode,
  peek = true,
  display,
  className,
}: ShopProductRowProps) {
  const headingId = useId();
  const trackRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<TrackState>(INITIAL_STATE);

  const sync = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const step = slideStep(track);
    const maxScroll = track.scrollWidth - track.clientWidth;
    const locked = maxScroll <= 2 || step <= 0;
    // Swiper 의 넘김 칸 수와 같게 올림한다 — 6장 · 5.5칸이면 반 칸만 남아도 두 칸(처음 · 끝)이다.
    const snapCount = locked ? 1 : Math.ceil(maxScroll / step - 0.05) + 1;
    const atEnd = track.scrollLeft >= maxScroll - 2;
    const index = locked ? 0 : atEnd ? snapCount - 1 : Math.min(snapCount - 1, Math.round(track.scrollLeft / step));
    const next: TrackState = {
      canPrev: !locked && track.scrollLeft > 2,
      canNext: !locked && track.scrollLeft < maxScroll - 2,
      locked,
      progress: (index + 1) / snapCount,
    };
    setState((previous) =>
      previous.canPrev === next.canPrev &&
      previous.canNext === next.canNext &&
      previous.locked === next.locked &&
      previous.progress === next.progress
        ? previous
        : next
    );
  }, []);

  useEffect(() => {
    sync();
    const track = trackRef.current;
    if (!track || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(sync);
    observer.observe(track);
    return () => observer.disconnect();
  }, [products.length, sync]);

  const move = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollBy({ left: direction * slideStep(track), behavior: "smooth" });
  };

  if (products.length === 0) return null;
  const shown = display ? products.slice(0, shopRowLimit(display)) : products;

  return (
    <section className={cn("solune-shop-product-section solune-shop-row", className)} aria-labelledby={headingId}>
      <header className="solune-shop-section-head solune-shop-section-head--row">
        <span className="solune-shop-eyebrow">{eyebrow}</span>
        <h2 id={headingId}>
          <Link href={viewAllHref}>{title}</Link>
        </h2>
        <Link className="solune-shop-section-more" href={viewAllHref}>
          전체 보기
          <ArrowRight size={13} strokeWidth={2.6} aria-hidden />
        </Link>
        <div className="solune-shop-swiper-nav">
          <button
            type="button"
            className={cn("solune-shop-swiper-prev", !state.canPrev && "swiper-button-disabled", state.locked && "swiper-button-lock")}
            aria-label={`${title} 이전`}
            disabled={!state.canPrev}
            onClick={() => move(-1)}
          >
            <ChevronLeft size={18} aria-hidden />
          </button>
          <button
            type="button"
            className={cn("solune-shop-swiper-next", !state.canNext && "swiper-button-disabled", state.locked && "swiper-button-lock")}
            aria-label={`${title} 다음`}
            disabled={!state.canNext}
            onClick={() => move(1)}
          >
            <ChevronRight size={18} aria-hidden />
          </button>
        </div>
        {subtitle ? <p className="solune-shop-section-sub">{subtitle}</p> : null}
        <div className={cn("solune-shop-swiper-progress", state.locked && "swiper-pagination-lock")} aria-hidden>
          <span
            className="swiper-pagination-progressbar-fill"
            style={{ transform: `scaleX(${state.progress})`, transition: "transform 0.32s ease" }}
          />
        </div>
      </header>
      <div
        ref={trackRef}
        className="swiper solune-shop-swiper solune-shop-scroll-track"
        data-solune-swiper-peek={peek ? "1" : undefined}
        data-solune-row-display={display ? "1" : undefined}
        style={display ? shopRowStyle(display, peek) : undefined}
        onScroll={sync}
      >
        <div className="swiper-wrapper sct">
          {shown.map((product, index) => (
            <div key={product.it_id} className={cn("swiper-slide", display && shopRowItemClass(index, display))}>
              <SoluneProductCard product={product} priority={index < 2} productRewriteMode={productRewriteMode} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
