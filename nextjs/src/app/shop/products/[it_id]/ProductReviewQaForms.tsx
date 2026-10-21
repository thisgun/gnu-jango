"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { ShopPolicy, ShopQA } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ChevronDown, LockKeyhole, Star } from "lucide-react";
import { toastSuccess, toastError } from "@/lib/toast";
import { sanitizeUserHtml } from "@/lib/sanitize";
import { updateShopQa, deleteShopQa } from "@/services/shop";

/**
 * 상품 후기 작성 폼 — 로그인 회원만 접근. 백엔드에서 영카트 후기 작성 정책을 검증.
 * 여닫기는 부르는 쪽이 갖는다 — 사용후기 탭의 평점 요약 상자 오른쪽 [사용후기 쓰기]가 연다(레퍼런스 solune itemuse).
 */
export function ReviewForm({
  itId,
  policy,
  onSubmitted,
  open,
  onOpenChange,
}: {
  itId: string;
  policy?: ShopPolicy | null;
  onSubmitted: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [subject, setSubject] = useState("");
  const [content, setContent] = useState("");
  const [score, setScore] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const subjectId = useId();
  const contentId = useId();
  const imageInputId = useId();
  const setOpen = onOpenChange;

  if (!open) return null;

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!subject.trim() || !content.trim()) {
          toastError("제목과 내용을 입력해주세요.");
          return;
        }
        if (score < 1 || score > 5) {
          toastError("평점을 1~5 사이로 선택해주세요.");
          return;
        }
        setSubmitting(true);
        try {
          const imageHtml = imageUrls
            .map((url) => `<p><img src="${url.replace(/"/g, "&quot;")}" alt="" /></p>`)
            .join("\n");
          const reviewContent = [content.trim(), imageHtml].filter(Boolean).join("\n");
          await api.post("/shop/reviews", {
            it_id: itId,
            is_subject: subject.trim(),
            is_content: reviewContent,
            is_score: score,
          });
          toastSuccess("후기가 등록되었습니다.");
          setSubject("");
          setContent("");
          setScore(5);
          setImageUrls([]);
          setOpen(false);
          onSubmitted();
        } catch (err: unknown) {
          const m = err instanceof Error ? err.message : "등록 실패";
          toastError(m);
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <div>
        <label className="mb-1 block text-sm font-medium">평점</label>
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setScore(n)}
              className="rounded p-1 hover:bg-accent"
              aria-label={`${n}점`}
            >
              <Star
                className={cn(
                  "h-5 w-5",
                  n <= score ? "fill-amber-400 text-amber-400" : "text-muted-foreground/30"
                )}
              />
            </button>
          ))}
          <span className="ml-2 text-sm text-muted-foreground">{score} / 5</span>
        </div>
      </div>
      <div>
        <label htmlFor={subjectId} className="mb-1 block text-sm font-medium">제목</label>
        <input
          id={subjectId}
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          maxLength={255}
          required
        />
      </div>
      <div>
        <label htmlFor={contentId} className="mb-1 block text-sm font-medium">내용</label>
        <textarea
          id={contentId}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={4}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          required
        />
      </div>
      {/* 이미지 첨부 — textarea에는 본문만 두고, 제출 시 업로드 URL을 img HTML로 합친다. */}
      <div>
        <label htmlFor={imageInputId} className="mb-1 block text-sm font-medium">
          사진 첨부 <span className="text-xs text-muted-foreground">(선택)</span>
        </label>
        <input
          id={imageInputId}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const fd = new FormData();
            fd.append("file", f);
            try {
              const res = await api.upload<{ url: string }>("/upload", fd);
              const url = (res.data as { url?: string })?.url;
              if (url) {
                setImageUrls((prev) => [...prev, url]);
                toastSuccess("이미지가 첨부됐습니다.");
              }
            } catch (err: unknown) {
              const m = err instanceof Error ? err.message : "업로드 실패";
              toastError(m);
            } finally {
              // 같은 파일을 다시 첨부할 수 있게 input 리셋.
              e.target.value = "";
            }
          }}
          className="text-xs"
        />
        {imageUrls.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {imageUrls.map((url) => (
              <div key={url} className="relative h-16 w-16 overflow-hidden rounded-md border bg-muted">
                <img src={url} alt="" className="h-full w-full object-cover" loading="lazy" />
                <button
                  type="button"
                  className="absolute right-0 top-0 bg-background/90 px-1 text-xs"
                  onClick={() => setImageUrls((prev) => prev.filter((item) => item !== url))}
                  aria-label="첨부 이미지 제거"
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={submitting}>
          {submitting ? "등록 중..." : "등록"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            setImageUrls([]);
            setOpen(false);
          }}
          disabled={submitting}
        >
          취소
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {policy?.review_requires_completed_order
          ? "사용후기는 주문이 완료된 경우에만 작성하실 수 있습니다."
          : "로그인 회원은 이 상품에 후기를 작성할 수 있습니다."}
        {policy?.review_requires_moderation
          ? " 등록한 후기는 관리자 확인 후 노출됩니다."
          : " 등록한 후기는 바로 노출됩니다."}
      </p>
    </form>
  );
}

/**
 * 상품 문의 작성 폼 — 로그인 회원만 접근. POST /shop/reviews/qna 호출.
 * 여닫기는 부르는 쪽이 갖는다 — 상품문의 탭 머리의 [문의하기]가 연다(레퍼런스 solune itemqa).
 */
export function QaForm({
  itId,
  onSubmitted,
  open,
  onOpenChange,
}: {
  itId: string;
  onSubmitted: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [subject, setSubject] = useState("");
  const [question, setQuestion] = useState("");
  const [email, setEmail] = useState("");
  const [hp, setHp] = useState("");
  const [secret, setSecret] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const subjectId = useId();
  const questionId = useId();
  const emailId = useId();
  const hpId = useId();
  const secretId = useId();
  const setOpen = onOpenChange;

  if (!open) return null;

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!subject.trim() || !question.trim()) {
          toastError("제목과 내용을 입력해주세요.");
          return;
        }
        setSubmitting(true);
        try {
          await api.post("/shop/reviews/qna", {
            it_id: itId,
            iq_subject: subject.trim(),
            iq_question: question.trim(),
            iq_email: email.trim(),
            iq_hp: hp.trim(),
            iq_secret: secret ? 1 : 0,
          });
          toastSuccess("문의가 등록되었습니다.");
          setSubject("");
          setQuestion("");
          setEmail("");
          setHp("");
          setSecret(false);
          setOpen(false);
          onSubmitted();
        } catch (err: unknown) {
          const m = err instanceof Error ? err.message : "등록 실패";
          toastError(m);
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <div>
        <label htmlFor={subjectId} className="mb-1 block text-sm font-medium">제목</label>
        <input
          id={subjectId}
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          maxLength={255}
          required
        />
      </div>
      <div>
        <label htmlFor={questionId} className="mb-1 block text-sm font-medium">내용</label>
        <textarea
          id={questionId}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          required
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={emailId} className="mb-1 block text-sm font-medium">이메일</label>
          <input
            id={emailId}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            maxLength={100}
          />
        </div>
        <div>
          <label htmlFor={hpId} className="mb-1 block text-sm font-medium">휴대폰</label>
          <input
            id={hpId}
            type="tel"
            value={hp}
            onChange={(e) => setHp(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            maxLength={30}
          />
        </div>
      </div>
      <label htmlFor={secretId} className="flex items-center gap-2 text-sm">
        <input
          id={secretId}
          type="checkbox"
          checked={secret}
          onChange={(e) => setSecret(e.target.checked)}
          className="h-4 w-4 rounded"
        />
        비밀글 (관리자/작성자만 확인 가능)
      </label>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={submitting}>
          {submitting ? "등록 중..." : "등록"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setOpen(false)}
          disabled={submitting}
        >
          취소
        </Button>
      </div>
    </form>
  );
}

export function QaListItem({
  qa,
  onChanged,
  initiallyOpen = false,
}: {
  qa: ShopQA;
  onChanged: () => void;
  initiallyOpen?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(initiallyOpen);
  const [subject, setSubject] = useState(qa.iq_subject);
  const [question, setQuestion] = useState(qa.iq_question);
  const [email, setEmail] = useState(qa.iq_email ?? "");
  const [hp, setHp] = useState(qa.iq_hp ?? "");
  const [secret, setSecret] = useState(String(qa.iq_secret ?? "0") === "1");
  const [submitting, setSubmitting] = useState(false);
  const editSubjectId = useId();
  const editQuestionId = useId();
  const editEmailId = useId();
  const editHpId = useId();
  const editSecretId = useId();
  const contentId = useId();
  const isLocked = qa.can_view === false;
  const isSecret = String(qa.iq_secret ?? "0") === "1";
  const isAnswered = qa.is_answered === true || (qa.iq_answer ?? "").trim() !== "";
  const canEdit = qa.can_edit === true && !isLocked && !isAnswered;
  const canDelete = qa.can_delete === true && !isAnswered;

  useEffect(() => {
    setEditing(false);
    setSubject(qa.iq_subject);
    setQuestion(qa.iq_question);
    setEmail(qa.iq_email ?? "");
    setHp(qa.iq_hp ?? "");
    setSecret(String(qa.iq_secret ?? "0") === "1");
  }, [qa.iq_email, qa.iq_hp, qa.iq_id, qa.iq_question, qa.iq_secret, qa.iq_subject]);

  useEffect(() => {
    if (initiallyOpen) setOpen(true);
  }, [initiallyOpen]);

  const resetEditValues = () => {
    setSubject(qa.iq_subject);
    setQuestion(qa.iq_question);
    setEmail(qa.iq_email ?? "");
    setHp(qa.iq_hp ?? "");
    setSecret(String(qa.iq_secret ?? "0") === "1");
  };

  const handleUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!subject.trim() || !question.trim()) {
      toastError("제목과 내용을 입력해 주세요.");
      return;
    }

    setSubmitting(true);
    try {
      await updateShopQa(qa.iq_id, {
        iq_subject: subject.trim(),
        iq_question: question.trim(),
        iq_email: email.trim(),
        iq_hp: hp.trim(),
        iq_secret: secret ? 1 : 0,
      });
      toastSuccess("상품문의가 수정되었습니다.");
      setEditing(false);
      onChanged();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "상품문의를 수정하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("상품문의를 삭제하시겠습니까?")) {
      return;
    }

    setSubmitting(true);
    try {
      await deleteShopQa(qa.iq_id);
      toastSuccess("상품문의가 삭제되었습니다.");
      onChanged();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "상품문의를 삭제하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const editForm = (
    <form className="space-y-3 rounded-lg border p-4" onSubmit={handleUpdate}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor={editSubjectId} className="mb-1 block text-sm font-medium">제목</label>
          <Input
            id={editSubjectId}
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            maxLength={255}
            required
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={editQuestionId} className="mb-1 block text-sm font-medium">내용</label>
          <Textarea
            id={editQuestionId}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={4}
            required
          />
        </div>
        <div>
          <label htmlFor={editEmailId} className="mb-1 block text-sm font-medium">이메일</label>
          <Input
            id={editEmailId}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            maxLength={100}
          />
        </div>
        <div>
          <label htmlFor={editHpId} className="mb-1 block text-sm font-medium">휴대폰</label>
          <Input
            id={editHpId}
            type="tel"
            value={hp}
            onChange={(event) => setHp(event.target.value)}
            maxLength={30}
          />
        </div>
      </div>
      <label htmlFor={editSecretId} className="flex items-center gap-2 text-sm">
        <input
          id={editSecretId}
          type="checkbox"
          checked={secret}
          onChange={(event) => setSecret(event.target.checked)}
          className="size-4 accent-primary"
        />
        비밀글
      </label>
      <div className="flex justify-end gap-2">
        <Button type="submit" size="sm" disabled={submitting}>
          {submitting ? "수정 중..." : "수정하기"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={submitting}
          onClick={() => {
            resetEditValues();
            setEditing(false);
          }}
        >
          취소
        </Button>
      </div>
    </form>
  );

  /* 레퍼런스 solune itemqa.skin.php 의 한 줄 — [상태 | 제목 | 작성자 | 날짜 | ▼] 가 접혀 있고, 누르면 Q(물음)와
     A(답, 옅은 회색 바탕)가 펼쳐진다. 문의 하나를 주소로 가리킬 수 있게 #iq_N 을 단다(?iq_id= 로 찾아오면
     useProductDetailFocusScroll 이 data-focused 로 잠깐 표시하고 초점을 준다). 고칠 때는 펼친 자리에 폼이 선다. */
  return (
    <article
      id={`iq_${qa.iq_id}`}
      data-qa-id={qa.iq_id}
      tabIndex={-1}
      className="product-qa-item border-b outline-none transition-[background-color,box-shadow] duration-1000 data-[focused=true]:bg-primary/5 data-[focused=true]:ring-2 data-[focused=true]:ring-primary"
    >
      <button
        type="button"
        className="product-qa-row grid w-full grid-cols-[auto_minmax(0,1fr)_20px] items-center gap-x-3 gap-y-1 py-4 text-left sm:grid-cols-[76px_minmax(0,1fr)_auto_auto_20px] sm:gap-x-5 sm:py-5"
        aria-expanded={open || editing}
        aria-controls={contentId}
        onClick={() => setOpen((current) => !current)}
      >
        <span
          className={cn(
            "product-qa-status inline-flex h-6 items-center justify-center border px-2 text-[11px] font-bold",
            isAnswered ? "is-done border-primary bg-primary/10 text-primary" : "is-waiting bg-muted text-muted-foreground"
          )}
        >
          {isAnswered ? "답변완료" : "답변대기"}
        </span>
        <span className="product-qa-subject flex min-w-0 items-center gap-2 text-sm font-semibold">
          <span className="truncate">{isLocked ? "비밀글입니다." : qa.iq_subject}</span>
          {isSecret && (
            <>
              <LockKeyhole className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
              <span className="sr-only">비밀글</span>
            </>
          )}
        </span>
        {/* 폰에서는 제목 아래 둘째 줄, 넓은 화면에서는 한 줄의 칸(display: contents). */}
        <span className="product-qa-meta col-start-2 row-start-2 flex gap-2 text-xs text-muted-foreground sm:contents">
          <span className="product-qa-name">{qa.mb_nick}</span>
          <span className="product-qa-date tabular-nums">{formatDate(qa.iq_time)}</span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "product-qa-caret col-start-3 row-start-1 h-4 w-4 justify-self-end text-muted-foreground transition-transform motion-reduce:transition-none sm:col-auto sm:row-auto",
            (open || editing) && "rotate-180"
          )}
        />
      </button>

      <div id={contentId} hidden={!open && !editing} className="product-qa-content pb-7 text-sm leading-relaxed sm:pl-[96px]">
        {editing ? (
          editForm
        ) : (
          <>
            <div className="product-qa-question relative pl-11">
              <span className="product-qa-mark absolute left-0 top-0 text-lg font-extrabold leading-[1.6]" aria-hidden="true">Q</span>
              <strong className="sr-only">문의 내용</strong>
              {isLocked ? (
                <p className="text-muted-foreground">작성자와 관리자만 내용을 볼 수 있습니다.</p>
              ) : (
                <div
                  className="prose prose-sm max-w-none text-foreground"
                  dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(qa.iq_question) }}
                />
              )}
            </div>
            {!isLocked && (
              <div className="product-qa-answer relative mt-5 bg-muted py-5 pl-16 pr-5">
                <span className="product-qa-mark absolute left-5 top-5 text-lg font-extrabold leading-[1.6]" aria-hidden="true">A</span>
                <strong className="sr-only">답변</strong>
                {isAnswered ? (
                  <div
                    className="prose prose-sm max-w-none text-muted-foreground"
                    dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(qa.iq_answer) }}
                  />
                ) : (
                  <p className="text-muted-foreground">답변이 등록되지 않았습니다.</p>
                )}
              </div>
            )}
            {(canEdit || canDelete) && (
              <div className="product-qa-cmd mt-3 flex gap-2">
                {canEdit && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2.5 text-xs"
                    onClick={() => setEditing(true)}
                  >
                    수정
                  </Button>
                )}
                {canDelete && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="product-qa-delete h-7 px-2.5 text-xs"
                    onClick={handleDelete}
                    disabled={submitting}
                  >
                    삭제
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </article>
  );
}
