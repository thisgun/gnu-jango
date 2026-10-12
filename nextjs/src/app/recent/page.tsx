import { Suspense } from "react";
import { buildPageMetadata } from "@/lib/seo";
import ClientPage from "./ClientPage";

export const metadata = buildPageMetadata({
  title: "전체 게시물",
  path: "/recent",
});

function PageFallback() {
  return (
    <div className="container mx-auto px-4 py-8">
      <p role="status" className="text-sm text-muted-foreground">
        전체 게시물을 불러오는 중...
      </p>
    </div>
  );
}

export default function RecentPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <ClientPage />
    </Suspense>
  );
}
