"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ShopReview } from "@/lib/api";
import { htmlToPlainText, sanitizeUserHtml } from "@/lib/sanitize";
import { cn } from "@/lib/utils";

/*
 * 사용후기 전체 목록의 카드 한 장과 "내용보기" 겹창 — 레퍼런스 solune 스킨(itemuselist)과 같은 짜임.
 *   상품(사진 · 이름) → 별점 → 제목 → 두 줄 발췌 → 사진 셋과 +N → 작성자 · 날짜 · 후기 바로가기 · 내용보기.
 */

/** 카드에 보이는 후기 사진 수 — 넘치면 "+N" 칸 하나로 줄인다. */
const MAX_CARD_PHOTOS = 3;
/** 별 색 — 상품 상세의 별과 같은 금색(테마가 --ondam-star 로 바꿀 수 있다). */
export const STAR_CLASS = "text-[var(--ondam-star,#c9a227)]";

const NAMED_ENTITIES: Readonly<Record<string, string>> = { nbsp: " ", amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", "#39": "'" };
const MAX_CODE_POINT = 0x10ffff;

/** 숫자 문자 참조 하나 — 유니코드 밖의 값(&#99999999; 같은)은 렌더를 깨지 않게 그대로 둔다. */
function decodeCodePoint(match: string, codePoint: number): string {
  return Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= MAX_CODE_POINT ? String.fromCodePoint(codePoint) : match;
}

/** 글자로 바꾼 본문에 남는 &nbsp; · &amp; 같은 이름 · 숫자 문자 참조를 푼다(서버 · 브라우저 어디서든). */
function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+|#39);/gi, (match, entity: string) => {
    const key = entity.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, key)) return NAMED_ENTITIES[key];
    if (key.startsWith("#x")) return decodeCodePoint(match, parseInt(key.slice(2), 16));
    if (key.startsWith("#")) return decodeCodePoint(match, Number(key.slice(1)));
    return match;
  });
}

function reviewExcerpt(html: string): string {
  return decodeEntities(htmlToPlainText(html)).replace(/\s+/g, " ").trim();
}

/**
 * 본문의 사진 주소 — http(s) 와 사이트 안 경로만, 같은 사진은 한 번. 겹창 본문과 같은 소독(sanitizeUserHtml)을
 * 거친 HTML 에서 고르므로, 소독이 버리는 사진은 카드에도 나오지 않는다.
 */
