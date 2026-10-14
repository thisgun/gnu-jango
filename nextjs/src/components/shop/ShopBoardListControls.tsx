"use client";

import type { FormEvent } from "react";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

/*
 * 사용후기 · 상품문의 전체 목록(/shop/reviews · /shop/qas)의 검색 줄과 쪽 번호.
 * 레퍼런스(그누보드 itemuselist · itemqalist 의 solune 스킨)는 두 화면에 같은 마크업을 따로 두었다 — 여기서 한 벌로 쓴다.
 */

export interface ShopBoardSearchField {
  value: string;
  label: string;
}

interface ShopBoardSearchFormProps {
  /** select · input 의 id 앞머리(shop-review → shop-review-sfl · shop-review-stx). */
  idPrefix: string;
  className: string;
  fields: readonly ShopBoardSearchField[];
  field: string;
  text: string;
  onFieldChange: (field: string) => void;
  onTextChange: (text: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

/** 검색 줄 — 항목 고르기 · 검색어 · 검색. */
export function ShopBoardSearchForm({
  idPrefix,
  className,
  fields,
  field,
  text,
  onFieldChange,
  onTextChange,
  onSubmit,
}: ShopBoardSearchFormProps) {
  return (
    <form className={`${className} mb-3 flex flex-wrap items-center gap-2`} role="search" onSubmit={onSubmit}>
      <label htmlFor={`${idPrefix}-sfl`} className="sr-only">검색 항목</label>
      {/* 폰 폭: 항목 고르기는 한 줄을 다 쓰고, 검색어와 단추가 다음 줄에 나란히(레퍼런스와 같다). */}
      <span className="relative inline-flex max-sm:w-full">
        <select
          id={`${idPrefix}-sfl`}
          value={field}
          onChange={(event) => onFieldChange(event.target.value)}
          className="h-11 cursor-pointer appearance-none rounded-lg border bg-background py-0 pl-3.5 pr-9 text-sm max-sm:w-full"
        >
          {fields.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
      </span>
      <label htmlFor={`${idPrefix}-stx`} className="sr-only">검색어</label>
      <input
        id={`${idPrefix}-stx`}
        type="search"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        placeholder="검색어를 입력하세요"
        className="h-11 min-w-0 flex-[1_1_200px] rounded-lg border bg-background px-3.5 text-sm placeholder:text-muted-foreground"
      />
      <Button type="submit" className="h-11 rounded-lg px-[22px]">
        검색
      </Button>
    </form>
  );
}

interface ShopBoardPaginationProps {
  page: number;
  lastPage: number;
  onPageChange: (page: number) => void;
}

/** 쪽 번호 — 지금 쪽 앞뒤 둘씩, 끝 쪽은 따로. */
export function ShopBoardPagination({ page, lastPage, onPageChange }: ShopBoardPaginationProps) {
  if (lastPage <= 1) return null;

  const pages: number[] = [];
  const start = Math.max(1, page - 2);
  const end = Math.min(lastPage, page + 2);
  for (let next = start; next <= end; next++) pages.push(next);

  return (
    <nav className="mt-10 flex items-center justify-center gap-1" aria-label="쪽 번호">
      <Button
        variant="outline"
        size="icon"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="이전 페이지"
      >
        <ChevronLeft className="size-4" />
      </Button>
      {start > 1 && (
        <>
          <Button variant="outline" size="sm" onClick={() => onPageChange(1)}>
            1
          </Button>
          {start > 2 && <span className="px-1 text-muted-foreground">...</span>}
        </>
      )}
      {pages.map((next) => (
        <Button
          key={next}
          variant={next === page ? "default" : "outline"}
          size="sm"
          aria-current={next === page ? "page" : undefined}
          onClick={() => onPageChange(next)}
        >
          {next}
        </Button>
      ))}
      {end < lastPage && (
        <>
          {end < lastPage - 1 && <span className="px-1 text-muted-foreground">...</span>}
          <Button variant="outline" size="sm" onClick={() => onPageChange(lastPage)}>
            {lastPage}
          </Button>
        </>
      )}
      <Button
        variant="outline"
        size="icon"
        disabled={page >= lastPage}
        onClick={() => onPageChange(page + 1)}
        aria-label="다음 페이지"
      >
        <ChevronRight className="size-4" />
      </Button>
    </nav>
  );
}
