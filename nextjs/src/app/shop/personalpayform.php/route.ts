// @g5-server-runtime-only
import { NextRequest, NextResponse } from "next/server";
import { firstLegacyParam, legacyYoungcartRedirect } from "../_legacy-youngcart-redirect";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  const ppId = firstLegacyParam(request, ["pp_id"]);
  if (request.nextUrl.searchParams.get("nextjs_handoff") === "1") {
    return new NextResponse(personalPayHandoffHtml(ppId), {
      status: 200,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
      },
    });
  }

  return legacyYoungcartRedirect(
    request,
    ppId ? `/shop/personalpay/${encodeURIComponent(ppId)}/pay` : "/shop/personalpay",
    { drop: ["pp_id"], permanent: false }
  );
}

function personalPayHandoffHtml(ppId: string) {
  const title = "Gnuboard personal payment";
  const message = ppId
    ? "This request has been handed off to the Gnuboard payment endpoint."
    : "Missing personal payment id.";

  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<title>${title}</title>
</head>
<body data-nextjs-handoff="personalpayform" data-pp-id="${escapeHtml(ppId)}">
<main>
<h1>${title}</h1>
<p>${message}</p>
</main>
</body>
</html>`;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}
