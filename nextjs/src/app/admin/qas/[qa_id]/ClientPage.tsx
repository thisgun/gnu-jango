"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import type { QaItem } from "@/lib/types";
import { answerQa, answerQaWithFiles, deleteQa, getQa } from "@/services/qas";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { QaAttachments } from "@/components/qa/qa-detail-extras";
import { toastError, toastSuccess } from "@/lib/toast";

interface AdminQaDetailPageProps {
  qaId?: string;
}

function StatusBadge({ status }: { status: number }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        status === 1 ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
      )}
    >
      {status === 1 ? "답변완료" : "답변대기"}
    </span>
  );
}

export default function AdminQaDetailPage({ qaId: fallbackQaId }: AdminQaDetailPageProps) {
  const router = useRouter();
  const qaId = Math.max(
    0,
    Number(useRuntimeRouteParam("qa_id", "/admin/qas/:qa_id", fallbackQaId)) || 0
  );
  const [item, setItem] = useState<QaItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [files, setFiles] = useState<Array<File | null>>([null, null]);
  const [deleteFiles, setDeleteFiles] = useState<number[]>([]);
  const [answerForm, setAnswerForm] = useState({
    qa_subject: "",
    qa_content: "",
  });

  useEffect(() => {
    if (!qaId) return;

    (async () => {
      setLoading(true);
      try {
        const nextItem = await getQa(qaId);
        setItem(nextItem);
        setAnswerForm({
          qa_subject: nextItem.answer?.qa_subject || `RE: ${nextItem.qa_subject}`,
          qa_content: nextItem.answer?.qa_content || "",
        });
        setFiles([null, null]);
        setDeleteFiles([]);
      } catch (error) {
        toastError(error instanceof Error ? error.message : "문의 내용을 불러오지 못했습니다.");
        runtimeRouterPush(router, "/admin/qas");
      } finally {
        setLoading(false);
      }
    })();
  }, [qaId, router]);

  async function handleAnswer(event: React.FormEvent) {
    event.preventDefault();
    if (!item) return;

    if (!answerForm.qa_subject.trim() || !answerForm.qa_content.trim()) {
      toastError("답변 제목과 내용을 입력해 주세요.");
      return;
    }

    setSaving(true);
    try {
      const hasAttachmentChanges = files.some(Boolean) || deleteFiles.length > 0;
      const updated = hasAttachmentChanges
        ? await answerQaWithFiles(item.qa_id, answerForm, { files, deleteFiles })
        : await answerQa(item.qa_id, answerForm);
      setItem(updated);
      setFiles([null, null]);
      setDeleteFiles([]);
      toastSuccess("답변이 저장되었습니다.");
    } catch (error) {
      toastError(error instanceof Error ? error.message : "답변 저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!item || !confirm("이 문의와 답변을 삭제하시겠습니까?")) return;
    try {
      await deleteQa(item.qa_id);
      toastSuccess("문의가 삭제되었습니다.");
      runtimeRouterPush(router, "/admin/qas");
    } catch (error) {
      toastError(error instanceof Error ? error.message : "문의 삭제에 실패했습니다.");
    }
  }

  if (loading || !item) {
    return <div className="h-72 animate-pulse rounded-lg bg-muted" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="outline" size="sm" onClick={() => runtimeRouterPush(router, "/admin/qas")}>
          <ArrowLeft className="mr-2 size-4" />
          목록
        </Button>
        <Button variant="outline" size="sm" onClick={handleDelete}>
          <Trash2 className="mr-2 size-4" />
          삭제
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={item.qa_status} />
            {item.qa_category && (
              <span className="text-xs text-muted-foreground">{item.qa_category}</span>
            )}
            <span className="text-xs text-muted-foreground">
              {formatDate(item.qa_datetime)}
            </span>
          </div>
          <CardTitle className="break-words">{item.qa_subject}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {item.qa_name} ({item.mb_id})
          </p>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap break-words text-sm leading-7">
            {item.qa_content}
          </p>
          {(item.qa_email || item.qa_hp) && (
            <div className="mt-5 grid gap-2 rounded-md border bg-muted/20 p-3 text-sm sm:grid-cols-2">
              {item.qa_email && (
                <div>
                  <span className="text-muted-foreground">이메일</span>
                  <p>{item.qa_email}</p>
                </div>
              )}
              {item.qa_hp && (
                <div>
                  <span className="text-muted-foreground">휴대폰</span>
                  <p>{item.qa_hp}</p>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <QaAttachments item={item} />

      {item.answer && <QaAttachments item={item.answer} />}

      <Card>
        <CardHeader>
          <CardTitle>{item.answer ? "답변 수정" : "답변 등록"}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAnswer} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="answer_subject">답변 제목</Label>
              <Input
                id="answer_subject"
                value={answerForm.qa_subject}
                onChange={(event) =>
                  setAnswerForm((prev) => ({ ...prev, qa_subject: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="answer_content">답변 내용</Label>
              <Textarea
                id="answer_content"
                value={answerForm.qa_content}
                onChange={(event) =>
                  setAnswerForm((prev) => ({ ...prev, qa_content: event.target.value }))
                }
                rows={10}
                required
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {[0, 1].map((index) => {
                const slot = index + 1;
                const source = slot === 1 ? item.answer?.qa_source1 : item.answer?.qa_source2;
                return (
                  <div key={slot} className="space-y-2 rounded-md border p-3">
                    <Label htmlFor={`answer_bf_file_${slot}`}>첨부파일 #{slot}</Label>
                    {source && (
                      <label className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Checkbox
                          checked={deleteFiles.includes(slot)}
                          onChange={(event) =>
                            setDeleteFiles((prev) =>
                              event.target.checked
                                ? Array.from(new Set([...prev, slot]))
                                : prev.filter((value) => value !== slot)
                            )
                          }
                        />
                        현재 파일 삭제: {source}
                      </label>
                    )}
                    <Input
                      id={`answer_bf_file_${slot}`}
                      type="file"
                      onChange={(event) => {
                        const next = [...files];
                        next[index] = event.target.files?.[0] || null;
                        setFiles(next);
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end">
              <Button type="submit" disabled={saving}>
                {saving ? "저장 중" : "답변 저장"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
