import { NextResponse } from "next/server";
import { appShortUrl } from "@/lib/g5-short-url";
import { htmlToPlainText } from "@/lib/sanitize";
import { getBoard, getBoardPosts, getBoards } from "@/services/boards";
import { getPublicSettings } from "@/services/settings";
import { boardPostPath } from "@/lib/board-url";

export const dynamic = "force-static";
export const dynamicParams = true;

export async function generateStaticParams() {
  const params = [{ bo_table: "__g5_static__" }];

  try {
    const boards = await getBoards(300);
    const seen = new Set(params.map(({ bo_table }) => bo_table));

    for (const board of boards) {
      if (!board.bo_table || seen.has(board.bo_table)) continue;
      seen.add(board.bo_table);
      params.push({ bo_table: board.bo_table });
    }
  } catch {
    // Keep the sentinel feed when the API is unavailable during static builds.
  }

  return params;
}

interface RssPost {
  wr_id: number;
  wr_subject: string;
  wr_seo_title?: string;
  wr_content: string;
  wr_name: string;
  mb_nick?: string;
  wr_datetime: string;
}

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ bo_table: string }> }
) {
  const { bo_table } = await params;

  try {
    const board = await getBoard(bo_table, 60);
    if (!board || board.bo_use_rss_view !== 1 || board.bo_read_level >= 2) {
      return new NextResponse("RSS feed not found", {
        status: 404,
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "public, max-age=60, s-maxage=60",
        },
      });
    }

    const [postsResult, settings] = await Promise.all([
      getBoardPosts({ boTable: bo_table, perPage: 20, revalidate: 60 }),
      getPublicSettings(60),
    ]);

    const boardName = board.bo_subject || bo_table;
    const boardDesc = board.bo_content || "";
    const posts: RssPost[] = postsResult.list;

    const items = posts
      .map((post) => {
        const link = appShortUrl(boardPostPath(bo_table, post, settings.cf_bbs_rewrite));
        const author = escapeXml(post.mb_nick || post.wr_name || "");
        const description = escapeXml(
          htmlToPlainText(post.wr_content).slice(0, 300)
        );
        const pubDate = new Date(post.wr_datetime).toUTCString();

        return `    <item>
      <title>${escapeXml(post.wr_subject)}</title>
      <link>${link}</link>
      <guid isPermaLink="true">${link}</guid>
      <description>${description}</description>
      <author>${author}</author>
      <pubDate>${pubDate}</pubDate>
    </item>`;
      })
      .join("\n");

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${escapeXml(boardName)}</title>
    <link>${appShortUrl(`/boards/${bo_table}`)}</link>
    <description>${escapeXml(boardDesc)}</description>
    <language>ko-KR</language>
    <atom:link href="${appShortUrl(`/boards/${bo_table}/rss`)}" rel="self" type="application/rss+xml"/>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
${items}
  </channel>
</rss>`;

    return new NextResponse(xml, {
      status: 200,
      headers: {
        "Content-Type": "application/rss+xml; charset=utf-8",
        "Cache-Control": "public, max-age=60, s-maxage=60",
      },
    });
  } catch {
    const errorXml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Error</title>
    <description>Failed to generate RSS feed</description>
  </channel>
</rss>`;

    return new NextResponse(errorXml, {
      status: 500,
      headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
    });
  }
}
