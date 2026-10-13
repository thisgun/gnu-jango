"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Image from "next/image";
import type { Board, PostFile, WritePost } from "@/lib/types";
import type { PostDetail } from "@/services/boards";
import {
  getBoardPosts,
  getBoardResult,
  getPostDetailBySeoResult,
  getPostDetailResult,
} from "@/services/boards";
import { getClientPublicSettings } from "@/services/settings";
import {
  currentPathForRuntime,
  currentPathHasTrailingSlashForRuntime,
  g5PathForRuntime,
} from "@/lib/config";
import {
  applyClientJsonLd,
  applyClientPageMetadata,
  clientAbsoluteUrl,
  plainTextSummary,
} from "@/lib/client-metadata";
import { formatDate, formatNumber } from "@/lib/utils";
import { sanitizeHtml } from "@/lib/sanitize";
import { shouldBypassImageOptimization } from "@/lib/image";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState } from "@/components/ErrorState";
import { Separator } from "@/components/ui/separator";
import { Pagination } from "@/components/ui/pagination";
import { ShareButtons } from "@/components/ShareButtons";
import { MemberSideview } from "@/components/MemberSideview";
import { ChevronDown, ChevronUp, Copy, FileQuestion, LockKeyhole, MessageCircle } from "lucide-react";
import { CommentSection } from "./CommentSection";
import { downloadAttachment, isCheckedDownloadUrl } from "./downloadAttachment";
import { MarkVisited } from "./MarkVisited";
import { PostActions } from "./PostActions";
import { g5ShortHref } from "@/lib/g5-short-url";
import { boardListHref, boardPostHref, boardPostPath, isBbsSeoRewrite } from "@/lib/board-url";
import { CommunitySidebar } from "@/components/layout/CommunitySidebar";
import { toastError, toastSuccess } from "@/lib/toast";
import { useAuthStore } from "@/store/auth";
import { SearchForm } from "../SearchForm";

interface ClientPageProps {
  boTable?: string;
  wrId?: string;
}

function isImageFile(file: PostFile): boolean {
  return (
    file.bf_type === 2 ||
    file.bf_type === 3 ||
    /\.(jpg|jpeg|png|gif|webp|bmp|svg)$/i.test(file.bf_source)
  );
}

function safePostLink(value?: string | null): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || /[\u0000-\u001F\u007F]/.test(raw)) return "";

  let decoded = raw;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    decoded = raw;
  }
  decoded = decoded.trim();
  if (!decoded || decoded.startsWith("//")) return "";

  const scheme = decoded.match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase();
  if (scheme && !["http", "https", "mailto", "tel"].includes(scheme)) return "";

  return raw;
}

