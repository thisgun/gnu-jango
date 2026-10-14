"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Home, LayoutGrid, List } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopListView } from "@/hooks/useShopListView";
import type { ShopCategory } from "@/lib/api";
import { g5ShortHref } from "@/lib/g5-short-url";
import { formatNumber } from "@/lib/utils";
import { getShopCategoriesResult } from "@/services/shop";

/** 영카트 list.sort.skin.php 의 정렬 — 값은 이 앱 API 의 정렬 별칭이다. */
export const SHOP_LIST_SORTS = [
  { value: "popular", label: "판매많은순" },
  { value: "price_asc", label: "낮은가격순" },
  { value: "price_desc", label: "높은가격순" },
  { value: "rating", label: "평점높은순" },
  { value: "reviews", label: "후기많은순" },
  { value: "latest", label: "최근등록순" },
];

/** 영카트 분류 코드는 두 자리씩 깊어진다("10" → "1010" → "101010"). */
const CATEGORY_STEP = 2;
const CATEGORY_CACHE_MS = 60_000;

let categoryCache: { at: number; promise: Promise<ShopCategory[]> } | null = null;

function flattenCategories(categories: ShopCategory[]): ShopCategory[] {
  return categories.flatMap((category) => [category, ...flattenCategories(category.children ?? [])]);
}

/** 빵부스러기의 같은 층 분류를 고르려면 전체 분류가 필요하다. 목록 페이지를 오가도 한 번만 받는다. */
function loadAllCategories(): Promise<ShopCategory[]> {
  if (categoryCache && Date.now() - categoryCache.at < CATEGORY_CACHE_MS) return categoryCache.promise;
  const promise = getShopCategoriesResult().then((result) => {
    if (!result.ok) throw new Error(result.error || "분류를 불러오지 못했습니다.");
    return flattenCategories(result.data);
  });
  categoryCache = { at: Date.now(), promise };
  promise.catch(() => {
    if (categoryCache?.promise === promise) categoryCache = null;
  });
  return promise;
}

function useAllShopCategories(): ShopCategory[] {
  const [categories, setCategories] = useState<ShopCategory[]>([]);
  useEffect(() => {
    let alive = true;
    loadAllCategories()
      .then((list) => {
        if (alive) setCategories(list);
      })
      .catch(() => {
        // 받지 못하면 빵부스러기는 현재 분류 이름만 보인다(고르기 메뉴 없이).
      });
    return () => {
      alive = false;
    };
  }, []);
  return categories;
}

function categoryHref(category: ShopCategory) {
  return g5ShortHref(`/shop/categories/${category.ca_id}`);
}

/** 레퍼런스 listcategory.skin.php 는 바로 아래 분류(ca_id 두 자리 더 긴 것)만 보여 준다. */
function directChildren(category: ShopCategory | null | undefined, subcategories: ShopCategory[]): ShopCategory[] {
  if (!category) return subcategories;
  const direct = subcategories.filter((sub) => sub.ca_id.length === category.ca_id.length + CATEGORY_STEP);
  return direct.length > 0 ? direct : subcategories;
}

/**
 * 빵부스러기 한 층 — 영카트 #sct_location 의 select 처럼 이 층의 형제 분류를 펼쳐 보이고, 고르면 그 분류로 간다.
 * 화살표 키를 다루지 않으므로 메뉴(role="menu")가 아니라 펼침 단추 + 링크 목록으로 둔다. Esc 는 닫고 단추로 돌아간다.
 */
