import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import PostViewClient from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ bo_table: "__g5_static__", wr_id: "0" }];
}

interface PageProps {
  params: Promise<{ bo_table: string; wr_id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { bo_table, wr_id } = await params;

  return buildPageMetadata({
    title: wr_id === "0" ? "Post" : `${bo_table} #${wr_id}`,
    path:
      bo_table === "__g5_static__" || wr_id === "0"
        ? "/boards"
        : `/boards/${bo_table}/${wr_id}`,
  });
}

export default async function PostViewPage({ params }: PageProps) {
  const { bo_table, wr_id } = await params;

  return <PostViewClient boTable={bo_table} wrId={wr_id} />;
}
