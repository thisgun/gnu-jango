"use client";

import { useEffect, useMemo, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useSearchParams } from "next/navigation";
import type { Board, WritePost } from "@/lib/types";
import { g5PathForRuntime, isGalleryBoard } from "@/lib/config";
import { cn } from "@/lib/utils";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { getBoardCategoryCounts, getBoardResult, getBoardPosts } from "@/services/boards";
import { getClientPublicSettings } from "@/services/settings";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { RssIcon, FolderX } from "lucide-react";
import { BatchPostList } from "./BatchActions";
import { GalleryPostGrid } from "./GalleryPostGrid";
import { InfinitePostList } from "./InfinitePostList";
import { SearchForm } from "./SearchForm";
import { g5ShortHref } from "@/lib/g5-short-url";
import { useAuthStore } from "@/store/auth";

interface ClientPageProps {
  boTable?: string;
  /**
   * 글보기 아래에 붙는 목록. 빵부스러기 · 머리띠 · 글쓰기 · 메타데이터 · 레일은 빼고
   * 분류 칩 · 글 줄 · 쪽 · 검색만 그린다(그누보드 view 아래 list 와 같다).
   */
  embedded?: boolean;
  /** embedded 일 때 지금 읽고 있는 글 — 줄에 "열람중"으로 표시한다 */
  currentWrId?: number;
}

interface PostsState {
  list: WritePost[];
  total: number;
  totalPage: number;
  noticeCount: number;
  totalNoticeCount: number;
  nextCursor: string | null;
  error?: string;
}

const EMPTY_POSTS: PostsState = {
  list: [],
  total: 0,
  totalPage: 1,
  noticeCount: 0,
  totalNoticeCount: 0,
  nextCursor: null,
};

