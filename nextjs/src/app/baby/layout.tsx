import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "육아수첩 — 우리 아기 기록",
  description: "수유·기저귀·수면 기록, 성장 추이, 한국 표준 예방접종 일정을 한 곳에서.",
};

export default function BabyLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
