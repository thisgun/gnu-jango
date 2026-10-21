import type { CSSProperties } from "react";
import { z } from "zod";

/*
 * 쇼핑몰 진열 설정(관리자 > 쇼핑몰 설정의 영카트 진열 값)을 화면 모양으로 바꾸는 도우미.
 * - 첫 화면 진열 줄: 쇼핑 홈 스냅샷의 display 블록(섹션마다 출력 여부 · PC/모바일 1줄당 수 · 표시 수)
 * - 검색 · 유형별 목록 · 관련상품: 공개 설정의 shop_display 블록(1줄당 수 · 줄 수 · 한 쪽 상품 수)
 * 값이 없거나 이상하면 영카트 설치 기본값을 쓴다 — 예전 서버의 응답도 그대로 그린다.
 */

const MAX_COLS = 8;

const columns = (fallback: number) => z.coerce.number().int().min(1).max(MAX_COLS).catch(fallback);
const count = (fallback: number) => z.coerce.number().int().min(0).catch(fallback);
const flag = z
  .preprocess((value) => (value === "0" || value === 0 ? false : value === "1" || value === 1 ? true : value), z.boolean())
  .catch(true);

const homeSectionSchema = z.object({
  use: flag,
  pc_cols: columns(5),
  pc_count: count(10),
  mobile_cols: columns(2),
  mobile_count: count(8),
});

export type ShopHomeSectionDisplay = z.infer<typeof homeSectionSchema>;

export const DEFAULT_HOME_SECTION_DISPLAY: ShopHomeSectionDisplay = {
  use: true,
  pc_cols: 5,
  pc_count: 10,
  mobile_cols: 2,
  mobile_count: 8,
};

const homeSection = homeSectionSchema.catch(DEFAULT_HOME_SECTION_DISPLAY).default(DEFAULT_HOME_SECTION_DISPLAY);

export type ShopHomeDisplay = Record<`type${1 | 2 | 3 | 4 | 5}`, ShopHomeSectionDisplay>;

export const DEFAULT_HOME_DISPLAY: ShopHomeDisplay = {
  type1: DEFAULT_HOME_SECTION_DISPLAY,
  type2: DEFAULT_HOME_SECTION_DISPLAY,
  type3: DEFAULT_HOME_SECTION_DISPLAY,
  type4: DEFAULT_HOME_SECTION_DISPLAY,
  type5: DEFAULT_HOME_SECTION_DISPLAY,
};

/** 쇼핑 홈 스냅샷의 display 블록. 빠진 섹션 · 블록은 기본값(출력 · 5×2 / 2×4). */
export const shopHomeDisplaySchema = z
  .object({ type1: homeSection, type2: homeSection, type3: homeSection, type4: homeSection, type5: homeSection })
  .catch(DEFAULT_HOME_DISPLAY)
  .default(DEFAULT_HOME_DISPLAY);

const gridSchema = z.object({
  pc_cols: columns(5),
  rows: z.coerce.number().int().min(1).catch(4),
  per_page: z.coerce.number().int().min(1).max(100).catch(20),
  mobile_cols: columns(2),
});

export type ShopGridDisplay = z.infer<typeof gridSchema>;

const DEFAULT_GRID: ShopGridDisplay = { pc_cols: 5, rows: 4, per_page: 20, mobile_cols: 2 };

const relatedSchema = z.object({ use: flag, pc_cols: columns(4), mobile_cols: columns(2) });

export type ShopRelatedDisplay = z.infer<typeof relatedSchema>;

const DEFAULT_RELATED: ShopRelatedDisplay = { use: true, pc_cols: 4, mobile_cols: 2 };

export const DEFAULT_SHOP_LIST_DISPLAY = {
  search: DEFAULT_GRID,
  listtype: DEFAULT_GRID,
  related: DEFAULT_RELATED,
};

export type ShopListDisplay = typeof DEFAULT_SHOP_LIST_DISPLAY;

export const shopListDisplaySchema = z
  .object({
    search: gridSchema.catch(DEFAULT_GRID).default(DEFAULT_GRID),
    listtype: gridSchema.catch(DEFAULT_GRID).default(DEFAULT_GRID),
    related: relatedSchema.catch(DEFAULT_RELATED).default(DEFAULT_RELATED),
  })
  .catch(DEFAULT_SHOP_LIST_DISPLAY);

