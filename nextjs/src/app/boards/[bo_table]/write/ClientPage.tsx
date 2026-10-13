"use client";

import { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { apiClient } from "@/lib/api";
import { apiUrl, currentPathForRuntime, g5PathForRuntime } from "@/lib/config";
import { g5ShortHref } from "@/lib/g5-short-url";
import { boardPostHref } from "@/lib/board-url";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { useAuthStore } from "@/store/auth";
import { getClientPublicSettings } from "@/services/settings";
import type { Board, WritePost } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { toastInfo } from "@/lib/toast";
import { htmlToPlainText } from "@/lib/sanitize";
import { PostTemplates } from "./PostTemplates";
import { FileAttachments, type Attachment, type ExistingAttachment } from "@/components/FileAttachments";
import { RefreshCw } from "lucide-react";

const DRAFT_PREFIX = "draft_";

function getDraftKey(boTable: string): string {
  return `${DRAFT_PREFIX}${boTable}`;
}

function saveDraft(boTable: string, data: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(getDraftKey(boTable), JSON.stringify({ ...data, saved_at: Date.now() }));
  } catch { /* storage full */ }
}

function loadDraft(boTable: string): Record<string, string> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(getDraftKey(boTable));
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Expire drafts older than 24 hours
    if (data.saved_at && Date.now() - data.saved_at > 24 * 60 * 60 * 1000) {
      localStorage.removeItem(getDraftKey(boTable));
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

function clearDraft(boTable: string) {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(getDraftKey(boTable));
  } catch {
    // Draft cleanup must not interrupt successful post submission.
  }
}

const TiptapEditor = dynamic(
  () => import("@/components/editor/TiptapEditor").then((mod) => ({ default: mod.TiptapEditor })),
  {
    ssr: false,
    loading: () => <div className="min-h-[300px] border rounded-lg animate-pulse bg-muted/30" />,
  }
);

interface WritePageProps {
  boTable?: string;
}

interface ExistingAttachmentApi {
  bf_no: number;
  bf_source: string;
  bf_filesize: number;
  bf_url: string;
  bf_type: number;
}

