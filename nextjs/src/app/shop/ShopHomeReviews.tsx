"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronLeft, ChevronRight, PackageSearch, Star } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopReview } from "@/lib/api";
import { plainTextSummary } from "@/lib/client-metadata";
import { shopProductHref } from "@/lib/product-url";
import { formatDate, truncate } from "@/lib/utils";
import { getShopReviews } from "@/services/shop";

export function ShopHomeReviews() {
  const [reviews, setReviews] = useState<ShopReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const carouselRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    getShopReviews({ perPage: 8 })
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

  const scrollCarousel = (direction: -1 | 1) => {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    carouselRef.current?.scrollBy({
      left: direction * Math.max(240, carouselRef.current.clientWidth * 0.8),
      behavior,
    });
  };

  const handleCarouselKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    scrollCarousel(event.key === "ArrowLeft" ? -1 : 1);
  };

  return (
    <section className="home-product-section" aria-labelledby="shop-home-reviews-title">
      <div className="home-product-head">
        <div>
          <h2 id="shop-home-reviews-title" className="home-product-title">고객님이 남긴 후기</h2>
          <p className="home-product-subtitle">상품을 받아본 분들이 직접 적은 이야기입니다.</p>
        </div>
        <div className="flex items-center gap-1">
          {reviews.length > 0 && !failed ? (
            <>
              <button type="button" className="btn btn-ghost btn-sm btn-square" aria-label="이전 후기" onClick={() => scrollCarousel(-1)}>
                <ChevronLeft aria-hidden="true" className="size-5" />
              </button>
              <button type="button" className="btn btn-ghost btn-sm btn-square" aria-label="다음 후기" onClick={() => scrollCarousel(1)}>
                <ChevronRight aria-hidden="true" className="size-5" />
              </button>
            </>
          ) : null}
          <Link href="/shop/reviews" className="section-more ml-1">
            후기 더보기 <ChevronRight aria-hidden="true" className="size-4" />
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="carousel carousel-center w-full gap-4 pb-3" aria-label="상품 후기 불러오는 중">
          {[0, 1, 2].map((item) => (
            <div key={item} className="carousel-item w-[min(82vw,300px)] overflow-hidden rounded-box border border-base-300 bg-base-100">
              <div className="aspect-[4/3] w-full animate-pulse bg-base-200" />
              <div className="space-y-3 p-4">
                <div className="h-4 w-24 animate-pulse rounded bg-base-200" />
                <div className="h-4 w-full animate-pulse rounded bg-base-200" />
                <div className="h-4 w-2/3 animate-pulse rounded bg-base-200" />
              </div>
            </div>
          ))}
        </div>
      ) : failed ? (
        <div role="alert" className="alert border border-base-300 bg-base-100">
          <span>상품 후기를 불러오지 못했습니다.</span>
          <button type="button" className="btn btn-outline btn-sm" onClick={() => setRetryKey((key) => key + 1)}>
            다시 불러오기
          </button>
        </div>
      ) : reviews.length === 0 ? (
        <div className="rounded-box border border-base-300 bg-base-100 px-5 py-10 text-center text-sm text-base-content/60">
          아직 등록된 상품 후기가 없습니다.
        </div>
      ) : (
        <div
          ref={carouselRef}
          className="carousel carousel-center w-full gap-4 pb-3"
          role="region"
          aria-label="최근 상품 후기"
          aria-roledescription="carousel"
          aria-keyshortcuts="ArrowLeft ArrowRight"
          tabIndex={0}
          onKeyDown={handleCarouselKeyDown}
        >
          {reviews.slice(0, 8).map((review) => (
            <Link
              key={review.is_id}
              href={shopProductHref({ it_id: review.it_id, it_seo_title: review.it_seo_title })}
              className="carousel-item card w-[min(82vw,300px)] flex-none overflow-hidden border border-base-300 bg-base-100 transition-colors hover:border-primary/50 hover:bg-base-200/50"
            >
              <figure className="aspect-[4/3] w-full bg-base-200">
                {review.product_image_url ? (
                  <img src={review.product_image_url} alt="" loading="lazy" className="h-full w-full object-cover" />
                ) : (
                  <PackageSearch aria-hidden="true" className="size-10 text-base-content/35" />
                )}
              </figure>
              <div className="card-body min-h-44 gap-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-0.5" aria-label={`평점 ${review.is_score}점`}>
                    {Array.from({ length: 5 }).map((_, index) => (
                      <Star
                        key={index}
                        aria-hidden="true"
                        className={`size-3.5 ${index < review.is_score ? "fill-warning text-warning" : "text-base-300"}`}
                      />
                    ))}
                  </div>
                  <time className="text-xs text-base-content/60" dateTime={review.is_time}>
                    {formatDate(review.is_time)}
                  </time>
                </div>
                <h3 className="line-clamp-2 min-h-10 text-sm font-bold text-base-content">
                  {review.is_subject}
                </h3>
                {review.is_content ? (
                  <p className="line-clamp-3 text-sm leading-5 text-base-content/70">
                    {truncate(plainTextSummary(review.is_content, review.is_subject), 100)}
                  </p>
                ) : null}
                <div className="mt-auto border-t border-base-300 pt-3 text-xs text-base-content/65">
                  <p className="truncate font-semibold text-base-content">{review.it_name}</p>
                  <p className="mt-1">{review.mb_nick || review.is_name}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