function toPage(value: string | null): number {
  const parsed = Number.parseInt(value || "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export default function BoardPostListClient({ boTable, embedded = false, currentWrId }: ClientPageProps) {
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
        getBoardPosts({
          boTable: bo_table,
          page,
          perPage,
          sfl,
          stx,
          sca,
          withExcerpt: isGalleryBoard(nextBoard),
        }),
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

  // 분류 칩의 글 수. 목록을 막지 않게 따로 부르고, 서버가 세지 않으면(끔 · 큰 게시판) 숫자 없이 둔다.
  // 쪽 · 분류 · 검색이 바뀌어도 숫자는 같으므로 게시판이 바뀔 때만 부른다.
  const [categoryCounts, setCategoryCounts] = useState<{ boTable: string; counts: Record<string, number> } | null>(null);
  const hasCategories = Boolean(board?.bo_category_list);
  useEffect(() => {
    if (!bo_table || !hasCategories) return;
    let alive = true;
    getBoardCategoryCounts(bo_table)
      .then((result) => {
        if (alive && result?.counts) setCategoryCounts({ boTable: bo_table, counts: result.counts });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [bo_table, hasCategories]);

  useEffect(() => {
    if (!board || !bo_table || embedded) return;

    applyClientPageMetadata({
      title: board.bo_subject,
      description: board.bo_content || `${board.bo_subject} 게시판`,
      path: `/boards/${bo_table}`,
    });
  }, [board, bo_table, embedded]);

  if (loading) {
    if (embedded) {
      return (
        <div className="board-list-page board-list-embedded mt-8" aria-busy="true">
          <div className="surface-panel space-y-3 p-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-12 animate-pulse rounded bg-muted" />
            ))}
          </div>
        </div>
      );
    }
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
    // 글 아래 목록은 글이 이미 게시판을 확인했으니, 여기서 또 "없음" 을 말하지 않는다.
    if (embedded) return null;
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
  const isGallery = isGalleryBoard(board);
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
  // 그누보드 bbs/rss.php 와 같은 조건: "RSS 보이기"를 켰고 비회원도 읽을 수 있는 게시판(읽기 레벨 1)만 RSS 를 낸다.
  const canViewRss = board.bo_use_rss_view > 0 && board.bo_read_level < 2;

  const list = (
    <div className={cn("board-list-page", embedded ? "board-list-embedded mt-8" : "site-container px-4 py-8")}>
      {embedded ? null : (
        <Breadcrumb items={[{ label: "게시판", href: g5ShortHref("/boards") }, { label: board.bo_subject }]} />
      )}

      {embedded ? null : (
        <section className="board-list-hero page-hero mb-5">
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
            <div>
              <p className="section-eyebrow">커뮤니티 게시판</p>
              <h1 className="page-hero-title">{board.bo_subject}</h1>
              <p className="page-hero-desc">
                {board.bo_content || `총 ${totalCount.toLocaleString("ko-KR")}개의 게시글을 확인하세요.`}
              </p>
            </div>
            <div className="board-list-actions flex items-center gap-2">
              {canWrite && (
                <Button className="board-list-write" asChild>
                  <a href={g5ShortHref(`/boards/${bo_table}/write`)}>글쓰기</a>
                </Button>
              )}
            </div>
          </div>
        </section>
      )}

      {/* 글 수 · 쪽수와 RSS. 그누보드 list.skin 의 안내줄 — 테마는 이것을 제목 아래 한 줄로 쓴다. */}
      <div className="board-list-summary mb-3 flex items-center justify-between gap-3 text-sm text-muted-foreground">
        <p className="board-list-summary-text">
          <b className="text-foreground">{totalCount.toLocaleString("ko-KR")}</b> 개의 글 · {page}페이지
        </p>
        {canViewRss && (
          <a
            /* 새 창으로 여는 피드 주소라 앱 안 이동이 아닌 <a> — 설치 경로(하위 폴더)는 직접 붙인다. */
            href={g5PathForRuntime(`/rss/${bo_table}`)}
            target="_blank"
            rel="noopener noreferrer"
            title="RSS feed"
            aria-label="RSS 피드"
            className="board-list-rss inline-flex h-8 w-8 items-center justify-center rounded-[4px] border text-[#b45309] transition-colors hover:bg-[#fff7e6]"
          >
            <RssIcon className="h-4 w-4" />
          </a>
        )}
      </div>

      {categories.length > 0 && (
        <div className="board-list-categories surface-toolbar mb-5">
          <a href={g5ShortHref(`/boards/${bo_table}`)} className={cn("filter-chip", !sca && "filter-chip-active")}>
            전체
            {/* 게시판 전체 글 수(그누보드가 늘 맞춰 두는 bo_count_write) — 분류 · 검색을 고른 동안에도 같다. */}
            <span className="filter-chip-count">{Number(board.bo_count_write || 0).toLocaleString("ko-KR")}</span>
          </a>
          {categories.map((category) => {
            const count = categoryCounts?.boTable === bo_table ? categoryCounts.counts[category] : undefined;
            return (
              <a
                key={category}
                href={g5ShortHref(`/boards/${bo_table}?sca=${encodeURIComponent(category)}`)}
                className={cn("filter-chip", sca === category && "filter-chip-active")}
              >
                {category}
                {typeof count === "number" && (
                  <span className="filter-chip-count">{count.toLocaleString("ko-KR")}</span>
                )}
              </a>
            );
          })}
        </div>
      )}

      {/* 검색은 마크업에서 목록 앞에 두고(키보드 순서), 테마 CSS 가 카드 아래 가운데로 옮긴다. */}
      <div className="board-list-search surface-panel mb-5 p-4">
        <SearchForm boTable={bo_table} sfl={sfl} stx={stx} sca={sca} />
      </div>

      {postsError && (
        <ErrorState
          title="게시글을 불러오지 못했습니다"
          description={postsError}
          onAction={() => setLoadAttempt((attempt) => attempt + 1)}
        />
      )}

      {!postsError && isGallery ? (
        posts.length > 0 ? (
          <GalleryPostGrid
            boTable={bo_table}
            notices={notices}
            posts={regularPosts}
            cols={galleryCols}
            isAdmin={canManageBoard}
            bbsRewriteMode={bbsRewriteMode}
            listQuery={listQuery}
            boNew={board.bo_new ?? 0}
            boHot={board.bo_hot ?? 0}
            currentWrId={currentWrId}
          />
        ) : (
          <EmptyState title="아직 등록된 게시글이 없습니다" />
        )
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
          initialCursor={postsData.nextCursor}
          boNew={board.bo_new ?? 0}
          boHot={board.bo_hot ?? 0}
          currentWrId={currentWrId}
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
          boNew={board.bo_new ?? 0}
          boHot={board.bo_hot ?? 0}
          currentWrId={currentWrId}
        />
      ) : null}

      {totalPage > 1 && !infiniteScroll && (
        <div className="board-list-pagination mt-6 flex justify-center">
          <Pagination
            currentPage={page}
            totalPages={totalPage}
            baseUrl={g5ShortHref(`/boards/${bo_table}`)}
            searchParams={paginationSearchParams}
          />
        </div>
      )}
    </div>
  );

  // 오른쪽 레일은 레이아웃(CommunityInnerShell)이 붙인다.
  return list;
}
