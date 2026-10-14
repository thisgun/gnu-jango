"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  memo,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useRouter } from "@bprogress/next/app";
import dynamic from "next/dynamic";
import { apiClient } from "@/lib/api";
import { apiUrl } from "@/lib/config";
import { useAuthStore } from "@/store/auth";
import type { Board, Comment } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatDate } from "@/lib/utils";
import { toastError } from "@/lib/toast";
import { MemberAvatar } from "@/components/MemberAvatar";
import { MemberSideview } from "@/components/MemberSideview";
import { htmlToPlainText, sanitizeUserHtml } from "@/lib/sanitize";
import { MoreVertical, RefreshCw } from "lucide-react";

const CommentEditor = dynamic(
  () => import("@/components/editor/CommentEditor").then((mod) => ({ default: mod.CommentEditor })),
  {
    ssr: false,
    loading: () => <div className="min-h-[80px] border rounded-lg animate-pulse bg-muted/30" />,
  }
);

interface CommentSectionProps {
  boTable: string;
  wrId: string;
  initialComments: Comment[];
  board: Board | null;
  useEditor?: boolean;
}

interface CommentItemProps {
  comment: Comment;
  boTable: string;
  onReply: (commentId: number) => void;
  replyTo: number | null;
  onCommentSubmit: (content: string, parentId?: number) => Promise<void>;
  onDelete: (commentId: number) => void;
  canReply: boolean;
  canDeleteAsAdmin: boolean;
  useEditor?: boolean;
  /** 답글이면 받는 댓글의 이름("○○ 님에게"). 받는 댓글이 지워졌으면 없다. */
  replyToName?: string;
}

interface CommentAction {
  key: string;
  label: string;
  onSelect: () => void;
  destructive?: boolean;
}

/** 마우스가 메뉴 단추와 메뉴 사이 틈을 지나는 동안 닫지 않고 기다리는 시간(ms). */
const MENU_HOVER_CLOSE_MS = 160;

function isContentEmpty(content: string): boolean {
  return !htmlToPlainText(content);
}

/**
 * 댓글 ⋮ 메뉴(답글 · 삭제) — 레퍼런스 view_comment 의 더보기 단추.
 * - 마우스: 단추에 얹으면 열리고, 단추 · 메뉴에서 벗어나면 잠깐 뒤 닫힌다.
 * - 터치 · 펜: hover 가 없으니 눌러서 열고, 바깥을 누르면 닫힌다.
 * - 키보드: Enter · Space 로 열고 첫 항목으로 초점이 들어간다. Esc 로 닫으면 단추로 돌아온다.
 * hover 로 열고 닫을 때는 초점을 옮기지 않는다 — 댓글을 쓰다 마우스가 지나가도 입력 칸의 초점을 빼앗지 않게.
 */
