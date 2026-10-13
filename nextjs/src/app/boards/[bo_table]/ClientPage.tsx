"use client";

import { useEffect, useMemo, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useSearchParams } from "next/navigation";
import type { Board, WritePost } from "@/lib/types";
import { GALLERY_BOARDS } from "@/lib/config";
import { cn, formatDate } from "@/lib/utils";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { getBoardResult, getBoardPosts } from "@/services/boards";
import { getClientPublicSettings } from "@/services/settings";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ImageIcon, RssIcon, FolderX } from "lucide-react";
import { BatchPostList } from "./BatchActions";
import { GalleryThumbnail } from "./GalleryThumbnail";
import { InfinitePostList } from "./InfinitePostList";
import { SearchForm } from "./SearchForm";
import { g5ShortHref } from "@/lib/g5-short-url";
import { boardPostHref } from "@/lib/board-url";
import { CommunitySidebar } from "@/components/layout/CommunitySidebar";
import { useAuthStore } from "@/store/auth";

interface ClientPageProps {
  boTable?: string;
}

interface PostsState {
  list: WritePost[];
  total: number;
  totalPage: number;
  noticeCount: number;
  totalNoticeCount: number;
  error?: string;
}

const EMPTY_POSTS: PostsState = {
  list: [],
  total: 0,
  totalPage: 1,
  noticeCount: 0,
  totalNoticeCount: 0,
};

