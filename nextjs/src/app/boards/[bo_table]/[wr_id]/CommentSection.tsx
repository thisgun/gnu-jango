"use client";

import { useState, useCallback, useRef, memo } from "react";
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
import { formatDate } from "@/lib/utils";
import { toastError } from "@/lib/toast";
import { MemberSideview } from "@/components/MemberSideview";
import { htmlToPlainText, sanitizeUserHtml } from "@/lib/sanitize";
import { RefreshCw } from "lucide-react";

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
}

function isContentEmpty(content: string): boolean {
  return !htmlToPlainText(content);
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
}: CommentItemProps) {
  const { user } = useAuthStore();
  const [replyContent, setReplyContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canDelete = user && (user.mb_id === comment.mb_id || canDeleteAsAdmin);
  const isReplyOpen = replyTo === comment.wr_id;
  const indent = (comment.wr_comment_reply?.length ?? 0) * 24;

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
    <div style={{ marginLeft: `${indent}px` }} className="py-3 border-b last:border-b-0">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2 text-sm">
          <MemberSideview
            mbId={comment.mb_id}
            name={comment.mb_nick || comment.wr_name}
            iconUrl={comment.member?.mb_icon_path}
            boTable={boTable}
            className="font-medium"
          />
          <span className="text-muted-foreground text-xs">
            {formatDate(comment.wr_datetime)}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {canReply && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onReply(isReplyOpen ? -1 : comment.wr_id)}
            >
              답글
            </Button>
          )}
          {canDelete && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-destructive"
              onClick={() => onDelete(comment.wr_id)}
            >
              삭제
            </Button>
          )}
        </div>
      </div>
      <div
        className="text-sm leading-relaxed"
        dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(comment.wr_content) }}
      />

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
            />
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onReply(-1)}
            >
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

  // 에디터 리셋용 key
  const [editorKey, setEditorKey] = useState(0);

  return (
    <Card>
      <CardContent className="pt-6">
        <h3 className="text-lg font-semibold mb-4">
          댓글 <span className="text-primary">{comments.length}</span>
        </h3>

        {canComment && !user && (
          <div className="mb-5 grid gap-4 sm:grid-cols-2">
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

        {/* Comment List */}
        {comments.length > 0 && (
          <div className="mb-6">
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
              />
            ))}
          </div>
        )}

        {/* New Comment Form */}
        {canComment ? (
          <div className="space-y-3">
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
        ) : !user ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            댓글을 작성하려면 로그인이 필요합니다.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-4">
            댓글 작성 권한이 없습니다.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
