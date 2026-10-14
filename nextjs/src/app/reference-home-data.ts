import { z } from "zod";
import {
  boardSchema, faqItemSchema, pollSchema, popularKeywordListSchema,
  publicSettingsSchema, recentItemListSchema, writePostListSchema,
} from "@/lib/schemas";
import type { PopularKeyword, VisitStats } from "@/lib/schemas";
import type { Board, FaqItem, Poll, RecentItem, WritePost } from "@/lib/types";
import { getPageBootstrap } from "@/services/page-bootstrap";

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

const homeSchema = z.object({
  boardPanels: z.array(z.object({ board: boardSchema, posts: writePostListSchema })),
  comments: recentItemListSchema,
  faqs: faqItemSchema.array(),
  gallery: z.object({ board: boardSchema, posts: writePostListSchema }).nullable(),
  popularKeywords: popularKeywordListSchema,
  poll: pollSchema.nullable(),
  visit: publicSettingsSchema.shape.visit.nullish().transform(value => value ?? null),
  rewriteMode: z.union([z.number(), z.string()]).nullable(),
});

export async function loadReferenceHomeData(): Promise<ReferenceHomeData> {
  return homeSchema.parse(await getPageBootstrap("community"));
}
