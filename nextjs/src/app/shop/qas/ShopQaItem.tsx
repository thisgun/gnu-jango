"use client";

import { useId, useState } from "react";
import { ChevronDown, Lock } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopQA } from "@/lib/api";
import { sanitizeUserHtml } from "@/lib/sanitize";
import { cn } from "@/lib/utils";

/*
 * 상품문의 전체 목록의 한 줄 — 레퍼런스 solune 스킨(itemqalist)과 같은 접는 줄.
 *   상품 사진 · 상품명 · 제목 · 비밀글 자물쇠 · 답변대기/답변완료 · 작성자 · 날짜, 오른쪽 펴기 단추
 *   → 펴면 Q 문의 내용 · A 답변 · 문의 바로가기 · 상품 보기.
 *   비밀글은 글쓴이 · 관리자만 내용을 보고(API 의 can_view), 그 밖에는 안내 한 줄만 두고 답변 칸은 내지 않는다.
 */

const QA_BODY_CLASS =
  "prose prose-sm min-w-0 flex-1 max-w-none dark:prose-invert [&_img]:h-auto [&_img]:max-w-full [&_p]:my-0";

function qaDate(value: string): string {
  return (value || "").slice(0, 10);
}

/** "문의 바로가기" — 상품 상세에서 이 문의로(?iq_id= — 그 문의가 실린 쪽을 열고 그 줄로 데려가 잠깐 표시). */
function qaHref(productHref: string, iqId: string | number): string {
  return `${productHref}${productHref.includes("?") ? "&" : "?"}iq_id=${encodeURIComponent(String(iqId))}`;
}

function ProductThumb({ src }: { src?: string }) {
  return (
    <span className="block size-12 flex-none overflow-hidden rounded-lg bg-muted" aria-hidden="true">
      {src ? (
        <img src={src} alt="" width={48} height={48} loading="lazy" decoding="async" className="size-full object-cover" />
      ) : null}
    </span>
  );
}

function QaMark({ kind }: { kind: "Q" | "A" }) {
  return (
    <span
      className={cn(
        "grid size-6 flex-none place-items-center rounded-full text-xs font-bold",
        kind === "A" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground/70"
      )}
      aria-hidden="true"
    >
      {kind}
    </span>
  );
}

interface ShopQaItemProps {
  item: ShopQA;
  productHref: string;
}

export function ShopQaItem({ item, productHref }: ShopQaItemProps) {
  const [open, setOpen] = useState(false);
  const panelId = `${useId()}-qa`;
  const secret = Number(item.iq_secret || 0) === 1;
  const canView = item.can_view !== false;
  const answered = Boolean(item.is_answered ?? item.iq_answer);

  return (
    <li className={cn("shop-qa-item overflow-hidden rounded-xl border bg-card", open && "is-open")}>
      <button
        type="button"
        className="flex w-full items-center gap-3.5 p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary md:px-5"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <ProductThumb src={item.product_image_url} />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-xs text-muted-foreground">{item.it_name || item.it_id}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-medium leading-snug text-pretty">
              {item.iq_subject}
              {secret ? (
                <>
                  <Lock className="ml-1 inline size-3 -translate-y-px text-muted-foreground" aria-hidden="true" />
                  <span className="sr-only"> 비밀글</span>
                </>
              ) : null}
            </span>
            <span
              className={cn(
                "inline-flex h-5 items-center rounded-full px-2 text-[11px] font-medium",
                answered ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
              )}
            >
              {answered ? "답변완료" : "답변대기"}
            </span>
          </span>
          <span className="mt-1.5 text-xs text-muted-foreground">
            <span className="sr-only">작성자 </span>
            {item.iq_name || item.mb_nick}
            <span className="mx-1.5" aria-hidden="true">·</span>
            <span className="sr-only">작성일 </span>
            {qaDate(item.iq_time)}
          </span>
        </span>
        <span
          className="grid size-7 flex-none place-items-center rounded-full border text-muted-foreground transition-transform"
          style={{ transform: open ? "rotate(180deg)" : undefined }}
          aria-hidden="true"
        >
          <ChevronDown className="size-4" />
        </span>
      </button>

      <div id={panelId} hidden={!open} className="flex flex-col gap-4 border-t bg-muted/30 px-4 pb-5 pt-4 md:px-5">
        <div className="flex gap-3">
          <QaMark kind="Q" />
          <span className="sr-only">문의내용</span>
          {canView ? (
            <div className={QA_BODY_CLASS} dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(item.iq_question) }} />
          ) : (
            <p className="text-sm text-muted-foreground">비밀글로 보호된 문의입니다.</p>
          )}
        </div>
        {canView ? (
          <div className="flex gap-3">
            <QaMark kind="A" />
            <span className="sr-only">답변</span>
            {answered ? (
              <div className={QA_BODY_CLASS} dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(item.iq_answer || "") }} />
            ) : (
              <p className="text-sm text-muted-foreground">답변이 등록되지 않았습니다.</p>
            )}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pl-9 text-[13px]">
          <Link href={qaHref(productHref, item.iq_id)} className="text-foreground/75 underline underline-offset-[3px] hover:text-primary">
            문의 바로가기<span className="sr-only"> — {item.iq_subject}</span>
          </Link>
          <Link href={productHref} className="text-foreground/75 underline underline-offset-[3px] hover:text-primary">
            상품 보기
          </Link>
        </div>
      </div>
    </li>
  );
}
