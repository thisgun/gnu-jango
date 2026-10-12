// @g5-server-runtime-only
import { NextRequest } from "next/server";
import { firstLegacyParam, legacyYoungcartRedirect } from "../../shop/_legacy-youngcart-redirect";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  return handleMobileContent(request);
}

export function POST(request: NextRequest) {
  return handleMobileContent(request);
}

function handleMobileContent(request: NextRequest) {
  const contentId = firstLegacyParam(request, ["co_id"]);
  if (contentId) {
    return legacyYoungcartRedirect(request, `/content/${encodeURIComponent(contentId)}`, {
      drop: ["co_id", "co_seo_title"],
      permanent: false,
    });
  }

  const seoTitle = firstLegacyParam(request, ["co_seo_title"]);
  if (seoTitle) {
    return legacyYoungcartRedirect(request, `/content/${encodeURIComponent(seoTitle)}/`, {
      drop: ["co_id", "co_seo_title"],
      permanent: false,
    });
  }

  return legacyYoungcartRedirect(request, "/", {
    drop: ["co_id", "co_seo_title"],
    permanent: false,
  });
}
