import { Suspense } from "react";
import { buildPageMetadata } from "@/lib/seo";
import ClientPage from "./ClientPage";

export const metadata = buildPageMetadata({
  title: "검색",
  path: "/search",
});

function PageFallback() {
  return (
    <div className="container mx-auto px-4 py-8">
      <p role="status" className="text-sm text-muted-foreground">
        검색 결과를 불러오는 중...
      </p>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <ClientPage />
    </Suspense>
  );
}
