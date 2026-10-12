"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Vote } from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { getCurrentPoll, getPoll } from "@/services/polls";
import type { Poll } from "@/lib/types";
import { PollClient } from "./PollClient";

export default function ClientPage() {
  const searchParams = useSearchParams();
  const poId = Math.max(0, Number(searchParams.get("po_id") || "0") || 0);
  const [poll, setPoll] = useState<Poll | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPoll(null);
    setError(null);
    setNotFound(false);

    const request = poId > 0 ? getPoll(poId) : getCurrentPoll();
    request.then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setPoll(result.data);
      } else if (result.status === 404) {
        setNotFound(true);
      } else {
        setError(result.error);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [poId]);

  return (
    <div className="container mx-auto max-w-5xl px-4 py-8">
      <Breadcrumb items={[{ label: "설문조사" }]} />
      <h1 className="mb-6 text-2xl font-bold">설문조사</h1>
      {notFound && <EmptyState icon={<Vote className="size-6" />} title="진행 중인 설문조사가 없습니다" />}
      {error && <ErrorState title="설문조사를 불러오지 못했습니다" description={error} actionHref="/polls" />}
      {!poll && !error && !notFound && <p className="text-sm text-muted-foreground">로딩 중...</p>}
      {poll && <PollClient initialPoll={poll} />}
    </div>
  );
}
