"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { apiClient } from "@/lib/api";
import type { WritePost } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatNumber } from "@/lib/utils";
import { Loader2, LockKeyhole } from "lucide-react";
import { MemberSideview } from "@/components/MemberSideview";
import { boardPostHref, type BbsRewriteMode } from "@/lib/board-url";

interface InfinitePostListProps {
  boTable: string;
  initialPosts: WritePost[];
  notices: WritePost[];
  listNumStart: number;
  totalPages: number;
  perPage: number;
  sfl?: string;
  stx?: string;
  sca?: string;
  bbsRewriteMode?: BbsRewriteMode;
  listQuery?: string;
  initialPage?: number;
}

export function InfinitePostList({
  boTable,
  initialPosts,
  notices: initialNotices,
  listNumStart,
  totalPages,
  perPage,
  sfl,
  stx,
  sca,
  bbsRewriteMode,
  listQuery,
  initialPage = 1,
}: InfinitePostListProps) {
  const [posts, setPosts] = useState<WritePost[]>(initialPosts);
  const [notices, setNotices] = useState<WritePost[]>(initialNotices);
  const [page, setPage] = useState(initialPage);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(totalPages > 1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return;
    const nextPage = page + 1;
    setLoading(true);
    try {
      const res = await apiClient.get(`/boards/${boTable}/posts`, {
        params: { page: nextPage, per_page: perPage, sfl, stx, sca },
      });
      const newPosts = (Array.isArray(res.data) ? res.data : []) as WritePost[];
      const newNotices = newPosts.filter((p: WritePost) => p.is_notice);
      const filtered = newPosts.filter((p: WritePost) => !p.is_notice);
      setNotices((prev) => [...prev, ...newNotices]);
      setPosts((prev) => [...prev, ...filtered]);
      setPage(nextPage);
      if (nextPage >= totalPages || newPosts.length === 0) {
        setHasMore(false);
      }
    } catch {
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [loading, hasMore, page, boTable, perPage, sfl, stx, sca, totalPages]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore]);

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col className="w-12 md:w-16" />
              <col />
              <col className="hidden md:table-column md:w-32" />
              <col className="hidden md:table-column md:w-28" />
              <col className="hidden md:table-column md:w-20" />
            </colgroup>
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-2 py-3 text-left w-12 md:w-16 md:px-4">번호</th>
                <th className="px-4 py-3 text-left">제목</th>
                <th className="px-4 py-3 text-left w-32 hidden md:table-cell">글쓴이</th>
                <th className="px-4 py-3 text-center w-28 hidden md:table-cell whitespace-nowrap">날짜</th>
                <th className="px-4 py-3 text-center w-20 hidden md:table-cell">조회</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((post) => (
                <tr
                  key={`notice-${post.wr_id}`}
                  className="border-b bg-primary/5 hover:bg-primary/10 transition-colors"
                >
                  <td className="px-4 py-3">
                    <Badge variant="default" className="text-xs">공지</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <a
                      href={boardPostHref(boTable, post, bbsRewriteMode, listQuery)}
                      className="hover:text-primary transition-colors font-medium"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        {post.ca_name && <Badge variant="secondary" className="shrink-0 text-xs">{post.ca_name}</Badge>}
                        {post.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                        <span className="flex min-w-0 flex-1 items-center gap-1">
                          <span className="min-w-0 truncate">{post.wr_subject}</span>
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
                  <td className="px-4 py-3 text-center text-muted-foreground hidden md:table-cell whitespace-nowrap">{formatDate(post.wr_datetime)}</td>
                  <td className="px-4 py-3 text-center text-muted-foreground hidden md:table-cell whitespace-nowrap">{formatNumber(post.wr_hit)}</td>
                </tr>
              ))}

              {posts.map((post, idx) => (
                <tr key={post.wr_id} className="border-b hover:bg-muted/50 transition-colors">
                  <td className="px-4 py-3 text-muted-foreground">
                    {listNumStart - idx}
                  </td>
                  <td className="px-4 py-3">
                    <a
                      href={boardPostHref(boTable, post, bbsRewriteMode, listQuery)}
                      className="hover:text-primary transition-colors"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        {post.ca_name && <Badge variant="secondary" className="shrink-0 text-xs">{post.ca_name}</Badge>}
                        {post.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
                        <span className="flex min-w-0 flex-1 items-center gap-1">
                          <span className="min-w-0 truncate">{post.wr_subject}</span>
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
                  <td className="px-4 py-3 text-center text-muted-foreground hidden md:table-cell whitespace-nowrap">{formatDate(post.wr_datetime)}</td>
                  <td className="px-4 py-3 text-center text-muted-foreground hidden md:table-cell whitespace-nowrap">{formatNumber(post.wr_hit)}</td>
                </tr>
              ))}

              {posts.length === 0 && notices.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                    게시글이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>

      {/* Sentinel + Loading */}
      <div ref={sentinelRef} className="py-4 text-center">
        {loading && (
          <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
        )}
        {!hasMore && posts.length > 0 && (
          <p className="text-sm text-muted-foreground">모든 게시글을 불러왔습니다.</p>
        )}
      </div>
    </Card>
  );
}
