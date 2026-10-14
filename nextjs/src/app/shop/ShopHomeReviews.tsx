"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { GalleryThumbnail } from "@/app/boards/[bo_table]/GalleryThumbnail";
import { ProductImageFallback } from "@/components/shop/ProductImageFallback";
import { SHOP_HOME_ROW_LIMIT } from "@/components/shop/ShopProductRow";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopReview } from "@/lib/api";
import { plainTextSummary } from "@/lib/client-metadata";
import { shopProductHref } from "@/lib/product-url";
import { cn, truncate } from "@/lib/utils";
import { getShopReviews } from "@/services/shop";

const REVIEW_LIMIT = SHOP_HOME_ROW_LIMIT;
const HEADING_ID = "shop-home-reviews-title";

function stars(score: number): string {
  const full = Math.max(0, Math.min(5, Math.round(score)));
  return "★".repeat(full) + "☆".repeat(5 - full);
}

interface PagerState {
  pages: number;
  page: number;
}

/** 한 칸 넘김 폭 — 칸 너비 + 칸 사이 간격(오른쪽 여백). */
function slideStep(track: HTMLElement): number {
  const slide = track.querySelector<HTMLElement>(".swiper-slide");
  if (!slide) return track.clientWidth;
  return slide.getBoundingClientRect().width + (Number.parseFloat(getComputedStyle(slide).marginRight) || 0);
}

/** 한 쪽에 보이는 칸 수(레퍼런스 1 · 2 · 3 · 4장) — 칸 폭은 CSS(--pre-spv)가 정한다. */
function slidesPerPage(track: HTMLElement): number {
  const step = slideStep(track);
  return step > 0 ? Math.max(1, Math.round((track.clientWidth + 1) / step)) : 1;
}

/**
 * 쇼핑 홈의 후기 구역 — 레퍼런스 테마 shop-home-client 의 ReviewSection 과 같은 마크업:
 * 가운데 머리(REVIEW · 제목 · 부제), 정사각 사진 카드 줄, 카드 양옆의 둥근 화살표, 아래 쪽 점.
 * 레퍼런스는 Swiper(한 쪽 1 · 2 · 3 · 4장, 쪽 단위로 넘김)를 쓰지만 이 앱은 가로 스크롤로 같은 칸을 넘긴다.
 */