function CrumbLevel({ current, siblings }: { current: ShopCategory; siblings: ShopCategory[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (siblings.length <= 1) {
    return <span className="solune-shop-crumb-current">{current.ca_name}</span>;
  }

  return (
    <div className={`solune-shop-crumb-level${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
      >
        {current.ca_name}
        <ChevronDown size={14} aria-hidden />
      </button>
      {open ? (
        <ul id={listId} aria-label={`${current.ca_name} 와 같은 층의 분류`}>
          {siblings.map((sibling) => (
            <li key={sibling.ca_id}>
              <Link href={categoryHref(sibling)} aria-current={sibling.ca_id === current.ca_id ? "page" : undefined}>
                {sibling.ca_name}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** 현재 분류까지의 층들. 각 층은 자기 분류와 그 층의 형제들이다. */
function crumbLevels(category: ShopCategory, all: ShopCategory[]): Array<{ current: ShopCategory; siblings: ShopCategory[] }> {
  const levels: Array<{ current: ShopCategory; siblings: ShopCategory[] }> = [];
  for (let length = CATEGORY_STEP; length <= category.ca_id.length; length += CATEGORY_STEP) {
    const prefix = category.ca_id.slice(0, length);
    const parent = prefix.slice(0, length - CATEGORY_STEP);
    const current = all.find((item) => item.ca_id === prefix) ?? (prefix === category.ca_id ? category : null);
    if (!current) continue;
    const siblings = all.filter((item) => item.ca_id.length === length && item.ca_id.startsWith(parent));
    levels.push({ current, siblings: siblings.length > 0 ? siblings : [current] });
  }
  return levels;
}

function ViewToggle({ view, onChange }: { view: ShopListView; onChange: (view: ShopListView) => void }) {
  return (
    <ul className="solune-shop-viewtoggle" aria-label="목록 모양">
      <li>
        <button type="button" aria-pressed={view === "list"} aria-label="리스트뷰" onClick={() => onChange("list")}>
          <List size={15} aria-hidden />
        </button>
      </li>
      <li>
        <button type="button" aria-pressed={view === "grid"} aria-label="갤러리뷰" onClick={() => onChange("grid")}>
          <LayoutGrid size={15} aria-hidden />
        </button>
      </li>
    </ul>
  );
}

interface ShopListHeaderProps {
  /** 분류가 없을 때(유형별 · 검색 목록)의 제목 */
  title: string;
  category?: ShopCategory | null;
  subcategories?: ShopCategory[];
  total: number;
  sort: string;
  onSortChange: (value: string) => void;
  view: ShopListView;
  onViewChange: (view: ShopListView) => void;
  /** 정렬 줄 위에 놓을 것(유형 칩 등) */
  filters?: ReactNode;
  /** 정렬 줄 오른쪽, 개수 앞에 놓을 것(검색창 등) */
  toolbar?: ReactNode;
}

/**
 * 레퍼런스 상품 목록의 머리(레퍼런스 테마 shop-list-header.tsx 에서 옮김): `<분류> 상품리스트` 제목,
 * #sct_location 의 빵부스러기(집 › 분류 ▾), #sct_ct_1 의 하위 분류 알약(개수 포함), #sct_sortlst 의
 * 정렬 줄과 #sct_lst 의 리스트/갤러리 전환. 모양은 solune-shop.list.css 가 입힌다.
 */
export function ShopListHeader({
  title,
  category = null,
  subcategories = [],
  total,
  sort,
  onSortChange,
  view,
  onViewChange,
  filters,
  toolbar,
}: ShopListHeaderProps) {
  const allCategories = useAllShopCategories();
  const children = directChildren(category, subcategories);
  const levels = category ? crumbLevels(category, allCategories) : [];

  return (
    <>
      <div className="solune-shop-page-title">
        <h1>{category ? `${category.ca_name} 상품리스트` : title}</h1>
      </div>

      <nav className="solune-shop-crumb" aria-label="현재 위치">
        <Link href="/shop" className="solune-shop-crumb-home" aria-label="쇼핑몰 메인으로">
          <Home size={14} aria-hidden />
        </Link>
        {levels.map((level) => (
          <span key={level.current.ca_id} className="solune-shop-crumb-item">
            <ChevronRight size={13} aria-hidden className="solune-shop-crumb-sep" />
            <CrumbLevel current={level.current} siblings={level.siblings} />
          </span>
        ))}
        {!category ? (
          <span className="solune-shop-crumb-item">
            <ChevronRight size={13} aria-hidden className="solune-shop-crumb-sep" />
            <span className="solune-shop-crumb-current">{title}</span>
          </span>
        ) : null}
      </nav>

      {children.length > 0 ? (
        <nav className="solune-shop-subcats" aria-label="하위 상품 분류">
          <ul>
            {children.map((sub) => (
              <li key={sub.ca_id}>
                <Link href={categoryHref(sub)}>
                  {sub.ca_name}
                  {typeof sub.item_count === "number" ? ` (${formatNumber(sub.item_count)})` : ""}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}

      {filters ? <div className="solune-shop-list-filters">{filters}</div> : null}

      <div className="solune-shop-sortbar">
        <ul className="solune-shop-sorts" aria-label="상품 정렬">
          {SHOP_LIST_SORTS.map((option) => (
            <li key={option.value}>
              <button type="button" aria-pressed={sort === option.value} onClick={() => onSortChange(option.value)}>
                {option.label}
              </button>
            </li>
          ))}
        </ul>
        <div className="solune-shop-sort-side">
          {toolbar}
          <span className="sct_nb">총 {formatNumber(total)}개</span>
          <ViewToggle view={view} onChange={onViewChange} />
        </div>
      </div>
    </>
  );
}
