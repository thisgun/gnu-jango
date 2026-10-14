"use client";

import { createElement, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Image from "next/image";
import type { Board, PostFile } from "@/lib/types";
import type { PostDetail } from "@/services/boards";
import {
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
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/ErrorState";
import { Separator } from "@/components/ui/separator";
import { ShareButtons } from "@/components/ShareButtons";
import { MemberAvatar } from "@/components/MemberAvatar";
import { MemberSideview } from "@/components/MemberSideview";
import { useThemeFeature, useThemeSlot } from "@/components/providers/ThemeSlotsProvider";
import { ChevronDown, ChevronUp, FileQuestion, Link2, MessageCircle } from "lucide-react";
import { CommentSection } from "./CommentSection";
import { downloadAttachment, isCheckedDownloadUrl } from "./downloadAttachment";
import { MarkVisited } from "./MarkVisited";
import { PostActions } from "./PostActions";
import { g5ShortHref } from "@/lib/g5-short-url";
import { boardListHref, boardPostHref, boardPostPath, isBbsSeoRewrite } from "@/lib/board-url";
import { toastError, toastSuccess } from "@/lib/toast";
import { useAuthStore } from "@/store/auth";
import BoardPostListClient from "../ClientPage";

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
  // 테마가 글보기 머리를 바꾸면(문서 테마 등) 그 슬롯이, 없으면 아래 기본 머리가 그려진다.
  const themeBoardViewHeader = useThemeSlot("BoardViewHeader");
  const listUnderPostView = useThemeFeature("listUnderPostView");
  const routePatterns = ["/bbs/:bo_table/:wr_id", "/boards/:bo_table/:wr_id", "/:bo_table/:wr_id"];
  const bo_table = useRuntimeRouteParam("bo_table", routePatterns, boTable);
  const wr_id = useRuntimeRouteParam("wr_id", routePatterns, wrId);
  const searchParams = useSearchParams();
  const listParams = new URLSearchParams();
  for (const key of ["page", "sfl", "stx", "sca"]) {
    const value = searchParams.get(key);
    if (value) listParams.set(key, value);
  }
  const listHref = bo_table ? boardListHref(bo_table, listParams.toString()) : g5ShortHref("/boards");
  const [post, setPost] = useState<PostDetail | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
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
  const safeLink1 = safePostLink(post.wr_link1);
  const safeLink2 = safePostLink(post.wr_link2);

  // 원본이 있는 그림 첨부는 본문 위에 그대로 보이고(그누보드 view.skin), 나머지는 첨부 목록에 둔다.
  const inlineImages = files.filter(
    (file) => isImageFile(file) && file.bf_download_available !== false && Boolean(file.bf_url)
  );
  const listedFiles = files.filter((file) => !inlineImages.includes(file));

  return (
    // 오른쪽 레일은 레이아웃(CommunityInnerShell)이 붙인다.
    <div className="board-view-page container mx-auto px-4 py-8">
      <MarkVisited boTable={bo_table} wrId={actualWrId} />
      <Breadcrumb
        items={[
          { label: boardName, href: g5ShortHref(`/boards/${bo_table}`) },
          { label: post.wr_subject },
        ]}
      />

      <Card className="board-view-card">
        {themeBoardViewHeader ? (
          createElement(themeBoardViewHeader, {
            post,
            boTable: bo_table,
            boardName,
            listHref,
            author: (
              <MemberSideview
                mbId={post.mb_id}
                name={authorName}
                email={post.wr_email}
                homepage={post.wr_homepage}
                boTable={bo_table}
                className="font-medium text-foreground"
              >
                <span>{authorName}</span>
              </MemberSideview>
            ),
            actions: <PostActions boTable={bo_table} wrId={actualWrId} post={post} />,
            share: <ShareButtons title={post.wr_subject} />,
          })
        ) : (
          <>
            {/* 레퍼런스 #bo_v 의 머리(테마 BoardViewHeader): 카드 위 줄의 게시판 이름 · 목록, 분류 칩 · 글 번호, 큰 제목,
                작성자 바(아바타 · 이름 · 시각 | 조회 · 댓글 · 공유 · 글 동작). */}
            <div className="solune-view-boardbar">
              <a href={listHref} className="solune-view-boardname">{boardName}</a>
              <a href={listHref} className="solune-view-listbtn">목록</a>
            </div>
            <header className="solune-view-head">
              <div className="solune-view-kicker-row">
                {post.ca_name ? <span className="solune-view-cate">{post.ca_name}</span> : null}
                <span className="solune-view-kicker">#{actualWrId}</span>
              </div>
              <h1 className="solune-view-title">{post.wr_subject}</h1>
            </header>
            <div className="solune-view-info">
              <div className="solune-view-author">
                <MemberAvatar name={authorName} member={post} className="solune-avatar solune-view-avatar" size={40} />
                <div className="solune-view-author-body">
                  <strong>
                    <MemberSideview
                      mbId={post.mb_id}
                      name={authorName}
                      email={post.wr_email}
                      homepage={post.wr_homepage}
                      boTable={bo_table}
                      className="font-medium text-foreground"
                    >
                      <span>{authorName}</span>
                    </MemberSideview>
                  </strong>
                  <time dateTime={post.wr_datetime}>{formatPostDate(post.wr_datetime)}</time>
                </div>
              </div>
              <div className="solune-view-tools">
                <span className="solune-view-stat">
                  조회 <b>{formatNumber(Number(post.wr_hit))}</b>
                </span>
                <span className="solune-view-stat">
                  댓글 <b>{formatNumber(Number(post.wr_comment ?? 0))}</b>
                </span>
                <ShareButtons title={post.wr_subject} />
                <PostActions boTable={bo_table} wrId={actualWrId} post={post} />
              </div>
            </div>

          </>
        )}

        <Separator />

        {inlineImages.length > 0 && (
          <>
            <CardContent className="space-y-4 py-4">
              {inlineImages.map((file) => {
                const src = file.bf_url || "";
                const width = Number(file.bf_width) || 0;
                const height = Number(file.bf_height) || 0;
                const knownSize = width > 0 && height > 0;
                return (
                  <div key={file.bf_no}>
                    {/* 원래 크기로 두고 본문보다 클 때만 줄인다. 링크는 그림 크기만큼만(inline-block)이라 옆 빈 곳은 눌리지 않는다. */}
                    <a href={src} target="_blank" rel="noopener noreferrer" className="view_image inline-block max-w-full align-top">
                      <Image
                        src={src}
                        alt={file.bf_source}
                        width={knownSize ? width : 1200}
                        height={knownSize ? height : 800}
                        sizes={knownSize ? `(max-width: ${width}px) 100vw, ${width}px` : "100vw"}
                        className="board-view-attached-image h-auto max-w-full"
                        style={knownSize ? { maxWidth: "100%", height: "auto" } : { width: "auto", maxWidth: "100%", height: "auto" }}
                        unoptimized={shouldBypassImageOptimization(src)}
                      />
                    </a>
                  </div>
                );
              })}
            </CardContent>
            <Separator />
          </>
        )}

        <CardContent className="board-view-content py-6">
          <div
            className="prose prose-sm min-w-0 max-w-none break-words dark:prose-invert"
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(post.wr_content) }}
          />
        </CardContent>

        {listedFiles.length > 0 && (
          <>
            <Separator />
            <CardContent className="board-view-files py-4">
              <h3 className="mb-2 text-sm font-medium">첨부파일</h3>
              <ul className="space-y-2">
                {listedFiles.map((file) => {
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
                    <li key={file.bf_no} className="text-sm">
                      {downloadUrl ? (
                        <a
                          href={downloadUrl}
                          className="break-all text-primary hover:underline"
                          // A download keeps the reader on this page, so it must not start the navigation bar.
                          data-disable-progress="true"
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
                          <span className="break-all text-muted-foreground">{fileLabel}</span>
                          {file.bf_download_available === false && (
                            <span className="badge badge-warning badge-soft shrink-0">원본 파일 없음</span>
                          )}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </>
        )}

        {(safeLink1 || safeLink2) && (
          <>
            <Separator />
            <CardContent className="space-y-1 py-4">
              {safeLink1 && (
                <p className="text-sm">
                  <span className="mr-2 text-muted-foreground">링크 1:</span>
                  <a href={safeLink1} target="_blank" rel="noopener noreferrer" className="break-all text-primary hover:underline">
                    {safeLink1}
                  </a>
                </p>
              )}
              {safeLink2 && (
                <p className="text-sm">
                  <span className="mr-2 text-muted-foreground">링크 2:</span>
                  <a href={safeLink2} target="_blank" rel="noopener noreferrer" className="break-all text-primary hover:underline">
                    {safeLink2}
                  </a>
                </p>
              )}
            </CardContent>
          </>
        )}

        <Separator />

        <CardContent className="board-view-vote py-4">
          <div className="flex items-center justify-center gap-4">
            <PostActions boTable={bo_table} wrId={actualWrId} post={post} mode="vote" />
          </div>
        </CardContent>

        {/* 글 아래 도구줄 — 그누보드 view.skin 의 #bo_v_top/bot: 댓글 수 · 링크 복사 | 답글 · 글쓰기 · 목록으로 */}
        <div className="board-view-toolbar flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-sm">
          <div className="flex items-center gap-2">
            <a href="#comments" className="board-view-toolbar-btn inline-flex h-8 items-center gap-1.5 rounded-[4px] border px-3">
              <MessageCircle className="h-3.5 w-3.5" aria-hidden />
              댓글 {formatNumber(comments.length)}
            </a>
            <button
              type="button"
              onClick={() => void handleCopyPostLink()}
              className="board-view-toolbar-btn inline-flex h-8 items-center gap-1.5 rounded-[4px] border px-3"
            >
              <Link2 className="h-3.5 w-3.5" aria-hidden />
              링크 복사
            </button>
          </div>
          <div className="flex items-center gap-2">
            {canReply && (
              <Button asChild variant="outline" size="sm" className="board-view-toolbar-reply">
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
              <Button asChild variant="outline" size="sm" className="board-view-toolbar-write">
                <a href={g5ShortHref(`/boards/${bo_table}/write`)}>글쓰기</a>
              </Button>
            )}
            <Button asChild size="sm" className="board-view-toolbar-list">
              <a href={listHref}>목록으로</a>
            </Button>
          </div>
        </div>
      </Card>

      <div className="board-view-comments mt-6 scroll-mt-24" id="comments">
        <CommentSection
          boTable={bo_table}
          wrId={actualWrId}
          initialComments={comments}
          board={board}
          useEditor={commentEditorEnabled}
        />
      </div>

      {(post.prev_post || post.next_post) && (
        <div className="board-view-siblings mt-6 divide-y rounded-lg border bg-card text-sm">
          {post.next_post && (
            <a
              href={boardPostHref(bo_table, post.next_post, bbsRewriteMode)}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50"
            >
              <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="shrink-0 text-muted-foreground">다음글</span>
              <span className="truncate">{post.next_post.wr_subject}</span>
            </a>
          )}
          {post.prev_post && (
            <a
              href={boardPostHref(bo_table, post.prev_post, bbsRewriteMode)}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50"
            >
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="shrink-0 text-muted-foreground">이전글</span>
              <span className="truncate">{post.prev_post.wr_subject}</span>
            </a>
          )}
        </div>
      )}

      {canViewBoardList && listUnderPostView ? (
        <BoardPostListClient boTable={bo_table} embedded currentWrId={post.wr_id} />
      ) : null}
    </div>
  );
}