export function ShopHomeReviews() {
  const [reviews, setReviews] = useState<ShopReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [pager, setPager] = useState<PagerState>({ pages: 1, page: 0 });
  const trackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    getShopReviews({ perPage: REVIEW_LIMIT })
      .then(({ items }) => {
        if (!active) return;
        setReviews(items.filter((review) => review.is_confirm !== "0" && review.it_id));
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setReviews([]);
        setFailed(true);
        setLoading(false);
      });
    return () => { active = false; };
  }, [retryKey]);

  const syncPager = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const perPage = slidesPerPage(track);
    const count = track.querySelectorAll(".swiper-slide").length;
    const pages = Math.max(1, Math.ceil(count / perPage));
    const atEnd = track.scrollLeft >= track.scrollWidth - track.clientWidth - 2;
    const page = atEnd ? pages - 1 : Math.min(pages - 1, Math.round(track.scrollLeft / (slideStep(track) * perPage)));
    setPager((previous) => (previous.pages === pages && previous.page === page ? previous : { pages, page }));
  }, []);

  useEffect(() => {
    syncPager();
    const track = trackRef.current;
    if (!track || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(syncPager);
    observer.observe(track);
    return () => observer.disconnect();
  }, [reviews.length, syncPager]);

  const goToPage = (page: number) => {
    const track = trackRef.current;
    if (!track) return;
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    track.scrollTo({ left: page * slideStep(track) * slidesPerPage(track), behavior });
  };

  const handleTrackKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    goToPage(Math.max(0, Math.min(pager.pages - 1, pager.page + (event.key === "ArrowLeft" ? -1 : 1))));
  };

  return (
    <section className="solune-shop-product-section solune-shop-review-section" aria-labelledby={HEADING_ID}>
      <header className="solune-shop-section-head solune-shop-section-head--center">
        <span className="solune-shop-eyebrow">REVIEW</span>
        <h2 id={HEADING_ID}>고객님이 남긴 후기</h2>
        <p className="solune-shop-section-sub">상품을 받아본 분들이 직접 적은 이야기입니다.</p>
      </header>

      {loading ? (
        <div className="swiper solune-review-swiper" aria-label="상품 후기 불러오는 중">
          <div className="swiper-wrapper ondam-review-grid">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="swiper-slide">
                <div className="ondam-review-card">
                  <div className="ondam-review-thumb animate-pulse" />
                  <div className="ondam-review-body space-y-3">
                    <div className="h-3 w-20 animate-pulse rounded bg-base-200" />
                    <div className="h-4 w-full animate-pulse rounded bg-base-200" />
                    <div className="h-4 w-2/3 animate-pulse rounded bg-base-200" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : failed ? (
        <div role="alert" className="alert border border-base-300 bg-base-100">
          <span>상품 후기를 불러오지 못했습니다.</span>
          <button type="button" className="btn btn-outline btn-sm" onClick={() => setRetryKey((key) => key + 1)}>
            다시 불러오기
          </button>
        </div>
      ) : reviews.length === 0 ? (
        <p className="sct_noitem">아직 등록된 상품 후기가 없습니다.</p>
      ) : (
        <>
          <div className="swiper solune-review-swiper">
            <div
              ref={trackRef}
              className="solune-review-track"
              role="region"
              aria-label="최근 상품 후기"
              aria-roledescription="carousel"
              aria-keyshortcuts="ArrowLeft ArrowRight"
              tabIndex={0}
              onKeyDown={handleTrackKeyDown}
              onScroll={syncPager}
            >
              <div className="swiper-wrapper ondam-review-grid">
                {reviews.slice(0, REVIEW_LIMIT).map((review) => (
                  <div key={review.is_id} className="swiper-slide">
                    <ReviewCard review={review} />
                  </div>
                ))}
              </div>
            </div>
            {pager.pages > 1 ? (
              <>
                <button
                  type="button"
                  className="solune-banner-nav solune-review-prev"
                  aria-label="이전 후기"
                  disabled={pager.page <= 0}
                  onClick={() => goToPage(pager.page - 1)}
                >
                  <ChevronLeft size={16} aria-hidden />
                </button>
                <button
                  type="button"
                  className="solune-banner-nav solune-review-next"
                  aria-label="다음 후기"
                  disabled={pager.page >= pager.pages - 1}
                  onClick={() => goToPage(pager.page + 1)}
                >
                  <ChevronRight size={16} aria-hidden />
                </button>
              </>
            ) : null}
          </div>
          {pager.pages > 1 ? (
            <div className="solune-review-pagination swiper-pagination">
              {Array.from({ length: pager.pages }).map((_, index) => (
                <button
                  key={index}
                  type="button"
                  className={cn("swiper-pagination-bullet", index === pager.page && "swiper-pagination-bullet-active")}
                  aria-label={`${index + 1}쪽으로 가기`}
                  aria-current={index === pager.page ? "true" : undefined}
                  onClick={() => goToPage(index)}
                />
              ))}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/** 후기 한 장 — 레퍼런스 ondam-review-card: 사진, 별점, 제목, 본문 세 줄, 이름 · 날짜, 상품 이름. */
function ReviewCard({ review }: { review: ShopReview }) {
  const href = shopProductHref({ it_id: review.it_id, it_seo_title: review.it_seo_title });
  const reviewHref = `${href}${href.includes("?") ? "&" : "?"}is_id=${encodeURIComponent(String(review.is_id))}`;
  const score = Number(review.is_score ?? 0);
  const image = review.product_image_url?.trim() ?? "";

  return (
    <article className="ondam-review-card">
      <Link className="ondam-review-thumb" href={reviewHref} tabIndex={-1} aria-hidden>
        {image ? (
          <GalleryThumbnail src={image} alt="" sizes="(max-width: 780px) 50vw, 300px" />
        ) : (
          <ProductImageFallback compact />
        )}
      </Link>
      <div className="ondam-review-body">
        <p className="ondam-review-score">
          {stars(score)} <span>{score.toFixed(1)}</span>
        </p>
        {review.is_subject ? (
          <p className="ondam-review-title">
            <Link href={reviewHref}>{review.is_subject}</Link>
          </p>
        ) : null}
        {review.is_content ? (
          <p className="ondam-review-text">{truncate(plainTextSummary(review.is_content, review.is_subject), 200)}</p>
        ) : null}
        <div className="ondam-review-meta">
          <span>{review.mb_nick || review.is_name}</span>
          {/* 레퍼런스 후기 날짜는 연도 두 자리(26-09-22). */}
          <span>{(review.is_time || "").slice(2, 10)}</span>
        </div>
        {review.it_name ? (
          <p className="ondam-review-item">
            <Link href={href}>{review.it_name}</Link>
          </p>
        ) : null}
      </div>
    </article>
  );
}