function CommentActionsMenu({ label, actions }: { label: string; actions: CommentAction[] }) {
  const [open, setOpen] = useState(false);
  const openedByHover = useRef(false);
  const closeTimer = useRef<number | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);
  useEffect(() => cancelClose, [cancelClose]);

  const openByHover = (event: ReactPointerEvent) => {
    if (event.pointerType !== "mouse") return;
    cancelClose();
    if (!open) {
      openedByHover.current = true;
      setOpen(true);
    }
  };
  const closeSoon = (event: ReactPointerEvent) => {
    if (event.pointerType !== "mouse" || !openedByHover.current) return;
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), MENU_HOVER_CLOSE_MS);
  };
  const run = (action: CommentAction) => {
    cancelClose();
    setOpen(false);
    action.onSelect();
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        cancelClose();
        if (next) openedByHover.current = false;
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="board-comment-menu size-8 shrink-0"
          aria-label={label}
          onPointerEnter={openByHover}
          onPointerLeave={closeSoon}
          // hover 로 이미 열린 메뉴를 마우스로 누르면 닫지 않는다(누르는 순간 닫혔다 깜박이지 않게).
          onClick={(event) => {
            if (open && openedByHover.current) event.preventDefault();
          }}
        >
          <MoreVertical className="size-4" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="board-comment-menu-list w-auto min-w-[7rem] p-1"
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") cancelClose();
        }}
        onPointerLeave={closeSoon}
        onOpenAutoFocus={(event) => {
          if (openedByHover.current) event.preventDefault();
        }}
        onCloseAutoFocus={(event) => {
          if (openedByHover.current) event.preventDefault();
        }}
      >
        <div role="group" aria-label={label} className="flex flex-col">
          {actions.map((action) => (
            <button
              key={action.key}
              type="button"
              className={`board-comment-menu-item rounded px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent${
                action.destructive ? " text-destructive" : ""
              }`}
              onClick={() => run(action)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

const CommentItem = memo(function CommentItem({
  comment,
  boTable,
  onReply,
  replyTo,
  onCommentSubmit,
  onDelete,
  canReply,
  canDeleteAsAdmin,
  useEditor,
  replyToName,
}: CommentItemProps) {
  const { user } = useAuthStore();
  const [replyContent, setReplyContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canDelete = Boolean(user && (user.mb_id === comment.mb_id || canDeleteAsAdmin));
  const isReplyOpen = replyTo === comment.wr_id;
  const depth = comment.wr_comment_reply?.length ?? 0;
  const displayName = comment.mb_nick || comment.wr_name;
  const actions: CommentAction[] = [
    ...(canReply
      ? [{ key: "reply", label: isReplyOpen ? "답글 닫기" : "답글", onSelect: () => onReply(isReplyOpen ? -1 : comment.wr_id) }]
      : []),
    ...(canDelete ? [{ key: "delete", label: "삭제", destructive: true, onSelect: () => onDelete(comment.wr_id) }] : []),
  ];

  const handleReplySubmit = async () => {
    if (isContentEmpty(replyContent)) return;
    setSubmitting(true);
    try {
      await onCommentSubmit(replyContent, comment.wr_id);
      setReplyContent("");
      onReply(-1);
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "답글 등록에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    // id 는 그누보드 댓글(view_comment 의 c_번호)과 같은 주소 — 최근 댓글 링크의 #c_번호 가 여기로 온다.
    // 깊이는 --comment-depth 로 넘긴다 — 들여쓰기 · 이음선(└)은 테마가 그린다(기본은 한 단에 24px).
    <div
      id={`c_${comment.wr_id}`}
      tabIndex={-1}
      data-depth={depth}
      style={{ "--comment-depth": depth } as CSSProperties}
      className={`board-comment${depth > 0 ? " board-comment--reply" : ""} relative border-b py-3 pl-[calc(var(--comment-depth)*24px)] last:border-b-0 scroll-mt-24 outline-none`}
    >
      <div className="board-comment-row flex items-start gap-3">
        <MemberAvatar
          name={displayName}
          member={{ mb_icon_path: comment.member?.mb_icon_path }}
          className="board-comment-avatar grid size-9 shrink-0 place-items-center rounded-full bg-muted text-sm font-semibold"
          size={40}
        />
        <div className="board-comment-main min-w-0 flex-1">
          <div className="board-comment-meta flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
            <MemberSideview
              mbId={comment.mb_id}
              name={displayName}
              boTable={boTable}
              className="board-comment-name font-medium"
            >
              <span>{displayName}</span>
            </MemberSideview>
            {replyToName ? (
              <span className="board-comment-to text-xs text-muted-foreground">{replyToName} 님에게</span>
            ) : null}
            <time className="board-comment-date text-xs text-muted-foreground" dateTime={comment.wr_datetime}>
              {formatDate(comment.wr_datetime)}
            </time>
          </div>
          <div className="board-comment-body mt-1">
            <div
              className="break-words text-sm leading-relaxed"
              dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(comment.wr_content) }}
            />
          </div>

          {/* Reply Form */}
          {isReplyOpen && canReply && (
            <div className="mt-3 space-y-2">
              {useEditor ? (
                <CommentEditor
                  content={replyContent}
                  onChange={setReplyContent}
                  placeholder="답글을 입력하세요"
                />
              ) : (
                <Textarea
                  value={replyContent}
                  onChange={(e) => setReplyContent(e.target.value)}
                  placeholder="답글을 입력하세요"
                  rows={2}
                  className="text-sm"
                  aria-label="답글"
                />
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => onReply(-1)}>
                  취소
                </Button>
                <Button
                  size="sm"
                  onClick={handleReplySubmit}
                  disabled={submitting || isContentEmpty(replyContent)}
                >
                  {submitting ? "등록 중..." : "답글 등록"}
                </Button>
              </div>
            </div>
          )}
        </div>
        {/* 답글 · 삭제는 오른쪽 ⋮ 메뉴 하나로(레퍼런스 view_comment 의 더보기 단추). */}
        {actions.length > 0 ? <CommentActionsMenu label={`${displayName} 댓글 메뉴`} actions={actions} /> : null}
      </div>
    </div>
  );
});

export function CommentSection({ boTable, wrId, initialComments, board, useEditor }: CommentSectionProps) {
  const router = useRouter();
  const { user } = useAuthStore();
  const boardUsesCaptcha = board?.bo_use_captcha === 1;
  const [guestName, setGuestName] = useState("");
  const [guestPassword, setGuestPassword] = useState("");
  const [captchaKey, setCaptchaKey] = useState("");
  const [captchaVersion, setCaptchaVersion] = useState(() => Date.now());
  const canDeleteAsAdmin = Boolean(
    user && board && (
      user.is_super_admin ||
      user.mb_id === board.bo_admin ||
      user.mb_id === board.gr_admin
    )
  );
  const canComment = Boolean(
    board && (canDeleteAsAdmin || (user?.mb_level ?? 1) >= board.bo_comment_level)
  );
  const [comments, setComments] = useState<Comment[]>(initialComments);
  const [submitting, setSubmitting] = useState(false);
  const [replyTo, setReplyTo] = useState<number | null>(null);
  // 목록 접기(레퍼런스 댓글 머리의 [접기]). 쓰기 칸은 접지 않는다.
  const [folded, setFolded] = useState(false);

  // 에디터 내용은 ref로 관리하여 타이핑 시 리렌더 방지
  const newCommentRef = useRef("");
  const [canSubmit, setCanSubmit] = useState(false);

  // textarea용 상태 (useEditor가 false일 때만 사용)
  const [textareaValue, setTextareaValue] = useState("");

  const handleEditorChange = useCallback((html: string) => {
    newCommentRef.current = html;
    const empty = isContentEmpty(html);
    setCanSubmit((prev) => {
      if (prev === !empty) return prev;
      return !empty;
    });
  }, []);

  const handleTextareaChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setTextareaValue(val);
    newCommentRef.current = val;
  }, []);

  // Returns false when the list could not be refreshed, so callers can tell the user
  // that a successful write may not be visible yet instead of leaving them guessing.
  const fetchComments = useCallback(async (): Promise<boolean> => {
    try {
      const res = await apiClient.get<{ comments?: Comment[] }>(`/posts/${boTable}/${wrId}`);
      setComments(res.data?.comments ?? []);
      return true;
    } catch {
      return false;
    }
  }, [boTable, wrId]);

  const handleSubmitComment = useCallback(async (content: string, parentId?: number) => {
    if (!user && !guestName.trim()) throw new Error("이름을 입력해주세요.");
    if (!user && !guestPassword) throw new Error("비밀번호를 입력해주세요.");
    if (!user && boardUsesCaptcha && !captchaKey.trim()) {
      throw new Error("자동등록방지 문자를 입력해주세요.");
    }
    try {
      await apiClient.post(`/comments/${boTable}/${wrId}`, {
        wr_content: content,
        comment_id: parentId,
        ...(!user ? {
          wr_name: guestName.trim(),
          wr_password: guestPassword,
          captcha_key: captchaKey.trim(),
        } : {}),
      });
    } catch (err) {
      if (!user && boardUsesCaptcha) {
        setCaptchaKey("");
        setCaptchaVersion(Date.now());
      }
      throw err;
    }
    if (!user && boardUsesCaptcha) {
      setCaptchaKey("");
      setCaptchaVersion(Date.now());
    }
    if (!user) setGuestPassword("");
    if (!(await fetchComments())) {
      toastError("댓글은 등록되었지만 목록을 새로 불러오지 못했습니다. 페이지를 새로고침해 주세요.");
    }
    // post 상세의 wr_comment 카운트 / 게시판 listing 의 댓글 수 동기화.
    router.refresh();
  }, [boTable, wrId, fetchComments, router, user, guestName, guestPassword, captchaKey, boardUsesCaptcha]);

  // 에디터 리셋용 key
  const [editorKey, setEditorKey] = useState(0);

  const handleNewComment = useCallback(async () => {
    const content = newCommentRef.current;
    if (isContentEmpty(content)) return;
    setSubmitting(true);
    try {
      await handleSubmitComment(content);
      newCommentRef.current = "";
      setCanSubmit(false);
      setTextareaValue("");
      // 에디터 리셋을 위해 강제 리마운트
      setEditorKey((k) => k + 1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "댓글 등록에 실패했습니다.";
      toastError(message);
    } finally {
      setSubmitting(false);
    }
  }, [handleSubmitComment]);

  const handleDelete = useCallback(async (commentId: number) => {
    if (!confirm("댓글을 삭제하시겠습니까?")) return;
    try {
      await apiClient.delete(`/comments/${boTable}/${commentId}`);
      if (!(await fetchComments())) {
        toastError("댓글은 삭제되었지만 목록을 새로 불러오지 못했습니다. 페이지를 새로고침해 주세요.");
      }
      router.refresh();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "삭제에 실패했습니다.";
      toastError(message);
    }
  }, [boTable, fetchComments, router]);

  // 답글의 받는 사람: 같은 댓글 묶음(wr_comment)에서 wr_comment_reply 가 한 글자 짧은 댓글(그누보드 답글 규칙).
  const replyToNames = useMemo(() => {
    const byKey = new Map(
      comments.map((item) => [`${item.wr_comment}|${item.wr_comment_reply ?? ""}`, item.mb_nick || item.wr_name])
    );
    return new Map(
      comments
        .filter((item) => (item.wr_comment_reply ?? "") !== "")
        .map((item) => [item.wr_id, byKey.get(`${item.wr_comment}|${(item.wr_comment_reply ?? "").slice(0, -1)}`)])
    );
  }, [comments]);

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="board-comments-head mb-4 flex items-center justify-between gap-3">
          <h3 className="text-lg font-semibold">
            댓글 <span className="board-comments-count text-primary">{comments.length}</span>
          </h3>
          {comments.length > 0 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="board-comments-fold"
              aria-expanded={!folded}
              aria-controls="board-comments-list"
              onClick={() => setFolded((value) => !value)}
            >
              {folded ? "펼치기" : "접기"}
            </Button>
          ) : null}
        </div>

        {/* Comment List */}
        {comments.length > 0 && (
          <div id="board-comments-list" className="board-comments-list mb-6" hidden={folded}>
            {comments.map((comment) => (
              <CommentItem
                key={comment.wr_id}
                comment={comment}
                boTable={boTable}
                onReply={setReplyTo}
                replyTo={replyTo}
                onCommentSubmit={handleSubmitComment}
                onDelete={handleDelete}
                canReply={canComment}
                canDeleteAsAdmin={canDeleteAsAdmin}
                useEditor={useEditor}
                replyToName={replyToNames.get(comment.wr_id)}
              />
            ))}
          </div>
        )}

        {/* New Comment Form — 게시판 댓글 권한이 비회원을 받으면(그누보드 bo_comment_level 1) 이름 · 비밀번호(· 자동등록방지)를 함께 받는다. */}
        {canComment ? (
          <div className="board-comment-form space-y-3">
            {!user && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="comment_guest_name">이름</Label>
                  <Input
                    id="comment_guest_name"
                    value={guestName}
                    onChange={(event) => setGuestName(event.target.value)}
                    autoComplete="name"
                    maxLength={255}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="comment_guest_password">비밀번호</Label>
                  <Input
                    id="comment_guest_password"
                    type="password"
                    value={guestPassword}
                    onChange={(event) => setGuestPassword(event.target.value)}
                    autoComplete="new-password"
                    maxLength={128}
                  />
                </div>
                {boardUsesCaptcha && (
                  <div className="space-y-2 sm:col-span-2">
                    <Label htmlFor="comment_captcha">자동등록방지</Label>
                    <div className="flex items-center gap-2">
                      <img
                        src={apiUrl(`/captcha?t=${captchaVersion}`)}
                        alt="자동등록방지 문자"
                        width={160}
                        height={60}
                        crossOrigin="use-credentials"
                        className="rounded border border-border bg-base-100"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        onClick={() => {
                          setCaptchaKey("");
                          setCaptchaVersion(Date.now());
                        }}
                        aria-label="새 자동등록방지 문자"
                      >
                        <RefreshCw className="size-4" />
                      </Button>
                    </div>
                    <Input
                      id="comment_captcha"
                      value={captchaKey}
                      onChange={(event) => setCaptchaKey(event.target.value)}
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={6}
                    />
                  </div>
                )}
              </div>
            )}
            {useEditor ? (
              <CommentEditor
                key={editorKey}
                content=""
                onChange={handleEditorChange}
                placeholder="댓글을 입력하세요"
              />
            ) : (
              <Textarea
                value={textareaValue}
                onChange={handleTextareaChange}
                placeholder="댓글을 입력하세요"
                rows={3}
                aria-label="댓글"
              />
            )}
            <div className="flex justify-end">
              <Button
                onClick={handleNewComment}
                disabled={submitting || (useEditor ? !canSubmit : !textareaValue.trim())}
              >
                {submitting ? "등록 중..." : "댓글 등록"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="board-comment-login text-sm text-muted-foreground text-center py-4">
            {user ? "댓글 작성 권한이 없습니다." : "댓글을 작성하려면 로그인이 필요합니다."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
