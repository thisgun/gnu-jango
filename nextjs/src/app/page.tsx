import { buildPageMetadata } from "@/lib/seo";
import { EMPTY_REFERENCE_HOME, loadReferenceHomeData } from "./reference-home-data";
import { ReferenceHomeClient } from "./ReferenceHomeClient";

export const metadata = buildPageMetadata({
  title: "그누보드5",
  description: "그누보드5 커뮤니티 게시판과 FAQ, 갤러리, 새 댓글을 확인하세요.",
  path: "/",
});

export default async function HomePage() {
  const initialData = process.env.G5_NEXT_RUNTIME === "server"
    ? await loadReferenceHomeData().catch((error: unknown) => {
        console.error("[reference-home:initial]", error);
        return EMPTY_REFERENCE_HOME;
      })
    : EMPTY_REFERENCE_HOME;

  return <ReferenceHomeClient initialData={initialData} />;
}