/** 공개 설정의 shop_display 를 읽는다. 없으면(예전 서버 · 불러오기 실패) 기본값. */
export function shopListDisplayOf(settings: { shop_display?: ShopListDisplay } | null | undefined): ShopListDisplay {
  return settings?.shop_display ?? DEFAULT_SHOP_LIST_DISPLAY;
}

/**
 * 폰 → 넓은 화면 네 단계의 칸 수. 끝은 모바일 · PC 설정 값이고 사이 둘은 그 사이를 고르게 나눈다
 * (기본 2 · 5 이면 2 · 3 · 4 · 5 — 설정 전의 칸 수와 같다).
 */
export function columnSteps(mobileCols: number, pcCols: number): [number, number, number, number] {
  const step = (part: number) => mobileCols + Math.round(((pcCols - mobileCols) * part) / 3);
  return [mobileCols, step(1), step(2), pcCols];
}

type CustomProperties = CSSProperties & Record<`--${string}`, string | number>;

/** 진열 줄(가로 넘김)의 한 화면 칸 수. peek 이면 마지막 한 장을 반쯤 걸친다(+0.5). */
export function shopRowStyle(display: ShopHomeSectionDisplay, peek: boolean): CustomProperties {
  const extra = peek ? 0.5 : 0;
  const [xs, sm, md, lg] = columnSteps(display.mobile_cols, display.pc_cols);
  return {
    "--solune-row-spv-xs": xs + extra,
    "--solune-row-spv-sm": sm + extra,
    "--solune-row-spv-md": md + extra,
    "--solune-row-spv-lg": lg + extra,
  };
}

/** 진열 줄의 index 번째 상품이 폰(모바일 수) · 넓은 화면(PC 수) 중 어디서 빠지는지 — CSS 가 감춘다. */
export function shopRowItemClass(index: number, display: ShopHomeSectionDisplay): string | undefined {
  const classes = [
    index >= display.mobile_count ? "solune-row-item--hide-mobile" : "",
    index >= display.pc_count ? "solune-row-item--hide-pc" : "",
  ].filter(Boolean);
  return classes.length ? classes.join(" ") : undefined;
}

/** 진열 줄에 실을 상품 수 — 두 화면 중 큰 쪽(서버도 그만큼만 보낸다). */
export function shopRowLimit(display: ShopHomeSectionDisplay): number {
  return Math.max(display.pc_count, display.mobile_count);
}

/** 상품 격자(검색 · 유형별 목록 · 관련상품)의 칸 수 — solune-shop.display.css 가 단계별로 쓴다. */
export function shopGridStyle(mobileCols: number, pcCols: number): CustomProperties {
  const [xs, sm, md, lg] = columnSteps(mobileCols, pcCols);
  return {
    "--shop-grid-cols-xs": xs,
    "--shop-grid-cols-sm": sm,
    "--shop-grid-cols-md": md,
    "--shop-grid-cols-lg": lg,
  };
}

const categoryGridSchema = z.object({
  configured: z.boolean().catch(false),
  pc_cols: columns(4),
  rows: z.coerce.number().int().min(1).catch(5),
  per_page: z.coerce.number().int().min(1).max(100).catch(20),
  mobile_cols: columns(2),
});

export type ShopCategoryGridDisplay = z.infer<typeof categoryGridSchema>;

/**
 * 분류 목록 격자(관리자 > 분류 출력설정의 1줄당 이미지 수 · 줄 수). 값을 정한 분류만 돌려준다 —
 * 정하지 않은 분류 · 예전 서버 응답은 null 이고 화면은 기본 격자(2 · 3 · 4칸, 20개)를 그대로 쓴다.
 */
export function shopCategoryGridOf(category: { list_display?: unknown } | null | undefined): ShopCategoryGridDisplay | null {
  const parsed = categoryGridSchema.safeParse(category?.list_display);
  return parsed.success && parsed.data.configured ? parsed.data : null;
}