function toPage(value: string | null): number {
  const parsed = Number.parseInt(value || "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export default function BoardPostListClient({ boTable }: ClientPageProps) {
  const user = useAuthStore((state) => state.user);
  const bo_table = useRuntimeRouteParam("bo_table", ["/bbs/:bo_table", "/boards/:bo_table", "/:bo_table"], boTable);
  const searchParams = useSearchParams();
  const queryKey = searchParams.toString();

  const page = toPage(searchParams.get("page"));
  const listQuery = searchParams.toString();
  const sfl = searchParams.get("sfl") || undefined;
  const stx = searchParams.get("stx") || undefined;
  const sca = searchParams.get("sca") || undefined;

  const paginationSearchParams = useMemo(
    () => ({
      page: searchParams.get("page") || undefined,
      sfl,
      stx,
      sca,
    }),
    [sca, searchParams, sfl, stx]
  );

  const [board, setBoard] = useState<Board | null>(null);
  const [postsData, setPostsData] = useState<PostsState>(EMPTY_POSTS);
  const [bbsRewriteMode, setBbsRewriteMode] = useState(0);
  const [infiniteScroll, setInfiniteScroll] = useState(false);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (!bo_table) {
      setBoard(null);
      setPostsData(EMPTY_POSTS);
      setMissing(true);
      setLoadError(null);
      setLoading(false);
      return;
    }

    let alive = true;
    setLoading(true);
    setMissing(false);
    setLoadError(null);

    async function load() {
      const boardResult = await getBoardResult(bo_table);
      if (!alive) return;

      if (!boardResult.ok) {
        setBoard(null);
        setPostsData(EMPTY_POSTS);
        if (boardResult.status === 404) {
          setMissing(true);
        } else {
          setLoadError(boardResult.error);
        }
        setLoading(false);
        return;
      }

      const nextBoard = boardResult.data;
      setBoard(nextBoard);
      const perPage = nextBoard.bo_page_rows || 15;
      const [settings, nextPosts] = await Promise.all([
        getClientPublicSettings().catch(() => null),
        getBoardPosts({ boTable: bo_table, page, perPage, sfl, stx, sca }),
      ]);

      if (!alive) return;
      setBbsRewriteMode(Number(settings?.cf_bbs_rewrite ?? 0));
      setInfiniteScroll(!!settings?.infinite_scroll);
      setPostsData(nextPosts);
      setLoading(false);
    }

    load().catch((error: unknown) => {
      if (!alive) return;
      setBoard(null);
      setPostsData(EMPTY_POSTS);
      setMissing(false);
      setLoadError(error instanceof Error ? error.message : "Failed to load board.");
      setLoading(false);
    });

    return () => {
      alive = false;
    };
  }, [bo_table, loadAttempt, page, queryKey, sca, sfl, stx]);

  useEffect(() => {
    if (!board || !bo_table) return;

    applyClientPageMetadata({
      title: board.bo_subject,
      description: board.bo_content || `${board.bo_subject} 게시판`,
      path: `/boards/${bo_table}`,
    });
  }, [board, bo_table]);

  if (loading) {
    return (
      <div className="site-container px-4 py-8">
        <div className="page-hero mb-5 animate-pulse">
          <div className="h-3 w-24 rounded bg-muted" />
          <div className="mt-3 h-8 w-48 rounded bg-muted" />
          <div className="mt-2 h-4 w-72 max-w-full rounded bg-muted" />
        </div>
        <div className="surface-panel space-y-3 p-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (missing || !board) {
    if (loadError) {
      return (
        <div className="site-container px-4 py-20">
          <ErrorState
            title="게시판 정보를 불러오지 못했습니다."
            description={loadError}
          />
          <div className="mt-4 flex justify-center">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setLoadAttempt((attempt) => attempt + 1)}
            >
              다시 시도
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div className="site-container px-4 py-20">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-muted">
            <FolderX className="size-7 text-muted-foreground" />
          </div>
          <div className="space-y-1">
            <h1 className="text-xl font-bold text-foreground">게시판을 찾을 수 없습니다</h1>
            <p className="text-sm text-muted-foreground">
              존재하지 않거나 접근 권한이 없는 게시판입니다.
            </p>
          </div>
          <Button asChild>
            <Link href={g5ShortHref("/boards")}>게시판 목록으로</Link>
          </Button>
        </div>
      </div>
    );
  }

  const {
    list: posts,
    total: totalCount,
    totalPage,
    noticeCount,
    totalNoticeCount,
    error: postsError,
  } = postsData;
  const categories = board.bo_category_list
    ? board.bo_category_list.split("|").filter(Boolean)
    : [];
  const notices = posts.filter((post) => post.is_notice);
  const regularPosts = posts.filter((post) => !post.is_notice);
  const perPage = board.bo_page_rows || 15;
  const listNumStart = totalCount - (page - 1) * perPage - totalNoticeCount;
  const isGallery = GALLERY_BOARDS.includes(bo_table);
  const galleryCols = board.bo_gallery_cols || 4;
  const canManageBoard = Boolean(
    user &&
      (user.is_super_admin || user.mb_id === board.bo_admin || user.mb_id === board.gr_admin)
  );
  const canWrite = Boolean(
    (user?.mb_level ?? 1) >= board.bo_write_level ||
    user?.is_super_admin ||
    user?.mb_id === board.bo_admin ||
    user?.mb_id === board.gr_admin
  );
  const canViewRss = board.bo_use_rss_view > 0 && board.bo_read_level < 2;

  return (
    <div className="site-container pb-20 md:pb-12 solune-board-list-page">
      <div className="solune-content-shell">
        <main className="solune-main-content">
      <Breadcrumb items={[{ label: "게시판", href: g5ShortHref("/boards") }, { label: board.bo_subject }]} />

      <header className="flex flex-col justify-between gap-4 pb-1 md:flex-row md:items-end md:pb-5">
        <div>
          <h1 className="page-hero-title">{board.bo_subject}</h1>
          <p className="page-hero-desc">
            {totalCount.toLocaleString("ko-KR")}개의 글 · {page} / {totalPage} 페이지
          </p>
        </div>
          <div className="flex items-center gap-2">
            {canViewRss ? (
              <a
                href={g5ShortHref(`/boards/${bo_table}/rss`)}
                target="_blank"
                rel="noopener noreferrer"
                title="RSS 피드"
                className="hidden h-10 items-center justify-center rounded-[4px] border px-3 text-sm font-bold text-[#b45309] transition-colors hover:bg-[#fff7e6] md:inline-flex"
              >
                <RssIcon className="mr-1.5 h-4 w-4" />
                RSS
              </a>
            ) : null}
            {canWrite ? (
              <Button asChild>
                <a href={g5ShortHref(`/boards/${bo_table}/write`)}>글쓰기</a>
              </Button>
            ) : null}
          </div>
      </header>

      {categories.length > 0 && (
        <div className="surface-toolbar mb-5">
          <a href={g5ShortHref(`/boards/${bo_table}`)} className={cn("filter-chip", !sca && "filter-chip-active")}>
            전체
          </a>
          {categories.map((category) => (
            <a
              key={category}
              href={g5ShortHref(`/boards/${bo_table}?sca=${encodeURIComponent(category)}`)}
              className={cn("filter-chip", sca === category && "filter-chip-active")}
            >
              {category}
            </a>
          ))}
        </div>
      )}

      {postsError && (
        <ErrorState
          className="mb-6"
          title="게시글을 불러오지 못했습니다"
          description={postsError}
          onAction={() => setLoadAttempt((attempt) => attempt + 1)}
        />
      )}

      {!postsError && isGallery ? (
        <>
          {notices.length > 0 && (
            <div className="mb-4 space-y-1">
              {notices.map((post) => (
                <div
                  key={`notice-${post.wr_id}`}
                  className="flex items-center gap-2 rounded bg-primary/5 px-2 py-1.5"
                >
                  <Badge variant="destructive" className="shrink-0 text-xs">
                    Notice
                  </Badge>
                  <a
                    href={boardPostHref(bo_table, post, bbsRewriteMode, listQuery)}
                    className="truncate text-sm font-medium transition-colors hover:text-primary"
                  >
                    {post.wr_subject}
                  </a>
                </div>
              ))}
            </div>
          )}

          {regularPosts.length > 0 ? (
            <div className="gallery-grid grid grid-cols-2 gap-4 sm:grid-cols-3">
              <style>{`
                @media (min-width: 768px) {
                  .gallery-grid { grid-template-columns: repeat(${galleryCols}, minmax(0, 1fr)) !important; }
                }
              `}</style>
              {regularPosts.map((post, index) => (
                <a
                  key={post.wr_id}
                  href={boardPostHref(bo_table, post, bbsRewriteMode, listQuery)}
                  className="group"
                >
                  <Card className="h-full overflow-hidden transition-shadow hover:shadow-lg">
                    <div className="relative aspect-square bg-muted">
                      {post.thumbnail ? (
                        <GalleryThumbnail
                          src={post.thumbnail}
                          alt={post.wr_subject}
                          sizes={`(max-width: 768px) 50vw, ${Math.floor(100 / galleryCols)}vw`}
                          priority={index < galleryCols * 2}
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center">
                          <ImageIcon className="h-12 w-12 text-muted-foreground/30" />
                        </div>
                      )}
                    </div>
                    <CardContent className="p-3">
                      <h3 className="truncate text-sm font-medium transition-colors group-hover:text-primary">
                        {post.wr_subject}
                        {post.wr_comment > 0 && (
                          <Badge variant="secondary" className="ml-1.5 text-xs">
                            {post.wr_comment}
                          </Badge>
                        )}
                      </h3>
                      <div className="mt-1.5 flex items-center justify-between text-xs text-muted-foreground">
                        <span>{post.mb_nick || post.wr_name}</span>
                        <span>{formatDate(post.wr_datetime)}</span>
                      </div>
                    </CardContent>
                  </Card>
                </a>
              ))}
            </div>
          ) : (
            posts.length === 0 && <EmptyState title="아직 등록된 게시글이 없습니다" />
          )}
        </>
      ) : !postsError && infiniteScroll ? (
        <InfinitePostList
          key={`${bo_table}:${listQuery}`}
          boTable={bo_table}
          initialPosts={regularPosts}
          notices={notices}
          listNumStart={listNumStart}
          totalPages={totalPage}
          perPage={perPage}
          sfl={sfl}
          stx={stx}
          sca={sca}
          bbsRewriteMode={bbsRewriteMode}
          listQuery={listQuery}
          initialPage={page}
        />
      ) : !postsError ? (
        <BatchPostList
          boTable={bo_table}
          isAdmin={canManageBoard}
          notices={notices}
          posts={regularPosts}
          totalCount={totalCount}
          noticeCount={noticeCount}
          listNumStart={listNumStart}
          bbsRewriteMode={bbsRewriteMode}
          listQuery={listQuery}
        />
      ) : null}

      {totalPage > 1 && !infiniteScroll && (
        <div className="mt-6 flex justify-center">
          <Pagination
            currentPage={page}
            totalPages={totalPage}
            baseUrl={g5ShortHref(`/boards/${bo_table}`)}
            searchParams={paginationSearchParams}
          />
        </div>
      )}
      <div className="surface-panel mt-5 p-4">
        <SearchForm boTable={bo_table} sfl={sfl} stx={stx} sca={sca} />
      </div>
        </main>
        <CommunitySidebar rewriteMode={bbsRewriteMode} />
      </div>
    </div>
  );
}