export default function WritePage({ boTable: fallbackBoTable }: WritePageProps) {
  const searchParams = useSearchParams();
  const replyParentId = searchParams.get("parent_id");
  const isReplyRequest = searchParams.get("w") === "r" && !!replyParentId;
  const routeBoTable = useRuntimeRouteParam(
    "bo_table",
    ["/bbs/:bo_table/write", "/boards/:bo_table/write", "/:bo_table/write"],
    fallbackBoTable
  );
  const { user, isInitialized } = useAuthStore();

  const [boTable, setBoTable] = useState("");
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [isEdit, setIsEdit] = useState(false);
  const [isReply, setIsReply] = useState(false);

  const [formData, setFormData] = useState({
    ca_name: "",
    wr_subject: "",
    wr_content: "",
    wr_link1: "",
    wr_link2: "",
    wr_secret: false,
    html: "0",
  });
  const [guestName, setGuestName] = useState("");
  const [guestPassword, setGuestPassword] = useState("");
  const [captchaKey, setCaptchaKey] = useState("");
  const [captchaVersion, setCaptchaVersion] = useState(() => Date.now());
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  // The post already saved by an earlier submit whose attachment upload failed, so a retry
  // uploads the files again instead of creating a duplicate post.
  const savedPostRef = useRef<Partial<WritePost> | null>(null);

  // Allow anonymous submissions only when the board's configured level allows them.
  useEffect(() => {
    if (!isInitialized || loading || !board) return;

    const editWrId = searchParams.get("wr_id");
    const isReplyForm = searchParams.get("w") === "r" && Boolean(replyParentId);
    const requiredLevel = isReplyForm ? board.bo_reply_level : board.bo_write_level;
    const isBoardAdmin = Boolean(
      user && (
        user.is_super_admin ||
        user.mb_id === board.bo_admin ||
        user.mb_id === board.gr_admin
      )
    );
    const canSubmit = Boolean(
      (editWrId && user) ||
      (user?.mb_level ?? 1) >= requiredLevel ||
      isBoardAdmin
    );

    if (!canSubmit || (editWrId && !user)) {
      const returnPath = `${currentPathForRuntime()}${window.location.search}${window.location.hash}`;
      const loginPath = `/login?redirect=${encodeURIComponent(returnPath)}`;
      window.location.replace(g5PathForRuntime(loginPath));
    }
  }, [user, isInitialized, loading, board, searchParams, replyParentId]);

  // Resolve params and load board info
  useEffect(() => {
    savedPostRef.current = null; // a different form context never reuses an earlier saved post
    (async () => {
      if (!routeBoTable) {
        setError("게시판을 찾을 수 없습니다.");
        setLoading(false);
        return;
      }

      setBoTable(routeBoTable);

      try {
        const res = await apiClient.get<Board>(`/boards/${routeBoTable}`);
        setBoard(res.data ?? null);
        if (res.data?.bo_use_dhtml_editor === 1) {
          setFormData((prev) => ({ ...prev, html: "1" }));
        }
      } catch {
        setError("게시판 정보를 불러올 수 없습니다.");
      }

      // Check edit mode
      const editWrId = searchParams.get("wr_id");
      if (editWrId) {
        setIsReply(false);
        setIsEdit(true);
        try {
          // /boards/{bo_table}/posts/{id} 는 LIST 반환이므로 단건 endpoint 사용
          const res = await apiClient.get<WritePost>(
            `/posts/${routeBoTable}/${editWrId}`
          );
          const post = res.data as WritePost;
          setFormData({
            ca_name: post.ca_name || "",
            wr_subject: post.wr_subject || "",
            wr_content: post.wr_content || "",
            wr_link1: post.wr_link1 || "",
            wr_link2: post.wr_link2 || "",
            wr_secret: !!post.wr_option?.includes("secret"),
            html: post.wr_option?.includes("html1")
              ? "1"
              : post.wr_option?.includes("html2")
                ? "2"
                : "0",
          });
        } catch {
          setError("게시글 정보를 불러올 수 없습니다.");
        }

        // Load existing attachments for this post.
        try {
          const filesRes = await apiClient.get<ExistingAttachmentApi[]>(
            `/boards/${routeBoTable}/${editWrId}/files`
          );
          const list = (filesRes.data ?? []).map<ExistingAttachment>((f) => ({
            kind: "existing",
            id: `existing-${f.bf_no}`,
            bf_no: f.bf_no,
            bf_source: f.bf_source,
            bf_filesize: f.bf_filesize,
            bf_url: f.bf_url,
            bf_type: f.bf_type,
          }));
          setAttachments(list);
        } catch {
          // 첨부 조회 실패는 무시 (글 자체는 보임)
        }
      }

      if (isReplyRequest) {
        const parentSubject = searchParams.get("subject")?.trim() ?? "";
        // a reply keeps the category of the post it answers (Gnuboard5 write.php)
        const parentCategory = searchParams.get("ca_name")?.trim() ?? "";
        setIsReply(true);
        setFormData((prev) => ({
          ...prev,
          ca_name: parentCategory || prev.ca_name,
          wr_subject: parentSubject
            ? /^re:/i.test(parentSubject)
              ? parentSubject
              : `Re: ${parentSubject}`
            : prev.wr_subject,
        }));
      }

      // Restore drafts for new top-level posts only.
      if (!searchParams.get("wr_id") && !isReplyRequest) {
        setIsReply(false);
        const draft = loadDraft(routeBoTable);
        if (draft && (draft.wr_subject || draft.wr_content)) {
          setFormData((prev) => ({
            ...prev,
            ca_name: draft.ca_name || prev.ca_name,
            wr_subject: draft.wr_subject || prev.wr_subject,
            wr_content: draft.wr_content || prev.wr_content,
            wr_link1: draft.wr_link1 || prev.wr_link1,
            wr_link2: draft.wr_link2 || prev.wr_link2,
          }));
          toastInfo("임시저장된 글을 불러왔습니다.");
        }
      }

      setLoading(false);
    })();
  }, [routeBoTable, searchParams, isReplyRequest]);

  // Autosave draft every 10 seconds (new posts only)
  useEffect(() => {
    if (isEdit || isReply || !boTable) return;
    const timer = setInterval(() => {
      if (formData.wr_subject || formData.wr_content) {
        saveDraft(boTable, formData);
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [isEdit, isReply, boTable, formData]);

  const categories = board?.bo_category_list
    ? board.bo_category_list.split("|").filter(Boolean)
    : [];

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  // Secret posts are only offered where the board allows them (or to its administrators);
  // the API rejects them elsewhere, as Gnuboard5 does.
  const canUseSecret = Boolean(
    board?.bo_use_secret ||
      (user && (user.is_super_admin || user.mb_id === board?.bo_admin || user.mb_id === board?.gr_admin))
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!formData.wr_subject.trim()) {
      setError("제목을 입력해주세요.");
      return;
    }
    const contentText = board?.bo_use_dhtml_editor === 1
      ? htmlToPlainText(formData.wr_content)
      : formData.wr_content.trim();
    if (!contentText) {
      setError("내용을 입력해주세요.");
      return;
    }
    if (!user && !guestName.trim()) {
      setError("이름을 입력해주세요.");
      return;
    }
    if (!user && !guestPassword) {
      setError("비밀번호를 입력해주세요.");
      return;
    }
    if (!user && board?.bo_use_captcha && !captchaKey.trim()) {
      setError("자동등록방지 문자를 입력해주세요.");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        ca_name: formData.ca_name || undefined,
        wr_subject: formData.wr_subject,
        wr_content: formData.wr_content,
        wr_link1: formData.wr_link1 || undefined,
        wr_link2: formData.wr_link2 || undefined,
        secret: canUseSecret && formData.wr_secret ? "secret" : "",
        html: formData.html,
        reply_to: isReply ? Number(replyParentId) : undefined,
        ...(!user ? {
          wr_name: guestName.trim(),
          wr_password: guestPassword,
          captcha_key: captchaKey.trim(),
        } : {}),
      };

      const editWrId = searchParams.get("wr_id");
      let targetWrId: number | undefined;
      let targetPost: Partial<WritePost> | undefined;

      if (isEdit && editWrId) {
        // posts.php는 PATCH /posts/{bo_table}/{wr_id} 를 받음
        const res = await apiClient.patch<WritePost>(`/posts/${boTable}/${editWrId}`, payload);
        targetWrId = Number(editWrId);
        targetPost = res.data;
      } else if (savedPostRef.current) {
        // Retry after a failed attachment upload: members save the form again onto the same post
        // (keeping its secret flag, which a reply may have inherited); guests cannot edit, so the
        // saved post is reused as is.
        const saved = savedPostRef.current;
        targetWrId = saved.wr_id;
        targetPost = saved;
        if (user && targetWrId) {
          const res = await apiClient.patch<WritePost>(`/posts/${boTable}/${targetWrId}`, {
            ...payload,
            secret: saved.is_secret ? "secret" : payload.secret,
          });
          targetPost = res.data;
        }
      } else {
        if (!isReply) clearDraft(boTable);
        const res = await apiClient.post<WritePost>(`/boards/${boTable}/posts`, payload);
        targetWrId = res.data?.wr_id;
        targetPost = res.data;
        savedPostRef.current = res.data ?? null;
      }

      // Sync attachments (new + edit). Skip if nothing to do AND it's a brand
      // new post — saves a round trip when the user posted text-only.
      const hasNewFiles = attachments.some((a) => a.kind === "new");
      const editedFiles = isEdit; // edit always reconciles to handle deletes
      if (targetWrId && (hasNewFiles || editedFiles)) {
        const fd = new FormData();
        attachments.forEach((att) => {
          if (att.kind === "existing") {
            fd.append("order[]", String(att.bf_no));
          } else {
            // index within only "new" entries
            const newIdx = attachments
              .filter((a) => a.kind === "new")
              .findIndex((a) => a.id === att.id);
            fd.append("order[]", `new:${newIdx}`);
            fd.append("files[]", att.file);
          }
        });

        await apiClient.upload(`/boards/${boTable}/${targetWrId}/files`, fd);
      }

      const settings = await getClientPublicSettings().catch(() => null);
      window.location.href = targetWrId
        ? boardPostHref(
            boTable,
            { wr_id: targetWrId, wr_seo_title: targetPost?.wr_seo_title },
            settings?.cf_bbs_rewrite
          )
        : g5ShortHref(`/boards/${boTable}`);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "게시글 저장에 실패했습니다.";
      setError(
        savedPostRef.current
          ? `글은 등록되었지만 첨부파일을 올리지 못했습니다. (${message}) 첨부파일을 확인한 뒤 다시 제출하면 첨부만 다시 올립니다.`
          : message
      );
      if (!user && board?.bo_use_captcha) {
        setCaptchaKey("");
        setCaptchaVersion(Date.now());
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!isInitialized) return null;

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-16 text-center text-muted-foreground">
        로딩 중...
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {board && (
        <Breadcrumb
          items={[
            { label: board.bo_subject, href: g5ShortHref(`/boards/${boTable}`) },
            { label: isEdit ? "글 수정" : isReply ? "답글 작성" : "글 쓰기" },
          ]}
        />
      )}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>{isEdit ? "글 수정" : isReply ? "답글 작성" : "글 쓰기"}</CardTitle>
            {!isEdit && !isReply && (
              <PostTemplates
                onApply={(prefix, content) => {
                  setFormData((prev) => ({
                    ...prev,
                    wr_subject: prefix + prev.wr_subject.replace(/^\[(질문|후기|공지)\]\s*/, ""),
                    wr_content: content,
                  }));
                }}
              />
            )}
          </div>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {!user && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="guest_name">이름</Label>
                  <Input
                    id="guest_name"
                    value={guestName}
                    onChange={(event) => setGuestName(event.target.value)}
                    autoComplete="name"
                    maxLength={255}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="guest_password">비밀번호</Label>
                  <Input
                    id="guest_password"
                    type="password"
                    value={guestPassword}
                    onChange={(event) => setGuestPassword(event.target.value)}
                    autoComplete="new-password"
                    maxLength={128}
                    required
                  />
                </div>
              </div>
            )}

            {!user && board?.bo_use_captcha === 1 && (
              <div className="space-y-2">
                <Label htmlFor="write_captcha">자동등록방지</Label>
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
                    disabled={submitting}
                    aria-label="새 자동등록방지 문자"
                  >
                    <RefreshCw className="size-4" />
                  </Button>
                </div>
                <Input
                  id="write_captcha"
                  value={captchaKey}
                  onChange={(event) => setCaptchaKey(event.target.value)}
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={6}
                  required
                />
              </div>
            )}

            {/* Category */}
            {categories.length > 0 && (
              <div className="space-y-2">
                <Label>분류</Label>
                <Select
                  value={formData.ca_name}
                  onValueChange={(v) =>
                    setFormData((prev) => ({ ...prev, ca_name: v }))
                  }
                >
                  <SelectTrigger aria-label="분류">
                    <SelectValue placeholder="분류를 선택하세요" />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map((cat) => (
                      <SelectItem key={cat} value={cat}>
                        {cat}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Subject */}
            <div className="space-y-2">
              <Label htmlFor="wr_subject">제목</Label>
              <Input
                id="wr_subject"
                name="wr_subject"
                value={formData.wr_subject}
                onChange={handleChange}
                placeholder="제목을 입력하세요"
                required
              />
            </div>

            {/* Content */}
            <div className="space-y-2">
              <Label htmlFor="wr_content">내용</Label>
              {board?.bo_use_dhtml_editor === 1 ? (
                <TiptapEditor
                  content={formData.wr_content}
                  onChange={(html) =>
                    setFormData((prev) => ({ ...prev, wr_content: html }))
                  }
                  placeholder="내용을 입력하세요"
                />
              ) : (
                <Textarea
                  id="wr_content"
                  name="wr_content"
                  value={formData.wr_content}
                  onChange={handleChange}
                  placeholder="내용을 입력하세요"
                  rows={15}
                  required
                />
              )}
            </div>

            {/* File attachments */}
            {user && (
              <div className="space-y-2">
                <Label>첨부파일</Label>
                <FileAttachments
                  value={attachments}
                  onChange={setAttachments}
                  maxCount={board?.bo_upload_count ?? 0}
                  maxSize={board?.bo_upload_size ?? 0}
                  disabled={submitting}
                />
              </div>
            )}

            {/* Links */}
            <div className="space-y-2">
              <Label htmlFor="wr_link1">링크 1</Label>
              <Input
                id="wr_link1"
                name="wr_link1"
                type="url"
                value={formData.wr_link1}
                onChange={handleChange}
                placeholder="https://"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="wr_link2">링크 2</Label>
              <Input
                id="wr_link2"
                name="wr_link2"
                type="url"
                value={formData.wr_link2}
                onChange={handleChange}
                placeholder="https://"
              />
            </div>

            {/* Options */}
            <div className="flex flex-wrap items-center gap-6 pt-2">
              {canUseSecret && (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="wr_secret"
                    checked={formData.wr_secret}
                    onChange={(e) =>
                      setFormData((prev) => ({
                        ...prev,
                        wr_secret: e.target.checked,
                      }))
                    }
                  />
                  <Label htmlFor="wr_secret" className="text-sm font-normal">
                    비밀글
                  </Label>
                </div>
              )}
              {board?.bo_use_dhtml_editor !== 1 && (
                <div className="flex items-center gap-2">
                  <Label className="text-sm font-normal">HTML</Label>
                  <Select
                    value={formData.html}
                    onValueChange={(v) =>
                      setFormData((prev) => ({ ...prev, html: v }))
                    }
                  >
                    <SelectTrigger className="w-[140px]" aria-label="HTML 옵션">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0">사용안함</SelectItem>
                      <SelectItem value="1">HTML 허용</SelectItem>
                      <SelectItem value="2">HTML 자동줄바꿈</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>

            {/* Submit */}
            <div className="flex justify-end gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  window.location.href = isReply && replyParentId
                    ? g5ShortHref(`/boards/${boTable}/${replyParentId}`)
                    : g5ShortHref(`/boards/${boTable}`);
                }}
                disabled={submitting}
              >
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting
                  ? "저장 중..."
                : isEdit
                  ? "수정 완료"
                  : isReply
                    ? "답글 등록"
                    : "작성 완료"}
              </Button>
            </div>
          </CardContent>
        </form>
      </Card>
    </div>
  );
}