function formatPostDate(value?: string | null): string {
  if (!value) return "";
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const localValue = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T00:00:00+09:00`
    : value.replace(" ", "T");
  const date = new Date(hasTimezone ? value : `${localValue}+09:00`);
  if (Number.isNaN(date.getTime())) return formatDate(value);

  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

export default function PostViewClient({ boTable, wrId }: ClientPageProps) {
  const routePatterns = ["/bbs/:bo_table/:wr_id", "/boards/:bo_table/:wr_id", "/:bo_table/:wr_id"];
  const bo_table = useRuntimeRouteParam("bo_table", routePatterns, boTable);
  const wr_id = useRuntimeRouteParam("wr_id", routePatterns, wrId);
  const searchParams = useSearchParams();
  const listPage = Math.max(Number.parseInt(searchParams.get("page") || "1", 10) || 1, 1);
  const listSfl = searchParams.get("sfl") || undefined;
  const listStx = searchParams.get("stx") || undefined;
  const listSca = searchParams.get("sca") || undefined;
  const listParams = new URLSearchParams();
  for (const key of ["page", "sfl", "stx", "sca"]) {
    const value = searchParams.get(key);
    if (value) listParams.set(key, value);
  }
  const listHref = bo_table ? boardListHref(bo_table, listParams.toString()) : g5ShortHref("/boards");
  const [post, setPost] = useState<PostDetail | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [boardList, setBoardList] = useState<{
    list: WritePost[];
    total: number;
    totalPage: number;
    noticeCount: number;
    totalNoticeCount: number;
    error?: string;
  } | null>(null);
  const listPostId = post?.wr_id;
  const [boardName, setBoardName] = useState("");
  const [bbsRewriteMode, setBbsRewriteMode] = useState(0);
  const [commentEditorEnabled, setCommentEditorEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const { user } = useAuthStore();
  const handleCopyPostLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toastSuccess("게시글 링크를 복사했습니다.");
    } catch {
      toastError("링크 복사에 실패했습니다. 브라우저 주소를 직접 복사해 주세요.");
    }
  };
  useEffect(() => {
    if (!bo_table || !wr_id) {
      setPost(null);
      setBoard(null);
      setBoardName(bo_table || "");
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
      const runtimePath = currentPathForRuntime();
      const legacySeoPath =
        (!/^[0-9]+$/.test(wr_id) || currentPathHasTrailingSlashForRuntime()) &&
        new RegExp(`^/${bo_table.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/[^/]+$`).test(runtimePath);

      if (legacySeoPath) {
        const [seoPostResult, boardResult, settings] = await Promise.all([
          getPostDetailBySeoResult({ boTable: bo_table, slug: wr_id }),
          getBoardResult(bo_table, 60),
          getClientPublicSettings().catch(() => null),
        ]);

        if (!alive) return;
        if (!boardResult.ok) {
          setPost(null);
          setBoard(null);
          setBoardName(bo_table);
          if (boardResult.status === 404) setMissing(true);
          else setLoadError(boardResult.error);
          setLoading(false);
          return;
        }

        const nextBoard = boardResult.data;
        const nextRewriteMode = Number(settings?.cf_bbs_rewrite ?? 0);
        setBbsRewriteMode(nextRewriteMode);
        setBoard(nextBoard);
        setBoardName(nextBoard?.bo_subject ?? bo_table);
        setCommentEditorEnabled(!!settings?.comment_editor);

        if (!seoPostResult.ok) {
          setPost(null);
          if (seoPostResult.status === 404) setMissing(true);
          else setLoadError(seoPostResult.error);
          setLoading(false);
          return;
        }

        const seoPost = seoPostResult.data;
        if (seoPost.wr_id) {
          if (isBbsSeoRewrite(nextRewriteMode)) {
            setPost(seoPost);
            setMissing(false);
            setLoading(false);
            return;
          }

          window.location.replace(g5PathForRuntime(`/${bo_table}/${seoPost.wr_id}`));
          return;
        }

        setPost(null);
        setMissing(true);
        setLoading(false);
        return;
      }

      const [postResult, boardResult, settings] = await Promise.all([
        getPostDetailResult({ boTable: bo_table, wrId: wr_id }),
        getBoardResult(bo_table, 60),
        getClientPublicSettings().catch(() => null),
      ]);

      if (!alive) return;
      if (!boardResult.ok) {
        setPost(null);
        setBoard(null);
        setBoardName(bo_table);
        if (boardResult.status === 404) setMissing(true);
        else setLoadError(boardResult.error);
        setLoading(false);
        return;
      }

      if (!postResult.ok) {
        setPost(null);
        setBoard(boardResult.data);
        setBoardName(boardResult.data.bo_subject || bo_table);
        if (postResult.status === 404) setMissing(true);
        else setLoadError(postResult.error);
        setLoading(false);
        return;
      }

      setPost(postResult.data);
      setBoard(boardResult.data);
      setBbsRewriteMode(Number(settings?.cf_bbs_rewrite ?? 0));
      setBoardName(boardResult.data.bo_subject ?? bo_table);
      setCommentEditorEnabled(!!settings?.comment_editor);
      setMissing(false);
      setLoading(false);
    }

    load().catch((error: unknown) => {
      if (!alive) return;
      setPost(null);
      setBoard(null);
      setBoardName(bo_table);
      setMissing(false);
      setLoadError(error instanceof Error ? error.message : "Failed to load post.");
      setLoading(false);
    });

    return () => {
      alive = false;
    };
  }, [bo_table, loadAttempt, wr_id]);

  useEffect(() => {
    if (!bo_table || !board || !listPostId) {
      setBoardList(null);
      return;
    }

    let alive = true;
    setBoardList(null);
    getBoardPosts({
      boTable: bo_table,
      page: listPage,
      perPage: board.bo_page_rows || 15,
      sfl: listSfl,
      stx: listStx,
      sca: listSca,
    })
      .then((result) => {
        if (!alive) return;
        setBoardList(result);
      })
      .catch(() => {
        if (alive) {
          setBoardList({
            list: [],
            total: 0,
            totalPage: 1,
            noticeCount: 0,
            totalNoticeCount: 0,
            error: "Unable to load board posts.",
          });
        }
      });

    return () => {
      alive = false;
    };
  }, [board, bo_table, listPage, listPostId, listSca, listSfl, listStx]);

  useEffect(() => {
    if (!post || !bo_table) return;

    const image = post.files?.find(isImageFile)?.bf_url;
    const postPath = boardPostPath(bo_table, post, bbsRewriteMode);
    const canonical = new URL(g5ShortHref(postPath), window.location.origin).toString();
    const imageUrl = image ? clientAbsoluteUrl(image) : undefined;
    applyClientPageMetadata({
      title: post.wr_subject,
      description: post.wr_content,
      path: postPath,
      image,
    });
    applyClientJsonLd("product", null);
    applyClientJsonLd("article", {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: post.wr_subject,
      description: plainTextSummary(post.wr_content, post.wr_subject),
      articleSection: boardName || bo_table,
      author: {
        "@type": "Person",
        name: post.mb_nick || post.wr_name || "익명",
      },
      datePublished: post.wr_datetime,
      dateModified: post.wr_last || post.wr_datetime,
      mainEntityOfPage: {
        "@type": "WebPage",
        "@id": canonical,
      },
      url: canonical,
      ...(imageUrl ? { image: [imageUrl] } : {}),
    });
    applyClientJsonLd("breadcrumb", {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: boardName || bo_table,
          item: new URL(g5ShortHref(`/boards/${bo_table}`), window.location.origin).toString(),
        },
        {
          "@type": "ListItem",
          position: 2,
          name: post.wr_subject,
          item: canonical,
        },
      ],
    });
  }, [post, bo_table, boardName, bbsRewriteMode]);

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="mb-4 h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="space-y-4 rounded-lg border p-6">
          <div className="h-8 w-3/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
          <div className="h-40 animate-pulse rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="container mx-auto px-4 py-20">
        <ErrorState
          title="게시글 정보를 불러오지 못했습니다."
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

  if (missing || !post) {
    return (
      <div className="container mx-auto px-4 py-20">
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-muted">
            <FileQuestion className="size-7 text-muted-foreground" />
          </div>
          <div className="space-y-1">
            <h1 className="text-xl font-bold text-foreground">게시글을 찾을 수 없습니다</h1>
            <p className="text-sm text-muted-foreground">
              삭제되었거나 이동된 글일 수 있습니다.
            </p>
          </div>
          <Button asChild>
            <a href={listHref}>목록으로 돌아가기</a>
          </Button>
        </div>
      </div>
    );
  }

  const comments = post.comments ?? [];
  const files = post.files ?? [];
  const actualWrId = String(post.wr_id);
  const canReply = Boolean(
    board &&
      !post.is_notice &&
      ((user?.mb_level ?? 1) >= board.bo_reply_level ||
        user?.is_super_admin ||
        user?.mb_id === board.bo_admin ||
        user?.mb_id === board.gr_admin)
  );
  const canWrite = Boolean(
    board &&
      ((user?.mb_level ?? 1) >= board.bo_write_level ||
        user?.is_super_admin ||
        user?.mb_id === board.bo_admin ||
        user?.mb_id === board.gr_admin)
  );
  const authorName = post.mb_nick || post.wr_name || "익명";
  const canViewBoardList = Boolean(
    board &&
      ((user?.mb_level ?? 1) >= board.bo_list_level ||
        user?.is_super_admin ||
        user?.mb_id === board.bo_admin ||
        user?.mb_id === board.gr_admin)
  );
  const listPerPage = board?.bo_page_rows || 15;
  const listNotices = boardList?.list.filter((item) => item.is_notice) ?? [];
  const listRegularPosts = boardList?.list.filter((item) => !item.is_notice) ?? [];
  const listNumberStart =
    (boardList?.total ?? 0) - (listPage - 1) * listPerPage - (boardList?.totalNoticeCount ?? 0);
  const boardCategories = board?.bo_category_list.split("|").filter(Boolean) ?? [];
  const listPaginationParams = { sfl: listSfl, stx: listStx, sca: listSca };
  const safeLink1 = safePostLink(post.wr_link1);
  const safeLink2 = safePostLink(post.wr_link2);

  return (
    <div className="site-container solune-post-detail-shell pb-20 md:pb-12">
      <div className="solune-content-shell">
        <main className="solune-main-content">
      <MarkVisited boTable={bo_table} wrId={actualWrId} />
      <Breadcrumb
        items={[
          { label: boardName, href: g5ShortHref(`/boards/${bo_table}`) },
          { label: post.wr_subject },
        ]}
      />

      <div className="solune-post-page-title flex items-center justify-between gap-4">
        <h2 className="text-2xl font-bold leading-tight">{boardName}</h2>
        <Button asChild variant="outline" size="sm">
          <a href={listHref}>목록</a>
        </Button>
      </div>

      <Card className="min-w-0 solune-reference-panel solune-post-detail-card">
        <CardHeader className="gap-0 space-y-0 px-5 pt-7 pb-0 md:px-8 md:pt-8">
          <div className="flex items-center gap-2 text-sm">
            {post.ca_name && <Badge variant="secondary">{post.ca_name}</Badge>}
            <span className="text-muted-foreground">#{actualWrId}</span>
          </div>
          <div className="mt-[18px] flex min-w-0 flex-col gap-4 md:mt-5">
            <h1 className="min-w-0 break-words text-2xl font-bold leading-tight">{post.wr_subject}</h1>
          </div>
          <Separator className="mt-[26px] mb-9 md:mt-[38px]" />
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4 text-sm text-muted-foreground">
            <div className="flex min-w-0 items-center gap-3">
              <div className="avatar avatar-placeholder shrink-0">
                <div className="size-10 rounded-full bg-base-200 text-base-content">
                  {post.mb_icon_path ? (
                    <Image
                      src={post.mb_icon_path}
                      alt=""
                      width={40}
                      height={40}
                      className="size-10 rounded-full object-cover"
                      unoptimized={shouldBypassImageOptimization(post.mb_icon_path)}
                    />
                  ) : (
                    <span className="text-sm font-semibold">{authorName.slice(0, 1)}</span>
                  )}
                </div>
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <MemberSideview
                  mbId={post.mb_id}
                  name={authorName}
                  email={post.wr_email}
                  homepage={post.wr_homepage}
                  boTable={bo_table}
                  className="font-medium text-foreground"
                />
                <time dateTime={post.wr_datetime} className="text-xs">
                  {formatPostDate(post.wr_datetime)}
                </time>
              </div>
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
              <span>조회 {formatNumber(Number(post.wr_hit))}</span>
              <a href="#comments" className="hover:text-primary">
                댓글 {formatNumber(Number(post.wr_comment))}
              </a>
              <ShareButtons title={post.wr_subject} />
              <PostActions boTable={bo_table} wrId={actualWrId} post={post} />
            </div>
          </div>
        </CardHeader>

        <CardContent className="px-5 pt-9 pb-7 md:px-8 md:pt-10 md:pb-6">
          <div
            className="prose prose-sm min-w-0 max-w-none break-words dark:prose-invert"
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(post.wr_content) }}
          />
        </CardContent>

        {files.length > 0 && (
          <section className="border-t border-base-300">
            <h3 className="border-b border-base-300 bg-base-200/50 px-5 py-4 text-sm font-semibold md:px-8">
              첨부파일
            </h3>
            <ul className="divide-y divide-base-300 px-5 md:px-8">
              {files.map((file) => {
                const downloadUrl =
                  file.bf_download_available === false
                    ? ""
                    : file.bf_download_url || file.bf_url || file.bf_fileurl;
                const fileLabel = (
                  <>
                    {file.bf_source}
                    {file.bf_filesize > 0 && (
                      <span className="ml-1 text-muted-foreground">
                        ({(file.bf_filesize / 1024).toFixed(1)}KB)
                      </span>
                    )}
                  </>
                );

                return (
                  <li key={file.bf_no} className="py-[13px] text-sm">
                    {downloadUrl ? (
                      <a
                        href={downloadUrl}
                        className="break-all text-primary hover:underline"
                        onClick={(event) => {
                          if (!isCheckedDownloadUrl(downloadUrl)) return;
                          event.preventDefault();
                          void downloadAttachment(
                            downloadUrl,
                            file.bf_source,
                            Number(board?.bo_download_point ?? 0)
                          );
                        }}
                      >
                        {fileLabel}
                      </a>
                    ) : (
                      <span className="inline-flex flex-wrap items-center gap-2">
                        <span className="break-all text-base-content/70">{fileLabel}</span>
                        {file.bf_download_available === false && (
                          <span className="badge badge-warning badge-soft shrink-0">
                            원본 파일 없음
                          </span>
                        )}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {(safeLink1 || safeLink2) && (
          <>
            <Separator />
            <CardContent className="space-y-1 py-4">
              {safeLink1 && (
                <p className="text-sm">
                  <span className="mr-2 text-muted-foreground">링크 1:</span>
                  <a
                    href={safeLink1}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-primary hover:underline"
                  >
                    {safeLink1}
                  </a>
                </p>
              )}
              {safeLink2 && (
                <p className="text-sm">
                  <span className="mr-2 text-muted-foreground">링크 2:</span>
                  <a
                    href={safeLink2}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-primary hover:underline"
                  >
                    {safeLink2}
                  </a>
                </p>
              )}
            </CardContent>
          </>
        )}

        <Separator />

        <CardContent className="py-4 md:py-[18px]">
          <div className="flex items-center justify-center gap-4">
            <PostActions boTable={bo_table} wrId={actualWrId} post={post} mode="vote" />
          </div>
        </CardContent>

        <div className="flex flex-col gap-3 border-t border-base-300 bg-base-200/50 px-5 py-[18px] sm:flex-row sm:items-center sm:justify-between md:px-8">
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <a href="#comments">
                <MessageCircle className="size-4" />
                댓글 {formatNumber(comments.length)}
              </a>
            </Button>
            <Button variant="outline" size="sm" onClick={handleCopyPostLink}>
              <Copy className="size-4" />
              링크 복사
            </Button>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {canReply && (
              <Button asChild variant="outline" size="sm">
                <a
                  href={g5ShortHref(
                    `/boards/${bo_table}/write?w=r&parent_id=${encodeURIComponent(actualWrId)}&subject=${encodeURIComponent(post.wr_subject)}${post.ca_name ? `&ca_name=${encodeURIComponent(post.ca_name)}` : ""}`
                  )}
                >
                  답글
                </a>
              </Button>
            )}
            {canWrite && (
              <Button asChild variant="outline" size="sm">
                <a href={g5ShortHref(`/boards/${bo_table}/write`)}>글쓰기</a>
              </Button>
            )}
            <Button asChild size="sm">
              <a href={listHref}>목록으로</a>
            </Button>
          </div>
        </div>
      </Card>

      <div id="comments" className="mt-6 scroll-mt-24">
        <CommentSection
          boTable={bo_table}
          wrId={actualWrId}
          initialComments={comments}
          board={board}
          useEditor={commentEditorEnabled}
        />
      </div>

      {(post.prev_post || post.next_post) && (
        <div className="mt-6 divide-y rounded-lg border bg-card text-sm">
          {post.next_post && (
            <a
              href={boardPostHref(bo_table, post.next_post, bbsRewriteMode)}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50"
            >
              <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="shrink-0 text-muted-foreground">다음 글</span>
              <span className="truncate">{post.next_post.wr_subject}</span>
            </a>
          )}
          {post.prev_post && (
            <a
              href={boardPostHref(bo_table, post.prev_post, bbsRewriteMode)}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50"
            >
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="shrink-0 text-muted-foreground">이전 글</span>
              <span className="truncate">{post.prev_post.wr_subject}</span>
            </a>
          )}
        </div>
      )}

      {canViewBoardList && (
        <section className="mt-6 overflow-hidden rounded-box border border-base-300 bg-base-100" aria-labelledby="related-board-posts-title">
          <header className="flex items-center justify-between gap-3 border-b border-base-300 px-4 py-3">
            <h2 id="related-board-posts-title" className="font-bold text-base-content">이 게시판의 글</h2>
            <a href={g5ShortHref(`/boards/${bo_table}`)} className="link link-hover text-sm text-primary">전체 목록</a>
          </header>
          {boardCategories.length > 0 && (
            <nav className="flex flex-wrap gap-2 border-b border-base-300 px-4 py-3" aria-label="게시판 분류">
              {["전체", ...boardCategories].map((category, index) => {
                const categoryParams = new URLSearchParams(listParams.toString());
                categoryParams.delete("page");
                if (index === 0) categoryParams.delete("sca");
                else categoryParams.set("sca", category);
                const query = categoryParams.toString();
                const active = index === 0 ? !listSca : listSca === category;
                return (
                  <a
                    key={category}
                    href={g5ShortHref(`/boards/${bo_table}${query ? `?${query}` : ""}`)}
                    className={`badge badge-sm ${active ? "badge-primary" : "badge-outline"}`}
                  >
                    {category}{index === 0 ? ` ${boardList?.total ?? board?.bo_count_write ?? 0}` : ""}
                  </a>
                );
              })}
            </nav>
          )}
          {boardList === null ? (
            <div className="flex justify-center py-8"><span className="loading loading-spinner loading-sm text-primary" aria-label="목록 불러오는 중" /></div>
          ) : boardList.error ? (
            <p role="alert" className="px-4 py-6 text-sm text-base-content/65">{boardList.error}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="table table-sm w-full table-fixed">
                  <colgroup>
                    <col className="w-12 md:w-16" />
                    <col />
                    <col className="hidden md:table-column md:w-32" />
                    <col className="hidden md:table-column md:w-20" />
                    <col className="hidden md:table-column md:w-28" />
                  </colgroup>
                  <thead className="hidden md:table-header-group">
                    <tr>
                      <th className="hidden w-16 text-left md:table-cell">번호</th>
                      <th>제목</th>
                      <th className="hidden md:table-cell">글쓴이</th>
                      <th className="hidden w-20 text-center md:table-cell">조회</th>
                      <th className="hidden w-28 text-center md:table-cell">날짜</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listNotices.map((item) => (
                      <tr key={`notice-${item.wr_id}`} className="bg-primary/5 hover:bg-primary/10">
                        <td className="text-center"><span className="badge badge-sm badge-primary">공지</span></td>
                        <td>
                          <a href={boardPostHref(bo_table, item, bbsRewriteMode, listParams.toString())} className="flex min-w-0 items-center gap-2 font-medium hover:text-primary">
                            {item.ca_name && <span className="badge badge-sm badge-secondary">{item.ca_name}</span>}
                            {item.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-base-content/60" aria-label="비밀글" />}
                            <span className="min-w-0 flex-1 truncate">{item.wr_subject}</span>
                            {item.wr_comment > 0 && <span className="badge badge-sm badge-ghost">{item.wr_comment}</span>}
                          </a>
                          <div className="mt-1 flex items-center gap-2 text-xs text-base-content/60 md:hidden">
                            <span className="truncate">{item.mb_nick || item.wr_name}</span>
                            <time dateTime={item.wr_datetime}>{formatDate(item.wr_datetime)}</time>
                          </div>
                        </td>
                        <td className="hidden md:table-cell">
                          <MemberSideview mbId={item.mb_id} name={item.mb_nick || item.wr_name} email={item.wr_email} homepage={item.wr_homepage} iconUrl={item.mb_icon_path} boTable={bo_table} />
                        </td>
                        <td className="hidden text-center text-base-content/60 md:table-cell">{formatNumber(item.wr_hit)}</td>
                        <td className="hidden whitespace-nowrap text-center text-base-content/60 md:table-cell">{formatDate(item.wr_datetime)}</td>
                      </tr>
                    ))}
                    {listRegularPosts.map((item, index) => (
                      <tr key={item.wr_id} className="hover:bg-base-200/50">
                        <td className="text-center text-base-content/60">{listNumberStart - index}</td>
                        <td>
                          <a href={boardPostHref(bo_table, item, bbsRewriteMode, listParams.toString())} className="flex min-w-0 items-center gap-2 hover:text-primary">
                            {item.ca_name && <span className="badge badge-sm badge-secondary">{item.ca_name}</span>}
                            {item.is_secret && <LockKeyhole className="size-3.5 shrink-0 text-base-content/60" aria-label="비밀글" />}
                            <span className="min-w-0 flex-1 truncate">{item.wr_subject}</span>
                            {item.wr_comment > 0 && <span className="badge badge-sm badge-ghost">{item.wr_comment}</span>}
                          </a>
                          <div className="mt-1 flex items-center gap-2 text-xs text-base-content/60 md:hidden">
                            <span className="truncate">{item.mb_nick || item.wr_name}</span>
                            <time dateTime={item.wr_datetime}>{formatDate(item.wr_datetime)}</time>
                          </div>
                        </td>
                        <td className="hidden md:table-cell">
                          <MemberSideview mbId={item.mb_id} name={item.mb_nick || item.wr_name} email={item.wr_email} homepage={item.wr_homepage} iconUrl={item.mb_icon_path} boTable={bo_table} />
                        </td>
                        <td className="hidden text-center text-base-content/60 md:table-cell">{formatNumber(item.wr_hit)}</td>
                        <td className="hidden whitespace-nowrap text-center text-base-content/60 md:table-cell">{formatDate(item.wr_datetime)}</td>
                      </tr>
                    ))}
                    {boardList.list.length === 0 && (
                      <tr><td colSpan={5} className="py-10 text-center text-base-content/60">게시글이 없습니다.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {boardList.totalPage > 1 && (
                <div className="border-t border-base-300 px-3 py-4">
                  <Pagination
                    currentPage={listPage}
                    totalPages={boardList.totalPage}
                    baseUrl={g5ShortHref(`/boards/${bo_table}`)}
                    searchParams={listPaginationParams}
                  />
                </div>
              )}
              <div className="border-t border-base-300 p-4">
                <SearchForm boTable={bo_table} sfl={listSfl} stx={listStx} sca={listSca} />
              </div>
            </>
          )}
        </section>
      )}

        </main>
        <CommunitySidebar rewriteMode={bbsRewriteMode} />
      </div>
    </div>
  );
}
