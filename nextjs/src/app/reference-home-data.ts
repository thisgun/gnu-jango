import { GALLERY_BOARDS } from "@/lib/config";
import type { PopularKeyword, VisitStats } from "@/lib/schemas";
import type { Board, FaqItem, Poll, RecentItem, WritePost } from "@/lib/types";
import { getBoardPosts, getBoards } from "@/services/boards";
import { getFaqs } from "@/services/faqs";
import { getCurrentPoll } from "@/services/polls";
import { getRecentItems } from "@/services/recent";
import { getPopularKeywords } from "@/services/search";
import { getClientPublicSettings, getPublicSettings } from "@/services/settings";

export type ReferenceBoardPanel = { board: Board; posts: WritePost[] };
export type ReferenceGallery = { board: Board; posts: WritePost[] };

export type ReferenceHomeData = {
  boardPanels: ReferenceBoardPanel[];
  comments: RecentItem[];
  faqs: FaqItem[];
  gallery: ReferenceGallery | null;
  popularKeywords: PopularKeyword[];
  poll: Poll | null;
  visit: VisitStats | null;
  rewriteMode: number | string | null;
};

export const EMPTY_REFERENCE_HOME: ReferenceHomeData = {
  boardPanels: [],
  comments: [],
  faqs: [],
  gallery: null,
  popularKeywords: [],
  poll: null,
  visit: null,
  rewriteMode: 0,
};

const BOARD_PANEL_LIMIT = 3;
const BOARD_ROW_LIMIT = 5;
const GALLERY_LIMIT = 8;
const FAQ_LIMIT = 4;
const COMMENT_LIMIT = 6;
const POPULAR_LIMIT = 5;

function boardsWithPostsFirst(boards: Board[]): Board[] {
  const populated = boards.filter((board) => (board.post_count ?? 0) > 0);
  const ordered = (populated.length ? populated : boards)
    .slice()
    .sort((a, b) => (b.post_count ?? 0) - (a.post_count ?? 0));
  const seenSubjects = new Set<string>();
  return ordered.filter((board) => {
    const subject = (board.bo_subject || board.bo_table).trim().toLowerCase();
    if (seenSubjects.has(subject)) return false;
    seenSubjects.add(subject);
    return true;
  });
}

export async function loadReferenceHomeData(): Promise<ReferenceHomeData> {
  const [boards, settings, faqResult, recentComments, pollResult, popularKeywords] = await Promise.all([
    getBoards(),
    // In the browser the header, footer and rail read the same settings: share their one request.
    typeof window === "undefined" ? getPublicSettings() : getClientPublicSettings(),
    getFaqs({ perPage: FAQ_LIMIT }),
    getRecentItems({ view: "c", limit: COMMENT_LIMIT }),
    getCurrentPoll(),
    getPopularKeywords(POPULAR_LIMIT),
  ]);

  const configuredHomeTables = (settings.cf_home_boards ?? "")
    .split(",")
    .map((table) => table.trim())
    .filter(Boolean);
  const configuredGalleryTable = settings.cf_home_gallery?.trim() ?? "";
  const configuredGalleryTables = [configuredGalleryTable, ...GALLERY_BOARDS].filter(Boolean);
  const galleryCandidates = [
    ...configuredGalleryTables,
    ...boards
      .filter((board) => /gallery|갤러리/i.test(`${board.bo_table} ${board.bo_subject} ${board.bo_skin}`))
      .map((board) => board.bo_table),
  ];
  const galleryTableSet = new Set(galleryCandidates);
  const matchingGalleryBoards = boards.filter((board) => galleryTableSet.has(board.bo_table));
  const galleryBoard = configuredGalleryTable
    ? matchingGalleryBoards.find((board) => board.bo_table === configuredGalleryTable) ?? null
    : matchingGalleryBoards.find((board) => (board.post_count ?? 0) > 0) ?? matchingGalleryBoards[0];

  const regularBoards = boards.filter((board) => !galleryTableSet.has(board.bo_table));
  const boardsByTable = new Map(regularBoards.map((board) => [board.bo_table, board]));
  const configuredPanelBoards = configuredHomeTables
    .map((table) => boardsByTable.get(table))
    .filter((board): board is Board => Boolean(board));
  const panelBoards = (configuredPanelBoards.length
    ? configuredPanelBoards
    : boardsWithPostsFirst(regularBoards)
  ).slice(0, BOARD_PANEL_LIMIT);
  const boardPanels = await Promise.all(
    panelBoards.map(async (board) => {
      const { list } = await getBoardPosts({ boTable: board.bo_table, perPage: BOARD_ROW_LIMIT });
      return { board, posts: list.slice(0, BOARD_ROW_LIMIT) };
    })
  );

  let gallery: ReferenceGallery | null = null;
  if (galleryBoard) {
    const { list } = await getBoardPosts({ boTable: galleryBoard.bo_table, perPage: GALLERY_LIMIT });
    const posts = list.filter((post) => Boolean(post.thumbnail || post.images?.[0])).slice(0, GALLERY_LIMIT);
    gallery = { board: galleryBoard, posts };
  }

  return {
    boardPanels,
    comments: recentComments.items,
    faqs: faqResult.ok ? faqResult.data.items.slice(0, FAQ_LIMIT) : [],
    gallery,
    popularKeywords,
    poll: pollResult.ok ? pollResult.data : null,
    visit: settings.visit ?? null,
    rewriteMode: settings.cf_bbs_rewrite ?? 0,
  };
}
