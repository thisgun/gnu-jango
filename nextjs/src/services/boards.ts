import { apiUrl } from "@/lib/config";
import { fetchApiResult, type ApiResult } from "@/lib/api-response";
import {
  boardListSchema,
  boardSchema,
  postDetailSchema,
  writePostListSchema,
} from "@/lib/schemas";
import type { Board, Comment, PostFile, WritePost } from "@/lib/types";

export interface PostNavItem {
  wr_id: number;
  wr_subject: string;
  wr_seo_title?: string;
}

export interface PostDetail extends WritePost {
  files?: PostFile[];
  comments?: Comment[];
  prev_post?: PostNavItem | null;
  next_post?: PostNavItem | null;
}

export interface GetBoardsOptions {
  revalidate?: number;
  group?: string;
}

export function getBoardsResult(options: number | GetBoardsOptions = 30) {
  const revalidate = typeof options === "number" ? options : options.revalidate ?? 30;
  const group = typeof options === "number" ? "" : options.group?.trim() ?? "";
  const params = new URLSearchParams();
  if (group) params.set("group", group);

  const suffix = params.toString() ? `?${params.toString()}` : "";

  return fetchApiResult(apiUrl(`/boards${suffix}`), boardListSchema, {
    next: { revalidate },
  });
}

export async function getBoards(options: number | GetBoardsOptions = 30): Promise<Board[]> {
  const result = await getBoardsResult(options);
  return result.ok ? result.data : [];
}

export function getBoardResult(boTable: string, revalidate = 30) {
  return fetchApiResult(apiUrl(`/boards/${boTable}`), boardSchema, {
    next: { revalidate },
  });
}

export async function getBoard(boTable: string, revalidate = 30): Promise<Board | null> {
  const result = await getBoardResult(boTable, revalidate);
  return result.ok ? result.data : null;
}

export async function getBoardPosts({
  boTable,
  page,
  perPage,
  sfl,
  stx,
  sca,
  revalidate = 30,
}: {
  boTable: string;
  page?: number;
  perPage?: number;
  sfl?: string;
  stx?: string;
  sca?: string;
  revalidate?: number;
}): Promise<{
  list: WritePost[];
  total: number;
  totalPage: number;
  noticeCount: number;
  totalNoticeCount: number;
  error?: string;
}> {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (perPage) params.set("per_page", String(perPage));
  if (sfl) params.set("sfl", sfl);
  if (stx) params.set("stx", stx);
  if (sca) params.set("sca", sca);

  const suffix = params.toString() ? `?${params.toString()}` : "";
  const result = await fetchApiResult(
    apiUrl(`/boards/${boTable}/posts${suffix}`),
    writePostListSchema,
    { next: { revalidate } }
  );

  if (!result.ok) {
    return {
      list: [],
      total: 0,
      totalPage: 1,
      noticeCount: 0,
      totalNoticeCount: 0,
      error: result.error,
    };
  }

  return {
    list: result.data,
    total: result.meta?.total ?? 0,
    totalPage: result.meta?.last_page ?? 1,
    noticeCount: result.meta?.notice_count ?? 0,
    totalNoticeCount: result.meta?.total_notice_count ?? result.meta?.notice_count ?? 0,
  };
}

export async function getPostDetailResult({
  boTable,
  wrId,
  token,
}: {
  boTable: string;
  wrId: string;
  token?: string;
}): Promise<ApiResult<PostDetail>> {
  const result = await fetchApiResult(
    apiUrl(`/posts/${boTable}/${wrId}`),
    postDetailSchema,
    {
      ...(token ? { cache: "no-store" as const } : { next: { revalidate: 30 } }),
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }
  );

  return result.ok ? { ...result, data: result.data as unknown as PostDetail } : result;
}

export async function getPostDetail({
  boTable,
  wrId,
  token,
}: {
  boTable: string;
  wrId: string;
  token?: string;
}): Promise<PostDetail | null> {
  const result = await getPostDetailResult({ boTable, wrId, token });
  return result.ok ? result.data : null;
}

export async function getPostDetailBySeoResult({
  boTable,
  slug,
}: {
  boTable: string;
  slug: string;
}): Promise<ApiResult<PostDetail>> {
  const result = await fetchApiResult(
    apiUrl(`/posts/${boTable}/seo/${encodeURIComponent(slug)}`),
    postDetailSchema,
    { next: { revalidate: 30 } }
  );

  return result.ok ? { ...result, data: result.data as unknown as PostDetail } : result;
}

export async function getPostDetailBySeo({
  boTable,
  slug,
}: {
  boTable: string;
  slug: string;
}): Promise<PostDetail | null> {
  const result = await getPostDetailBySeoResult({ boTable, slug });
  return result.ok ? result.data : null;
}
