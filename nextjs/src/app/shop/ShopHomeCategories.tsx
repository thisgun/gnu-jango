"use client";

import { useEffect, useRef, useState, type Ref } from "react";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopCategory } from "@/lib/api";
import { assignCategoryIcons } from "@/lib/shop-category-icons";
import { useDynamicSwiper } from "@/lib/use-dynamic-swiper";
import { cn } from "@/lib/utils";
import { getShopHomeData } from "@/services/shop-home";

const demoCategoryMedia = new Map([
  ["문구·기록", { image: "/sample-data/product-01.webp", description: "노트 · 펜" }],
  ["데스크 정리", { image: "/sample-data/product-02.webp", description: "선반 · 매트 · 스탠드" }],
  ["커피·티", { image: "/sample-data/product-05.webp", description: "머그 · 드립 포트" }],
]);

function categoryHref(category: ShopCategory) {
  return `/shop/list-${encodeURIComponent(category.ca_id)}`;
}

function CategoryCards({ categories, demo }: { categories: ShopCategory[]; demo: boolean }) {
  const icons = assignCategoryIcons(categories.map((category) => category.ca_id));
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
      {categories.map((category, index) => {
        const media = demo ? demoCategoryMedia.get(category.ca_name) : undefined;
        const Icon = icons[index];
        return (
          <li key={category.ca_id} className="min-w-0">
            <Link href={categoryHref(category)} className="card group grid min-h-27 grid-cols-[minmax(0,1fr)_5.5rem] items-center gap-2 overflow-hidden rounded-2xl border border-base-300 bg-base-100 p-2 ps-4 text-base-content transition-colors hover:border-base-content/35 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:grid-cols-[minmax(0,1fr)_6rem]">
              <div className="min-w-0 space-y-1">
                <div className="flex items-start gap-1">
                  <span className="text-base font-semibold break-keep">{category.ca_name}</span>
                  <ArrowUpRight size={14} className="mt-1 shrink-0 text-base-content/55" aria-hidden />
                </div>
                {media && <p className="text-xs break-keep text-base-content/70">{media.description}</p>}
                {typeof category.item_count === "number" && (
                  <p className="text-xs text-base-content/65">상품 {category.item_count.toLocaleString("ko-KR")}개</p>
                )}
              </div>
              <div className="relative grid aspect-square place-items-center overflow-hidden rounded-xl bg-base-200" aria-hidden>
                {media ? (
                  <img src={media.image} alt="" width={96} height={96} loading="lazy" decoding="async" className="absolute inset-0 size-full object-cover motion-safe:transition-transform motion-safe:group-hover:scale-105" />
                ) : (
                  <Icon size={30} strokeWidth={1.45} />
                )}
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** 칩 아래 넘김 표시 — 화살표 둘과 끌 수 있는 막대. Swiper 가 서기 전에는 흐린 자리(-reserve)로 둔다. */
function CategoryPager({
  ready,
  prevRef,
  nextRef,
  scrollbarRef,
}: {
  ready: boolean;
  prevRef?: Ref<HTMLButtonElement>;
  nextRef?: Ref<HTMLButtonElement>;
  scrollbarRef?: Ref<HTMLDivElement>;
}) {
  return (
    <div className={cn("solune-catrow-pager", !ready && "solune-catrow-pager-reserve")} aria-hidden={ready ? undefined : true}>
      <button ref={prevRef} type="button" className="solune-catrow-nav solune-catrow-prev" aria-label="이전 분류" tabIndex={ready ? undefined : -1}>
        <ChevronLeft size={16} aria-hidden />
      </button>
      <div ref={scrollbarRef} className="solune-catrow-scrollbar" />
      <button ref={nextRef} type="button" className="solune-catrow-nav solune-catrow-next" aria-label="다음 분류" tabIndex={ready ? undefined : -1}>
        <ChevronRight size={16} aria-hidden />
      </button>
    </div>
  );
}

/**
 * 분류 칩 줄 — 레퍼런스 shop-home-swipers.tsx 의 .solune-catrow-swiper 값 그대로: 좁은 폭 2칸에서
 * 640 · 780 · 1080 · 1280 마다 3 · 4 · 8 · 10칸, 간격 14, 칩 아래에 화살표 둘과 끌 수 있는 막대.
 * 한 줄에 다 들어가면 Swiper 가 막대를 잠그고 CSS 가 통째로 감춘다. 첫 칩은 레퍼런스처럼 강조(is-featured)한다.
 * 키보드로 화면 밖 칩에 초점이 가면 A11y 모듈이 그 칩을 끌어온다(watchSlidesProgress 로 보이는 칩은 그대로).
 */
function ShopCategoryCarousel({ categories }: { categories: ShopCategory[] }) {
  const swiperElRef = useRef<HTMLDivElement>(null);
  const prevRef = useRef<HTMLButtonElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const scrollbarRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const icons = assignCategoryIcons(categories.map((category) => category.ca_id));

  useDynamicSwiper(
    swiperElRef,
    () => ({
      slidesPerView: 2,
      spaceBetween: 14,
      speed: 320,
      watchOverflow: true,
      watchSlidesProgress: true,
      a11y: { prevSlideMessage: "이전 분류", nextSlideMessage: "다음 분류" },
      navigation: { prevEl: prevRef.current, nextEl: nextRef.current },
      scrollbar: { el: scrollbarRef.current, draggable: true, hide: false },
      breakpoints: {
        640: { slidesPerView: 3 },
        780: { slidesPerView: 4 },
        1080: { slidesPerView: 8 },
        1280: { slidesPerView: 10 },
      },
      on: {
        init() {
          setReady(true);
        },
      },
    }),
    [],
    { modules: (modules) => [modules.A11y, modules.Navigation, modules.Scrollbar] }
  );

  return (
    <nav className="ondam-catrow site-container px-0" aria-label="상품 카테고리">
      <div ref={swiperElRef} className="swiper solune-catrow-swiper">
        <div className="swiper-wrapper">
          {categories.map((category, index) => {
            const Icon = icons[index];
            return (
              <div key={category.ca_id} className="swiper-slide">
                <Link href={categoryHref(category)} className={index === 0 ? "is-featured" : undefined}>
                  <span className="ondam-catrow-icon" aria-hidden>
                    <Icon size={22} strokeWidth={1.6} />
                  </span>
                  <span className="ondam-catrow-label">{category.ca_name}</span>
                </Link>
              </div>
            );
          })}
        </div>
      </div>
      <CategoryPager ready={ready} prevRef={prevRef} nextRef={nextRef} scrollbarRef={scrollbarRef} />
    </nav>
  );
}

/**
 * 쇼핑 홈 분류 줄. 서버 모드는 분류를 HTML 에 구워 받고(categories), 정적 내보내기는 브라우저가 쇼핑 홈
 * 묶음(getShopHomeData)에서 받는다. 분류 묶음이 바뀌면 key 로 캐러셀을 새로 세운다.
 */
export function ShopHomeCategories({ categories }: { categories: ShopCategory[] }) {
  const [runtimeCategories, setRuntimeCategories] = useState<ShopCategory[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const visibleCategories = runtimeCategories ?? categories;

  useEffect(() => {
    let active = true;
    getShopHomeData()
      .then((home) => {
        if (active) setRuntimeCategories(home.categories);
      })
      .catch(() => {
        if (active) {
          setRuntimeCategories(categories);
          setUnavailable(categories.length === 0);
        }
      });
    return () => {
      active = false;
    };
    // 처음 붙을 때 한 번 받는다. categories 는 서버가 구운 첫 값이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loading = runtimeCategories === null && categories.length === 0;
  const onlyRoot = visibleCategories.length === 1 ? visibleCategories[0] : undefined;
  const children = onlyRoot?.children ?? [];

  return (
    <section id="shop-categories" className="mx-auto w-full max-w-[1216px] scroll-mt-28 pt-7 pb-3 sm:pt-9" aria-labelledby="shop-categories-title" aria-busy={loading}>
      <h2 id="shop-categories-title" className="mb-3 text-xl! font-bold! tracking-tight sm:text-2xl!">카테고리로 쇼핑하기</h2>
      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3" aria-hidden>
          {Array.from({ length: 3 }, (_, index) => <div key={index} className="skeleton h-27 rounded-2xl" />)}
        </div>
      ) : children.length > 0 ? (
        <CategoryCards categories={children} demo={onlyRoot?.ca_name === "데모 스토어"} />
      ) : visibleCategories.length > 0 ? (
        <ShopCategoryCarousel key={visibleCategories.map((category) => category.ca_id).join(",")} categories={visibleCategories} />
      ) : (
        <p className="rounded-2xl border border-base-300 px-4 py-4 text-sm text-base-content/70">
          {unavailable ? "카테고리를 불러오지 못했습니다." : "등록된 카테고리가 없습니다."}{" "}
          <Link href="/shop/products" className="link">전체 상품 보기</Link>
        </p>
      )}
    </section>
  );
}
