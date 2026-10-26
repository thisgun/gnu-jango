"use client";

import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  Bike,
  Boxes,
  Coffee,
  Gem,
  House,
  LampDesk,
  PencilLine,
  Shirt,
  Sparkles,
  Utensils,
} from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopCategory } from "@/lib/api";
import { getShopHomeData } from "@/services/shop-home";

const categoryIcons: Array<[RegExp, LucideIcon]> = [
  [/의류|패션|옷|팬츠|상의|하의|티셔츠/i, Shirt],
  [/주방|식품|푸드|식기|요리/i, Utensils],
  [/문구|펜|사무|테스트/i, PencilLine],
  [/가구|리빙|홈|생활/i, House],
  [/커피|음료|차|카페/i, Coffee],
  [/조명|램프|등/i, LampDesk],
  [/자전거|스포츠|레저/i, Bike],
  [/주얼리|보석|액세서리/i, Gem],
  [/뷰티|화장품|케어/i, Sparkles],
];

function categoryIcon(name: string) {
  return categoryIcons.find(([pattern]) => pattern.test(name))?.[1] ?? Boxes;
}

function categoryGridColumns(count: number) {
  if (count <= 1) return "grid-cols-1";
  if (count === 2) return "grid-cols-2";
  if (count === 3) return "grid-cols-2 sm:grid-cols-3";
  if (count === 4) return "grid-cols-2 sm:grid-cols-4";
  if (count === 5) return "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5";
  return "grid-cols-2 sm:grid-cols-3 lg:grid-cols-6";
}

export function ShopHomeCategories({ categories }: { categories: ShopCategory[] }) {
  const [runtimeCategories, setRuntimeCategories] = useState<ShopCategory[] | null>(null);
  const visibleCategories = runtimeCategories ?? categories;
  useEffect(() => {
    let active = true;
    getShopHomeData().then((home) => {
      if (active) setRuntimeCategories(home.categories);
    }).catch(() => undefined);

    return () => { active = false; };
  }, []);

  if (visibleCategories.length === 0) return null;
  const singleCategory = visibleCategories.length === 1;

  return (
    <section className="site-container px-0 pb-0 pt-[19px] md:pb-0 md:pt-9" aria-label="상품 카테고리">
      <div
        className={`grid w-full gap-3 ${categoryGridColumns(visibleCategories.length)}`}
        role="group"
        aria-label="상품 카테고리 목록"
      >
        {visibleCategories.map((category, index) => {
          const Icon = categoryIcon(category.ca_name);
          return (
            <Link
              key={category.ca_id}
              href={`/shop/list-${encodeURIComponent(category.ca_id)}`}
              className={`card relative w-full min-w-0 rounded-box border bg-base-100 transition-colors ${singleCategory ? "col-span-full h-[112px] flex-row justify-between px-5 text-left md:h-[120px]" : "min-h-[126px] items-center justify-center gap-2 px-2 text-center md:min-h-[144px]"} ${index === 0 ? "border-success text-success" : "border-base-300 text-base-content hover:border-primary hover:bg-base-200"}`}
            >
              <span className={`flex min-w-0 items-center ${singleCategory ? "gap-4" : "flex-col gap-2"}`}>
                <span className={`flex size-12 shrink-0 items-center justify-center rounded-full border ${index === 0 ? "border-success/40 bg-base-200 text-success" : "border-base-300 bg-base-200 text-base-content"}`}>
                  <Icon aria-hidden="true" className="size-5" />
                </span>
                <span className={singleCategory ? "min-w-0" : "text-center"}>
                  <span className={`block line-clamp-1 text-sm font-semibold ${index === 0 ? "text-success" : "text-base-content"}`}>
                    {category.ca_name}
                  </span>
                  {singleCategory && (
                    <span className="mt-1 block text-xs text-base-content/60">
                      {typeof category.item_count === "number" ? `${category.item_count.toLocaleString()}개 상품을 둘러보세요.` : "상품을 둘러볼 분류입니다."}
                    </span>
                  )}
                </span>
              </span>
              {singleCategory && <ArrowRight aria-hidden="true" className="size-5 shrink-0 text-base-content/60" />}
              {index === 0 && <span aria-hidden="true" className={`absolute bottom-0 h-0.5 rounded-full bg-success ${singleCategory ? "inset-x-5" : "inset-x-10"}`} />}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
