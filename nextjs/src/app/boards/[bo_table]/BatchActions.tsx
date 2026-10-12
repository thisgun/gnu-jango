"use client";

import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LockKeyhole, Trash2 } from "lucide-react";
import { formatDate, formatNumber } from "@/lib/utils";
import { toastSuccess, toastError } from "@/lib/toast";
import { useVisitedPosts } from "@/hooks/useVisitedPosts";
import { KeyboardNav } from "./KeyboardNav";
import type { WritePost } from "@/lib/types";
import { MemberSideview } from "@/components/MemberSideview";
import { boardPostHref, type BbsRewriteMode } from "@/lib/board-url";

interface BatchPostListProps {
  boTable: string;
  isAdmin: boolean;
  notices: WritePost[];
  posts: WritePost[];
  totalCount: number;
  noticeCount: number;
  listNumStart: number;
  bbsRewriteMode?: BbsRewriteMode;
  listQuery?: string;
}

export function BatchPostList({
  boTable,
  isAdmin,
  notices,
  posts,
  listNumStart,
  bbsRewriteMode,
  listQuery,
}: BatchPostListProps) {
  const { isVisited } = useVisitedPosts();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deletedIds, setDeletedIds] = useState<Set<number>>(new Set());

  const allIds = Array.from(new Set([...notices, ...posts].map((post) => post.wr_id)));
  const visibleIds = allIds.filter((id) => !deletedIds.has(id));

  const toggleOne = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === visibleIds.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleIds));
    }
  };

  const handleBatchDelete = useCallback(async () => {
    if (selected.size === 0) return;
    if (!confirm(`선택한 ${selected.size}개의 게시글을 삭제하시겠습니까?`)) return;

    setDeleting(true);
    const selectedIds = [...selected];
    const deletedInBatch = new Set<number>();
    const failedRequests = new Set<number>();
    try {
      for (const wrId of selectedIds) {
        if (deletedInBatch.has(wrId)) continue;

        try {
          const response = await apiClient.delete<{ deleted_ids?: number[] }>(
            `/posts/${boTable}/${wrId}`
          );
          for (const deletedId of response.data?.deleted_ids ?? [wrId]) {
            deletedInBatch.add(deletedId);
          }
          deletedInBatch.add(wrId);
        } catch {
          failedRequests.add(wrId);
        }
      }

      setDeletedIds((prev) => new Set([...prev, ...deletedInBatch]));
      // Keep only the posts that were not removed selected, so a retry is one click.
      setSelected(new Set(selectedIds.filter((id) => !deletedInBatch.has(id))));

      const failedCount = [...failedRequests].filter((id) => !deletedInBatch.has(id)).length;
      if (failedCount > 0) {
        const deletedSelectedCount = selectedIds.length - failedCount;
        toastError(
          deletedSelectedCount > 0
            ? `${deletedSelectedCount}개 선택 글은 삭제했고 ${failedCount}개 선택 글은 삭제하지 못했습니다. 삭제하지 못한 글은 선택된 상태로 남아 있습니다.`
            : "선택한 게시글을 삭제하지 못했습니다. 선택은 유지되므로 다시 시도할 수 있습니다."
        );
      } else if (deletedInBatch.size > 0) {
        toastSuccess(`${deletedInBatch.size}개의 게시글이 삭제되었습니다.`);
      }
    } finally {
      setDeleting(false);
    }
  }, [selected, boTable]);

  const postLinks = posts
    .filter((p) => !deletedIds.has(p.wr_id))
    .map((p) => ({ wrId: p.wr_id, boTable, href: boardPostHref(boTable, p, bbsRewriteMode, listQuery) }));

  return (
    <>
      {/* Keyboard navigation hint */}
      <KeyboardNav postLinks={postLinks} />

      {/* Batch toolbar */}
      {isAdmin && selected.size > 0 && (
        <div className="flex items-center gap-3 mb-3 p-3 rounded-lg bg-primary/5 border">
          <span className="text-sm font-medium">{selected.size}개 선택됨</span>
          <Button variant="destructive" size="sm" onClick={handleBatchDelete} disabled={deleting}>
            <Trash2 className="h-4 w-4 mr-1" />
            {deleting ? "삭제 중..." : "선택 삭제"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            선택 해제
          </Button>
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full table-fixed text-sm">
              <colgroup>
                {isAdmin ? <col className="w-10" /> : null}
                <col className="w-12 md:w-16" />
                <col />
                <col className="hidden md:table-column md:w-32" />
                <col className="hidden md:table-column md:w-20" />
                <col className="hidden md:table-column md:w-28" />
              </colgroup>
              <thead className="hidden md:table-header-group">
                <tr className="border-b bg-muted/50">
                  {isAdmin && (
                    <th className="px-2 py-3 w-10 text-center">
                      <input
                        type="checkbox"
                        checked={selected.size === visibleIds.length && visibleIds.length > 0}
                        onChange={toggleAll}
                        disabled={deleting}
                        className="checkbox checkbox-sm text-base-content border border-base-content/40"
                        aria-label="Select all posts"
                      />
                    </th>
                  )}
                  <th className="hidden w-16 px-4 py-3 text-left md:table-cell">번호</th>
                  <th className="px-4 py-3 text-left">제목</th>
                  <th className="px-4 py-3 text-left w-32 hidden md:table-cell">글쓴이</th>
                  <th className="hidden w-20 px-4 py-3 text-center md:table-cell">조회</th>
                  <th className="hidden w-28 whitespace-nowrap px-4 py-3 text-center md:table-cell">날짜</th>
                </tr>
              </thead>
              <tbody>
                {notices.filter((post) => !deletedIds.has(post.wr_id)).map((post) => (
                  <tr key={`notice-${post.wr_id}`} className="border-b bg-primary/5 hover:bg-primary/10 transition-colors">
                    {isAdmin && (
                      <td className="px-2 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={selected.has(post.wr_id)}
                          onChange={() => toggleOne(post.wr_id)}
                          disabled={deleting}
                          className="checkbox checkbox-sm text-base-content border border-base-content/40"
                          aria-label={`Select notice post ${post.wr_id}`}
                        />
                      </td>
                    )}
                    <td className="hidden px-4 py-3 md:table-cell">
                      <Badge variant="default" className="text-xs">공지</Badge>
                    </td>
                    <td colSpan={2} className="px-4 py-4 md:hidden">
                      <a
                        href={boardPostHref(boTable, post, bbsRewriteMode, listQuery)}
                        className={`block min-w-0 transition-colors hover:text-primary ${isVisited(boTable, post.wr_id) ? "text-muted-foreground" : ""}`}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Badge variant="default" className="shrink-0 text-xs">공지</Badge>
                          {post.ca_name && <Badge variant="secondary" className="shrink-0 text-xs">{post.ca_name}</Badge>}
                          {post.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                          <span className="flex min-w-0 flex-1 items-center gap-1 font-medium">
                            <span className="min-w-0 truncate" title={post.wr_subject}>{post.wr_subject}</span>
                            {post.wr_comment > 0 && <Badge variant="outline" className="shrink-0 border-transparent bg-primary/10 px-1 text-xs text-primary">{post.wr_comment}</Badge>}
                          </span>
                        </span>
                      </a>
                      <span className="mt-1 flex min-w-0 items-center gap-2 text-xs font-normal text-muted-foreground">
                        <span className="min-w-0 flex-1 truncate">
                          <MemberSideview
                            mbId={post.mb_id}
                            name={post.mb_nick || post.wr_name}
                            email={post.wr_email}
                            homepage={post.wr_homepage}
                            iconUrl={post.mb_icon_path}
                            boTable={boTable}
                          />
                        </span>
                        <span className="shrink-0">{formatNumber(post.wr_hit)}</span>
                        <time className="shrink-0" dateTime={post.wr_datetime}>{formatDate(post.wr_datetime)}</time>
                      </span>
                    </td>
                    <td className="hidden px-4 py-4 md:table-cell md:py-3">
                      <a
                        href={boardPostHref(boTable, post, bbsRewriteMode, listQuery)}
                        className={`block min-w-0 transition-colors hover:text-primary ${isVisited(boTable, post.wr_id) ? "text-muted-foreground" : ""}`}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          {post.ca_name && <Badge variant="secondary" className="shrink-0 text-xs">{post.ca_name}</Badge>}
                          {post.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                          <span className="flex min-w-0 flex-1 items-center gap-1 font-medium">
                            <span className="min-w-0 truncate" title={post.wr_subject}>{post.wr_subject}</span>
                            {post.wr_comment > 0 && <Badge variant="outline" className="shrink-0 border-transparent bg-primary/10 px-1 text-xs text-primary">{post.wr_comment}</Badge>}
                          </span>
                        </span>
                      </a>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground hidden md:table-cell">
                      <MemberSideview
                        mbId={post.mb_id}
                        name={post.mb_nick || post.wr_name}
                        email={post.wr_email}
                        homepage={post.wr_homepage}
                        iconUrl={post.mb_icon_path}
                        boTable={boTable}
                      />
                    </td>
                    <td className="hidden whitespace-nowrap px-4 py-3 text-center text-muted-foreground md:table-cell">{formatNumber(post.wr_hit)}</td>
                    <td className="hidden whitespace-nowrap px-4 py-3 text-center text-muted-foreground md:table-cell">{formatDate(post.wr_datetime)}</td>
                  </tr>
                ))}

                {posts.map((post, idx) =>
                  deletedIds.has(post.wr_id) ? null : (
                    <tr key={post.wr_id} data-keyboard-nav-row className="border-b hover:bg-muted/50 transition-colors">
                      {isAdmin && (
                        <td className="px-2 py-3 text-center">
                          <input
                            type="checkbox"
                            checked={selected.has(post.wr_id)}
                            onChange={() => toggleOne(post.wr_id)}
                            disabled={deleting}
                            className="checkbox checkbox-sm text-base-content border border-base-content/40"
                            aria-label={`Select post ${post.wr_id}`}
                          />
                        </td>
                      )}
                  <td className="w-12 px-2 py-3 text-center text-muted-foreground align-top md:w-16 md:px-4">{listNumStart - idx}</td>
                  <td className="px-4 py-4 md:py-3">
                    <a
                          href={boardPostHref(boTable, post, bbsRewriteMode, listQuery)}
                        className={`block min-w-0 transition-colors hover:text-primary ${isVisited(boTable, post.wr_id) ? "text-muted-foreground" : ""}`}
                      >
                      <span className="flex min-w-0 items-center gap-2">
                        {post.ca_name && <Badge variant="secondary" className="shrink-0 text-xs">{post.ca_name}</Badge>}
                        {post.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                        <span className="flex min-w-0 flex-1 items-center gap-1">
                          <span className="min-w-0 truncate" title={post.wr_subject}>{post.wr_subject}</span>
                          {post.wr_comment > 0 && <Badge variant="outline" className="shrink-0 border-transparent bg-primary/10 px-1 text-xs text-primary">{post.wr_comment}</Badge>}
                        </span>
                      </span>
                    </a>
                    <span className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground md:hidden">
                      <span className="min-w-0 flex-1 truncate">
                        <MemberSideview
                          mbId={post.mb_id}
                          name={post.mb_nick || post.wr_name}
                          email={post.wr_email}
                          homepage={post.wr_homepage}
                          iconUrl={post.mb_icon_path}
                          boTable={boTable}
                        />
                      </span>
                      <span className="shrink-0">{formatNumber(post.wr_hit)}</span>
                      <time className="shrink-0" dateTime={post.wr_datetime}>{formatDate(post.wr_datetime)}</time>
                    </span>
                  </td>
                      <td className="px-4 py-3 text-muted-foreground hidden md:table-cell">
                      <MemberSideview
                        mbId={post.mb_id}
                        name={post.mb_nick || post.wr_name}
                        email={post.wr_email}
                        homepage={post.wr_homepage}
                        iconUrl={post.mb_icon_path}
                        boTable={boTable}
                      />
                    </td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-center text-muted-foreground md:table-cell">{formatNumber(post.wr_hit)}</td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-center text-muted-foreground md:table-cell">{formatDate(post.wr_datetime)}</td>
                    </tr>
                  )
                )}

                {visibleIds.length === 0 && (
                  <tr>
                    <td colSpan={isAdmin ? 6 : 5} className="px-4 py-12 text-center text-muted-foreground">
                      게시글이 없습니다.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
