"use client";

import type { ReactNode } from "react";
import { LockKeyhole } from "lucide-react";
import { MemberAvatar } from "@/components/MemberAvatar";
import { MemberSideview } from "@/components/MemberSideview";
import type { WritePost } from "@/lib/types";
import { boardPostHref, type BbsRewriteMode } from "@/lib/board-url";
import { g5ShortHref } from "@/lib/g5-short-url";
import { cn, formatDate, formatNumber } from "@/lib/utils";

const HOUR_MS = 60 * 60 * 1000;

/** 그누보드의 새글 표식: 등록 뒤 bo_new 시간 안. 0 이면 끈 것. */
export function isNewPost(post: WritePost, boNew: number): boolean {
  if (!boNew || !post.wr_datetime) return false;
  const written = new Date(post.wr_datetime.replace(" ", "T")).getTime();
  return Number.isFinite(written) && Date.now() - written < boNew * HOUR_MS;
}

/** 인기글 표식: 조회가 bo_hot 이상. 0 이면 끈 것. */
export function isHotPost(post: WritePost, boHot: number): boolean {
  return boHot > 0 && post.wr_hit >= boHot;
}

export type PostListRowProps = {
  post: WritePost;
  boTable: string;
  /** 번호 칸. 공지는 undefined. */
  number?: number;
  boNew?: number;
  boHot?: number;
  isVisited?: boolean;
  /** 글보기 아래 목록에서 지금 읽고 있는 글 */
  isCurrent?: boolean;
  bbsRewriteMode?: BbsRewriteMode;
  /** 글 주소에 붙여 둘 목록 조건(쪽 · 분류 · 검색) — 글에서 목록으로 돌아올 때 그대로 돌아온다. */
  listQuery?: string;
  /** 관리자 일괄 선택 칸(체크박스). 있으면 첫 칸. */
  leading?: ReactNode;
  /** 키보드 이동(KeyboardNav)이 줄을 찾는 표식 */
  keyboardNavRow?: boolean;
};

/**
 * 목록의 글 한 줄 — 레퍼런스 list.skin 의 .cb-row(테마 BoardListRow):
 * [번호 레일] [분류 칩 · 제목 · 댓글 수 · 표식] [아바타 · 이름] [조회] [날짜].
 * 폰 폭에서는 solune-theme.internal-pages.css 가 이 줄을 격자로 바꿔 글쓴이 · 조회 · 날짜를 제목 아래로 접는다.
 */
export function PostListRow({
  post,
  boTable,
  number,
  boNew = 0,
  boHot = 0,
  isVisited = false,
  isCurrent = false,
  bbsRewriteMode,
  listQuery,
  leading,
  keyboardNavRow,
}: PostListRowProps) {
  const isNotice = number === undefined;
  const href = boardPostHref(boTable, post, bbsRewriteMode, listQuery);
  const replyDepth = post.wr_reply ? Math.min(post.wr_reply.length, 5) : 0;
  const categoryHref = post.ca_name
    ? g5ShortHref(`/boards/${encodeURIComponent(boTable)}?sca=${encodeURIComponent(post.ca_name)}`)
    : undefined;
  const name = post.mb_nick || post.wr_name || "";
  const isNew = !isNotice && isNewPost(post, boNew);
  const isHot = !isNotice && isHotPost(post, boHot);

  return (
    <tr
      data-keyboard-nav-row={keyboardNavRow ? "" : undefined}
      aria-current={isCurrent ? "page" : undefined}
      className={cn(
        "solune-blr",
        leading !== undefined && "has-check",
        isNotice && "is-notice",
        isVisited && "is-visited",
        isCurrent && "is-current"
      )}
    >
      {leading !== undefined ? <td className="solune-blr-check">{leading}</td> : null}
      <td className="solune-blr-rail">
        {isNotice ? (
          <span className="solune-blr-flag is-new">공지</span>
        ) : isCurrent ? (
          <span className="solune-blr-no is-current">열람중</span>
        ) : (
          <span className="solune-blr-no">{number}</span>
        )}
      </td>
      <td className="solune-blr-body">
        <span className="solune-blr-title-line">
          {post.ca_name ? (
            <a href={categoryHref} className="solune-blr-cat">{post.ca_name}</a>
          ) : null}
          <a
            href={href}
            className="solune-blr-title"
            style={replyDepth ? { paddingLeft: `${replyDepth * 0.9}rem` } : undefined}
          >
            {replyDepth ? (
              <span className="solune-blr-reply" aria-label="답글">↳</span>
            ) : null}
            {post.wr_subject}
          </a>
          {post.is_secret ? (
            <LockKeyhole className="solune-blr-lock size-3.5 shrink-0 text-muted-foreground" aria-label="비밀글" />
          ) : null}
          {post.wr_comment > 0 ? (
            <span className="solune-blr-cmt">
              <span className="sr-only">댓글 </span>
              {post.wr_comment}
              <span className="sr-only">개</span>
            </span>
          ) : null}
          {isNew ? (
            <span className="solune-blr-flag is-new">NEW</span>
          ) : isHot ? (
            <span className="solune-blr-flag is-hot">HOT</span>
          ) : null}
        </span>
      </td>
      <td className="solune-blr-author">
        <MemberAvatar name={name} member={post} className="solune-blr-avatar" size={22} />
        <span className="solune-blr-name" title={name || undefined}>
          <MemberSideview
            mbId={post.mb_id}
            name={name}
            email={post.wr_email}
            homepage={post.wr_homepage}
            boTable={boTable}
          >
            <span>{name}</span>
          </MemberSideview>
        </span>
      </td>
      <td className="solune-blr-hit">
        <span className="sr-only">조회 </span>
        {formatNumber(post.wr_hit)}
      </td>
      <td className="solune-blr-date">{formatDate(post.wr_datetime)}</td>
    </tr>
  );
}
