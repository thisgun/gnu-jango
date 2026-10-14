"use client";

import { useState } from "react";
import { Paperclip, Search } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { QaItem } from "@/lib/types";
import { cn, formatDate, truncate } from "@/lib/utils";
import { htmlToText } from "../htmlText";

/*
 * 1:1 문의 목록의 조각(레퍼런스 mypage/qas/QaListParts) — 그누보드 bbs/qalist.php · 기본 qa 스킨과 같은 것을 보여 준다:
 * 검색(제목 · 내용 · 글쓴이), 번호 · 상태 · 분류 · 제목 · 첨부 · 미리보기 · 등록일.
 * 레퍼런스의 분류 알약 줄은 뺐다 — Django 1:1 문의 API 가 분류(sca)로 거르지 않아 눌러도 목록이 그대로다.
 * 최고관리자 전용 칸(회원아이디 검색 · 선택삭제 · 글쓴이)도 이 앱의 회원 화면에는 없다.
 */

export type QaSearchField = "qa_subject" | "qa_content" | "qa_name";

const SEARCH_FIELDS: Array<{ value: QaSearchField; label: string }> = [
  { value: "qa_subject", label: "제목" },
  { value: "qa_content", label: "내용" },
  { value: "qa_name", label: "글쓴이" },
];

export function qaSearchField(value: string | null): QaSearchField {
  return SEARCH_FIELDS.some((field) => field.value === value) ? (value as QaSearchField) : "qa_subject";
}

export function QaSearchForm({
  field,
  keyword,
  onSearch,
  onReset,
}: {
  field: QaSearchField;
  keyword?: string;
  onSearch: (field: QaSearchField, keyword: string) => void;
  onReset: () => void;
}) {
  const [nextField, setNextField] = useState<QaSearchField>(field);
  const [nextKeyword, setNextKeyword] = useState(keyword ?? "");

  return (
    <form
      role="search"
      className="mypage-qa-search flex flex-wrap gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (nextKeyword.trim()) onSearch(nextField, nextKeyword.trim());
      }}
    >
      <Select value={nextField} onValueChange={(value) => setNextField(qaSearchField(value))}>
        <SelectTrigger aria-label="검색 대상" className="w-[120px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SEARCH_FIELDS.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <label htmlFor="qa-search-keyword" className="sr-only">
        검색어
      </label>
      <Input
        id="qa-search-keyword"
        type="search"
        placeholder="검색어를 입력하세요"
        value={nextKeyword}
        onChange={(event) => setNextKeyword(event.target.value)}
        className="min-w-0 flex-1 sm:max-w-xs"
      />
      <Button type="submit" variant="secondary">
        <Search className="mr-1 size-4" aria-hidden />
        검색
      </Button>
      {keyword ? (
        <Button type="button" variant="ghost" onClick={onReset}>
          검색 해제
        </Button>
      ) : null}
    </form>
  );
}

/** 목록에 보일 내용 한 줄 — 편집기로 쓴 문의(qa_html)는 태그를 걷어 글자만. */
function contentPreview(item: QaItem): string {
  const text = item.qa_html ? htmlToText(item.qa_content) : item.qa_content.replace(/\s+/g, " ").trim();
  return truncate(text, 120);
}

export function QaListRow({
  item,
  number,
  subjectLength,
}: {
  item: QaItem;
  /** 목록 번호(전체 건수에서 거꾸로) — 그누보드 목록의 번호 칸. */
  number: number;
  /** 관리자 설정의 제목 길이(qa_subject_len). 0 이면 자르지 않는다. */
  subjectLength: number;
}) {
  const answered = item.qa_status === 1;
  const hasFile = Boolean(item.qa_file1 || item.qa_file2);
  const subject = subjectLength > 0 ? truncate(item.qa_subject, subjectLength) : item.qa_subject;
  const preview = contentPreview(item);

  return (
    <li className="flex items-start gap-3 p-4 transition-colors hover:bg-muted/50">
      <span className="mt-0.5 w-10 shrink-0 text-xs tabular-nums text-muted-foreground">
        <span className="sr-only">번호 </span>
        {number}
      </span>
      <Link href={`/mypage/qas/${item.qa_id}`} className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              answered ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
            )}
          >
            {answered ? "답변완료" : "답변대기"}
          </span>
          {item.qa_category ? (
            <span className="rounded border px-1.5 py-0.5 text-xs text-muted-foreground">{item.qa_category}</span>
          ) : null}
          <span className="break-words text-sm font-medium">{subject}</span>
          {hasFile ? <Paperclip className="size-3.5 text-muted-foreground" aria-label="첨부파일" /> : null}
        </span>
        {preview ? <span className="mt-1 block break-words text-sm text-muted-foreground">{preview}</span> : null}
        <span className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          <time dateTime={item.qa_datetime}>{formatDate(item.qa_datetime)}</time>
        </span>
      </Link>
    </li>
  );
}
