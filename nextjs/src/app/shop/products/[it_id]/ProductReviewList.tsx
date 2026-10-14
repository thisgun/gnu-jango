"use client";

import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { ChevronDown, Star } from "lucide-react";
import type { ShopReview, ShopReviewSummary } from "@/lib/api";
import { sanitizeUserHtml } from "@/lib/sanitize";
import { reviewImageUrls } from "@/components/shop/productDetailHelpers";
import { cn, formatDate } from "@/lib/utils";

const Lightbox = dynamic(
  () => import("@/components/ui/lightbox").then((mod) => ({ default: mod.Lightbox })),
  { ssr: false }
);

type ReviewScore = NonNullable<ShopReviewSummary["scores"]>[number];

/** 사진 줄에 놓는 칸 수 — 레퍼런스 solune-review-photo-grid(사진 후기마다 첫 사진 하나씩 8칸, 남는 후기는 마지막 칸에 +N). */
const PHOTO_STRIP_SIZE = 8;

function Stars({ score, className }: { score: number; className?: string }) {
  return (
    <span className={cn("flex", className)} aria-label={`5점 만점에 ${score}점`} role="img">
      {Array.from({ length: 5 }).map((_, index) => (
        <Star
          key={index}
          aria-hidden="true"
          className={cn("h-3.5 w-3.5", index < score ? "fill-current" : "fill-transparent opacity-40")}
        />
      ))}
    </span>
  );
}

/** 평점 요약 — 평균 · 별 · 건수(포토 몇) 왼쪽, 점수대 막대 가운데, 쓰기 단추 오른쪽(레퍼런스 solune-review-summary). */
export function ReviewSummaryBox({
  average,
  total,
  photoCount,
  scores,
  action,
}: {
  average: number;
  total: number;
  photoCount: number;
  scores: ReviewScore[];
  action: ReactNode;
}) {
  return (
    <div className="product-review-summary flex flex-wrap items-center gap-x-8 gap-y-5 rounded-lg border px-6 py-6 sm:px-8">
      <div className="product-review-score min-w-[120px] flex-none text-center">
        <p className="product-review-avg text-4xl font-bold tracking-tight">{average.toFixed(1)}</p>
        <Stars score={Math.round(average)} className="product-review-stars mt-1.5 justify-center text-amber-500" />
        <p className="product-review-count mt-1.5 text-xs text-muted-foreground">
          리뷰 {total.toLocaleString()}건 · 포토 {photoCount.toLocaleString()}
        </p>
      </div>
      <ul className="product-review-bars min-w-[200px] flex-1 space-y-1.5">
        {scores.map((item) => (
          <li key={item.score} className="flex items-center gap-2.5 text-xs text-muted-foreground">
            <span className="w-7 flex-none">{item.score}점</span>
            <span className="product-review-bar relative h-1.5 flex-1 overflow-hidden bg-muted">
              <span
                className="absolute inset-y-0 left-0 bg-amber-500"
                style={{ width: `${Math.min(100, Math.max(0, item.percentage))}%` }}
              />
            </span>
            <span className="w-8 flex-none text-right tabular-nums">{item.count.toLocaleString()}</span>
          </li>
        ))}
      </ul>
      <div className="flex-none max-sm:w-full">{action}</div>
    </div>
  );
}

/** 크게 볼 사진 묶음(한 후기의 사진들)과 처음 볼 차례 */
type PhotoView = { photos: string[]; index: number };

/**
 * 후기 목록 — 포토 후기 줄(이 쪽 사진 후기의 첫 사진 8칸), "최신순 · N개", 후기마다 접힌 한 줄(레퍼런스 앱 ProductReviewList).
 * 사진을 누르면 그 후기의 사진을 크게 본다 — 레퍼런스의 포토 후기 창 대신 이 앱의 Lightbox 를 쓴다.
 * ?is_id= 로 가리킨 후기(focusReviewId)는 펼친 채로 그린다.
 */
