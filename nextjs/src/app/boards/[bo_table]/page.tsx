import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import BoardPostListClient from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ bo_table: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ bo_table: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { bo_table } = await params;

  return buildPageMetadata({
    title: bo_table === "__g5_static__" ? "게시판" : bo_table,
    path: bo_table === "__g5_static__" ? "/boards" : `/boards/${bo_table}`,
  });
}

export default async function BoardPostListPage({ params }: PageProps) {
  const { bo_table } = await params;

  return <BoardPostListClient boTable={bo_table} />;
}