function reviewPhotos(html: string): string[] {
  const photos: string[] = [];
  for (const match of sanitizeUserHtml(html).matchAll(/<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/gi)) {
    const src = decodeEntities(match[1].trim());
    if (!/^(https?:)?\/\//i.test(src) && !src.startsWith("/")) continue;
    if (!photos.includes(src)) photos.push(src);
  }
  return photos;
}

function reviewDate(value: string): string {
  return (value || "").slice(0, 10);
}

/** "후기 바로가기" — 상품 상세에서 이 후기로(?is_id= — 그 후기가 실린 쪽을 열고 그 줄로 데려가 잠깐 표시). */
function reviewHref(productHref: string, isId: string | number): string {
  return `${productHref}${productHref.includes("?") ? "&" : "?"}is_id=${encodeURIComponent(String(isId))}`;
}

function Rating({ score, className }: { score: number; className?: string }) {
  const value = Math.max(0, Math.min(5, Math.round(Number(score || 0))));
  return (
    <p className={cn("flex items-center gap-2", className)}>
      <span className={cn("text-[15px] leading-none tracking-[1px]", STAR_CLASS)} aria-label={`5점 만점에 ${value}점`}>
        {"★".repeat(value)}
        {"☆".repeat(5 - value)}
      </span>
      <span className="text-[13px] tabular-nums text-muted-foreground" aria-hidden="true">
        {value.toFixed(1)}
      </span>
    </p>
  );
}

function ProductThumb({ src, size }: { src?: string; size: number }) {
  return (
    <span
      className="block flex-none overflow-hidden rounded-lg bg-muted"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {src ? (
        <img src={src} alt="" width={size} height={size} loading="lazy" decoding="async" className="size-full object-cover" />
      ) : null}
    </span>
  );
}

/** 후기 사진 한 칸 — 읽지 못한 사진(지워진 외부 주소 등)은 깨진 그림 대신 칸째 감춘다. */
function ReviewPhoto({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <span className="grid size-16 flex-none place-items-center overflow-hidden rounded-md border bg-muted">
      <img
        src={src}
        alt=""
        width={64}
        height={64}
        loading="lazy"
        decoding="async"
        className="size-full object-cover"
        onError={() => setFailed(true)}
      />
    </span>
  );
}

interface ShopReviewCardProps {
  item: ShopReview;
  productHref: string;
  onOpen: () => void;
}

export function ShopReviewCard({ item, productHref, onOpen }: ShopReviewCardProps) {
  const excerpt = reviewExcerpt(item.is_content);
  const photos = reviewPhotos(item.is_content);
  const shown = photos.slice(0, MAX_CARD_PHOTOS);
  const more = photos.length - shown.length;
  const writer = item.is_name || item.mb_nick;

  return (
    <li className="shop-review-card flex flex-col gap-3.5 rounded-xl border bg-card p-5">
      <Link href={productHref} className="group flex min-w-0 items-center gap-2.5">
        <ProductThumb src={item.product_image_url} size={44} />
        <span className="truncate text-[13px] text-muted-foreground group-hover:text-primary">
          {item.it_name || item.it_id}
        </span>
      </Link>

      <Rating score={item.is_score} />

      <h2 className="text-[17px] font-semibold leading-[1.45] text-pretty">{item.is_subject}</h2>
      {excerpt ? (
        <p className="line-clamp-2 text-sm leading-[1.65] text-foreground/75 [overflow-wrap:anywhere]">{excerpt}</p>
      ) : null}

      {shown.length > 0 ? (
        // 사진을 모두 읽지 못하면 칸이 비므로(empty) 줄째 감춰 빈 틈이 남지 않게 한다.
        <div className="flex items-center gap-1.5 empty:hidden" aria-hidden="true">
          {shown.map((src) => (
            <ReviewPhoto key={src} src={src} />
          ))}
          {more > 0 ? (
            <span className="grid size-16 flex-none place-items-center rounded-md border border-dashed bg-muted text-[13px] text-muted-foreground">
              +{more}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="mt-auto flex items-center justify-between gap-2 pt-1.5 text-[13px] text-muted-foreground">
        <span className="min-w-0 truncate">
          {writer}
          <span className="mx-1.5" aria-hidden="true">·</span>
          {reviewDate(item.is_time)}
        </span>
        {/* 바로가기는 화면을 옮기고 내용보기는 이 자리에서 연다 — 무게를 달리 둔다. */}
        <span className="flex flex-none items-center gap-2.5">
          <Link
            href={reviewHref(productHref, item.is_id)}
            className="whitespace-nowrap text-foreground/75 underline underline-offset-[3px] hover:text-foreground"
          >
            후기 바로가기<span className="sr-only"> — {item.is_subject}</span>
          </Link>
          <button
            type="button"
            onClick={onOpen}
            className="cursor-pointer whitespace-nowrap text-primary underline underline-offset-[3px] hover:opacity-80"
          >
            내용보기<span className="sr-only"> — {item.is_subject}</span>
          </button>
        </span>
      </div>
    </li>
  );
}

interface ShopReviewDialogProps {
  item: ShopReview | null;
  productHref: string;
  onClose: () => void;
}

/** "내용보기" — 본문 전체를 이 자리에서 겹창으로. (레퍼런스는 관리자 답변도 보이지만 이 앱의 API 는 답변을 주지 않는다.) */
export function ShopReviewDialog({ item, productHref, onClose }: ShopReviewDialogProps) {
  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onClose()}>
      {/* 겹창 설명은 제목(사용후기)과 본문이 대신한다 — 따로 두지 않는다고 Radix 에 알린다. */}
      <DialogContent
        aria-describedby={undefined}
        className="flex max-h-[calc(100vh-48px)] max-w-[640px] flex-col gap-0 overflow-hidden p-0"
      >
        <DialogHeader className="flex-none border-b px-5 py-[18px]">
          <DialogTitle className="text-[13px] font-medium text-muted-foreground">사용후기</DialogTitle>
        </DialogHeader>
        {item ? (
          <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-6 pb-7 pt-[22px]">
            <Link
              href={productHref}
              onClick={onClose}
              className="flex min-w-0 items-center gap-3 rounded-[10px] border bg-muted/50 p-3"
            >
              <ProductThumb src={item.product_image_url} size={48} />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13px] font-medium">{item.it_name || item.it_id}</span>
                <span className="inline-flex items-center gap-1 text-xs text-primary">
                  상품 보기 <ArrowRight className="size-3" aria-hidden="true" />
                </span>
              </span>
            </Link>

            <div className="flex flex-col gap-1.5">
              <Rating score={item.is_score} />
              <h3 className="text-lg font-semibold leading-snug">{item.is_subject}</h3>
              <p className="text-[13px] text-muted-foreground">
                {item.is_name || item.mb_nick}
                <span className="mx-1.5" aria-hidden="true">·</span>
                {reviewDate(item.is_time)}
              </p>
            </div>

            <div
              className="prose prose-sm max-w-none border-t pt-4 dark:prose-invert [&_img]:h-auto [&_img]:max-w-full"
              dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(item.is_content) }}
            />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