export function ReviewList({
  reviews,
  total,
  photoCount,
  focusReviewId,
  pager,
}: {
  reviews: ShopReview[];
  total: number;
  photoCount: number;
  focusReviewId: number;
  pager: ReactNode;
}) {
  const [photoView, setPhotoView] = useState<PhotoView | null>(null);
  // 못 읽은 사진 — 본문이 지워진 외부 주소를 가리키면 깨진 칸이 줄에 남는다. 한 번 실패하면 줄 · 썸네일에서 뺀다.
  const [brokenPhotos, setBrokenPhotos] = useState<ReadonlySet<string>>(() => new Set());
  const markBroken = (url: string) =>
    setBrokenPhotos((current) => (current.has(url) ? current : new Set([...current, url])));
  const photosByReview = useMemo(
    () =>
      new Map(
        reviews.map((review) => [
          review.is_id,
          reviewImageUrls(review.is_content).filter((url) => !brokenPhotos.has(url)),
        ])
      ),
    [reviews, brokenPhotos]
  );
  // 사진 줄 — 사진 후기마다 첫 사진 하나(누르면 그 후기의 사진을 연다). 서버의 photo_count 도 사진 후기 수라 단위가 같다.
  const stripPhotos = useMemo(
    () =>
      reviews.flatMap((review) => {
        const photos = photosByReview.get(review.is_id) ?? [];
        return photos[0] ? [{ url: photos[0], photos }] : [];
      }),
    [reviews, photosByReview]
  );
  const shownPhotos = stripPhotos.slice(0, PHOTO_STRIP_SIZE);
  // 사진 후기 수 — 서버 요약(photo_count, 다른 쪽까지 센 수)과 이 쪽에서 센 수 중 큰 쪽. 요약이 0 을 주어도
  // 사진이 보이는 줄 머리에 "0" 이 서지 않는다. 마지막 칸의 +N 은 줄에 못 놓은 사진 후기.
  const photoReviewCount = Math.max(photoCount, stripPhotos.length);
  const morePhotos = photoReviewCount - shownPhotos.length;

  return (
    <>
      {shownPhotos.length > 0 && (
        <section className="product-review-photos mt-10">
          <h4 className="product-review-photos-head border-b border-foreground pb-3.5 text-[15px] font-bold">
            포토 후기 <span className="font-semibold tabular-nums text-muted-foreground">{photoReviewCount.toLocaleString()}</span>
          </h4>
          <ul className="product-review-photo-grid mt-4 grid grid-cols-4 gap-2 sm:grid-cols-8">
            {shownPhotos.map((entry, index) => {
              const isLast = index === shownPhotos.length - 1 && morePhotos > 0;
              return (
                <li key={`${index}-${entry.url}`}>
                  <button
                    type="button"
                    className="product-review-photo relative block aspect-square w-full cursor-zoom-in overflow-hidden bg-muted"
                    onClick={() => setPhotoView({ photos: entry.photos, index: 0 })}
                    aria-label={`포토 후기 사진 ${index + 1} 크게 보기`}
                  >
                    {/* 후기 본문의 사진은 어느 주소든 올 수 있어 next/image 대신 그대로 그린다. */}
                    <img
                      src={entry.url}
                      alt=""
                      loading="lazy"
                      onError={() => markBroken(entry.url)}
                      className="h-full w-full object-cover transition-opacity hover:opacity-85"
                    />
                    {isLast && (
                      <span className="absolute inset-0 grid place-items-center bg-black/45 text-[13px] font-bold text-white">
                        +{morePhotos.toLocaleString()}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <p className="product-review-sort mt-8 border-b border-foreground pb-3.5 text-xs tabular-nums text-muted-foreground">
        최신순 · {total.toLocaleString()}개
      </p>

      {reviews.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">아직 리뷰가 없습니다.</p>
      ) : (
        <ol className="product-review-list">
          {reviews.map((review) => (
            <ReviewListItem
              key={review.is_id}
              review={review}
              initiallyOpen={focusReviewId === Number(review.is_id)}
              photos={photosByReview.get(review.is_id) ?? []}
              onOpenPhoto={(photos, index) => setPhotoView({ photos, index })}
              onPhotoError={markBroken}
            />
          ))}
        </ol>
      )}
      {pager}

      {photoView && (
        <Lightbox
          images={photoView.photos}
          currentIndex={photoView.index}
          onClose={() => setPhotoView(null)}
          onNavigate={(index) => setPhotoView((current) => (current ? { ...current, index } : current))}
        />
      )}
    </>
  );
}

/** 후기 한 줄 — 별 · 이름 · 날짜, 제목, [내용 보기 ▾](펼치면 "접기"), 오른쪽에 첫 사진(+N). */
function ReviewListItem({
  review,
  initiallyOpen,
  photos,
  onOpenPhoto,
  onPhotoError,
}: {
  review: ShopReview;
  initiallyOpen: boolean;
  photos: string[];
  onOpenPhoto: (photos: string[], index: number) => void;
  onPhotoError: (url: string) => void;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const contentId = useId();

  useEffect(() => {
    if (initiallyOpen) setOpen(true);
  }, [initiallyOpen]);

  return (
    /* 후기 하나를 주소로 가리킬 수 있게 이름표를 단다(?is_id= — 레퍼런스 itemuse.skin.php 의 #is_N).
       찾아오면 useProductDetailFocusScroll 이 data-focused 로 잠깐 표시하고 초점을 준다(탭 차례에는 넣지 않는다). */
    <li
      id={`is_${review.is_id}`}
      data-review-id={review.is_id}
      tabIndex={-1}
      className="product-review-item flex gap-5 border-b py-6 outline-none transition-[background-color,box-shadow] duration-1000 data-[focused=true]:bg-primary/5 data-[focused=true]:ring-2 data-[focused=true]:ring-primary"
    >
      <div className="min-w-0 flex-1">
        <div className="product-review-meta mb-2 flex flex-wrap items-center gap-3">
          <Stars score={review.is_score} className="product-review-item-stars text-amber-500" />
          <span className="product-review-name text-[13px] font-semibold">{review.mb_nick}</span>
          <span className="product-review-date text-xs tabular-nums text-muted-foreground">{formatDate(review.is_time)}</span>
        </div>
        <h4 className="product-review-subject text-[14.5px] font-medium">{review.is_subject}</h4>
        <div id={contentId} hidden={!open} className="product-review-content mt-2">
          <div
            className="prose prose-sm max-w-none text-muted-foreground [&_img]:mr-1.5 [&_img]:mt-2.5 [&_img]:inline-block [&_img]:max-h-[110px] [&_img]:max-w-[110px] [&_img]:rounded-md [&_img]:object-cover"
            dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(review.is_content) }}
          />
        </div>
        <button
          type="button"
          className="product-review-toggle mt-3 inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs hover:border-foreground"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "접기" : "내용 보기"}
          <ChevronDown
            aria-hidden="true"
            className={cn("h-3.5 w-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")}
          />
        </button>
      </div>
      {photos.length > 0 && (
        <button
          type="button"
          className="product-review-thumb relative h-[84px] w-[84px] flex-none cursor-zoom-in overflow-hidden rounded-xl bg-muted sm:h-[110px] sm:w-[110px]"
          onClick={() => onOpenPhoto(photos, 0)}
          aria-label={`${review.mb_nick} 님의 사진 후기 크게 보기`}
        >
          <img
            src={photos[0]}
            alt=""
            loading="lazy"
            onError={() => onPhotoError(photos[0])}
            className="h-full w-full object-cover"
          />
          {photos.length > 1 && (
            <span className="absolute bottom-2 right-2 rounded-full bg-black/60 px-1.5 py-0.5 text-[11px] font-semibold text-white">
              +{photos.length - 1}
            </span>
          )}
        </button>
      )}
    </li>
  );
}

/**
 * 후기 · 문의 쪽 번호 — 레퍼런스 ReviewPager 모양(‹ 지금 쪽 둘레 다섯 쪽과 처음 · 끝 ›).
 * 단추 이름은 이 앱 그대로 둔다("N페이지", "… 이전 페이지") — 화면 읽기와 시험이 그 이름으로 찾는다.
 */
export function ReviewPager({
  page,
  lastPage,
  onPageChange,
  label = "상품 후기",
}: {
  page: number;
  lastPage: number;
  onPageChange: (page: number) => void;
  label?: string;
}) {
  if (lastPage <= 1) return null;
  const start = Math.max(1, page - 2);
  const end = Math.min(lastPage, page + 2);
  const pages: number[] = [];
  for (let next = start; next <= end; next++) pages.push(next);
  const buttonClass =
    "inline-flex h-8 min-w-8 items-center justify-center rounded-md border px-2 text-sm tabular-nums transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40";
  const pageButton = (target: number) => (
    <button
      key={target}
      type="button"
      className={cn(
        buttonClass,
        target === page && "border-primary bg-primary text-primary-foreground hover:bg-primary"
      )}
      aria-label={`${target}페이지`}
      aria-current={target === page ? "page" : undefined}
      onClick={() => onPageChange(target)}
    >
      {target}
    </button>
  );

  return (
    <nav
      className="product-review-pager flex flex-wrap items-center justify-center gap-1 pt-4"
      aria-label={`${label} 페이지`}
    >
      <button
        type="button"
        className={buttonClass}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label={`${label} 이전 페이지`}
      >
        ‹
      </button>
      {start > 1 ? (
        <>
          {pageButton(1)}
          {start > 2 ? <span className="px-1 text-muted-foreground" aria-hidden="true">…</span> : null}
        </>
      ) : null}
      {pages.map(pageButton)}
      {end < lastPage ? (
        <>
          {end < lastPage - 1 ? <span className="px-1 text-muted-foreground" aria-hidden="true">…</span> : null}
          {pageButton(lastPage)}
        </>
      ) : null}
      <button
        type="button"
        className={buttonClass}
        disabled={page >= lastPage}
        onClick={() => onPageChange(page + 1)}
        aria-label={`${label} 다음 페이지`}
      >
        ›
      </button>
    </nav>
  );
}
