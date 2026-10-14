"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Bike,
  Boxes,
  ChevronLeft,
  ChevronRight,
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
import { getShopCategoriesResult } from "@/services/shop";

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

export function ShopHomeCategories({ categories }: { categories: ShopCategory[] }) {
  const [runtimeCategories, setRuntimeCategories] = useState<ShopCategory[] | null>(null);
  const visibleCategories = runtimeCategories ?? categories;
  const carouselRef = useRef<HTMLDivElement>(null);
  const [scrollPosition, setScrollPosition] = useState({ canGoBack: false, canGoForward: false, progress: 0 });

  useEffect(() => {
    let active = true;
    getShopCategoriesResult({ cache: "no-store" }).then((result) => {
      if (active && result.ok) setRuntimeCategories(result.data);
    });

    return () => { active = false; };
  }, []);

  const updateScrollPosition = () => {
    const element = carouselRef.current;
    if (!element) return;
    const maxScroll = Math.max(0, element.scrollWidth - element.clientWidth);
    const next = {
      canGoBack: element.scrollLeft > 2,
      canGoForward: element.scrollLeft + element.clientWidth < element.scrollWidth - 2,
      progress: maxScroll > 0 ? element.scrollLeft / maxScroll : 0,
    };
    setScrollPosition((current) =>
      current.canGoBack === next.canGoBack &&
      current.canGoForward === next.canGoForward &&
      Math.abs(current.progress - next.progress) < 0.005
        ? current
        : next
    );
  };

  useEffect(() => {
    const element = carouselRef.current;
    if (!element) return;
    updateScrollPosition();
    element.addEventListener("scroll", updateScrollPosition, { passive: true });
    window.addEventListener("resize", updateScrollPosition);
    return () => {
      element.removeEventListener("scroll", updateScrollPosition);
      window.removeEventListener("resize", updateScrollPosition);
    };
  }, [visibleCategories.length]);

  const scrollCarousel = (direction: -1 | 1) => {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    carouselRef.current?.scrollBy({
      left: direction * Math.max(220, (carouselRef.current?.clientWidth ?? 0) * 0.82),
      behavior,
    });
  };

  const handleCarouselKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      scrollCarousel(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      scrollCarousel(1);
    }
  };

  if (visibleCategories.length === 0) return null;

  return (
    <section className="site-container px-0 pb-0 pt-[19px] md:pb-0 md:pt-9" aria-label="상품 카테고리">
      <div
        ref={carouselRef}
        className="carousel carousel-center scrollbar-hide w-full gap-3 overflow-x-auto overscroll-x-contain"
        role="region"
        aria-label="상품 카테고리 목록"
        aria-keyshortcuts="ArrowLeft ArrowRight"
        tabIndex={0}
        onScroll={updateScrollPosition}
        onKeyDown={handleCarouselKeyDown}
      >
        {visibleCategories.map((category, index) => {
          const Icon = categoryIcon(category.ca_name);
          return (
            <Link
              key={category.ca_id}
              href={`/shop/list-${encodeURIComponent(category.ca_id)}`}
              className={`carousel-item card relative h-[126px] min-h-0 w-[min(44vw,154px)] shrink-0 snap-start items-center justify-center gap-2 rounded-box border bg-base-100 px-2 text-center transition-colors md:h-[144px] sm:w-[min(30vw,213px)] lg:w-[91px] ${index === 0 ? "border-success text-success" : "border-base-300 text-base-content hover:border-primary hover:bg-base-200"}`}
            >
              <span className={`flex size-12 items-center justify-center rounded-full border ${index === 0 ? "border-success/40 bg-base-200 text-success" : "border-base-300 bg-base-200 text-base-content"}`}>
                <Icon aria-hidden="true" className="size-5" />
              </span>
              <span className={`line-clamp-1 text-sm font-semibold ${index === 0 ? "text-success" : "text-base-content"}`}>
                {category.ca_name}
              </span>
              {index === 0 && <span aria-hidden="true" className="absolute inset-x-10 bottom-0 h-0.5 rounded-full bg-success" />}
            </Link>
          );
        })}
      </div>
      {(scrollPosition.canGoBack || scrollPosition.canGoForward) && (
        <div className="mt-[18px] flex items-center gap-3" aria-label="카테고리 이동">
          <button
            type="button"
            className="btn btn-circle btn-sm size-9 border border-base-300 bg-base-100 text-base-content"
            aria-label="이전 카테고리"
            disabled={!scrollPosition.canGoBack}
            onClick={() => scrollCarousel(-1)}
          >
            <ChevronLeft aria-hidden="true" className="size-4" />
          </button>
          <div
            className="relative h-1 min-w-0 flex-1 rounded-full bg-base-300"
            role="progressbar"
            aria-label="카테고리 스크롤 위치"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(scrollPosition.progress * 100)}
          >
            <span
              aria-hidden="true"
              className="absolute inset-y-0 left-0 w-[12%] rounded-full bg-success"
              style={{ left: `${scrollPosition.progress * 88}%` }}
            />
          </div>
          <button
            type="button"
            className="btn btn-circle btn-sm size-9 border border-base-300 bg-base-100 text-base-content"
            aria-label="다음 카테고리"
            disabled={!scrollPosition.canGoForward}
            onClick={() => scrollCarousel(1)}
          >
            <ChevronRight aria-hidden="true" className="size-4" />
          </button>
        </div>
      )}
    </section>
  );
}
