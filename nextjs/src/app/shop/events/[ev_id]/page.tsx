import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import ClientPage from "./ClientPage";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ ev_id: "0" }];
}

interface PageProps {
  params: Promise<{ ev_id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { ev_id } = await params;

  return buildPageMetadata({
    title: "기획전",
    description: "쇼핑몰 기획전과 행사 상품을 확인하세요.",
    path:
      ev_id === "__g5_static__"
        ? "/shop/events"
        : `/shop/events/${encodeURIComponent(ev_id)}`,
  });
}

export default function Page(_props: PageProps) {
  return <ClientPage />;
}
