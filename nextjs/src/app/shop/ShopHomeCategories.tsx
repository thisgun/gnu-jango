"use client";

import { useEffect, useRef, useState, type Ref } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopCategory } from "@/lib/api";
import { assignCategoryIcons } from "@/lib/shop-category-icons";
import { useDynamicSwiper } from "@/lib/use-dynamic-swiper";
import { cn } from "@/lib/utils";
import { getShopHomeData } from "@/services/shop-home";

/* 분류 칩 자리 수 — 넓은 화면의 한 화면 칸 수(10)보다 많게 두어 넘김 막대 자리도 잡는다. */
const CATEGORY_SKELETON_CHIPS = 12;

function categoryHref(category: ShopCategory) {
  return `/shop/list-${encodeURIComponent(category.ca_id)}`;
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

/** 분류를 받는 동안의 자리 — 진짜 줄과 같은 마크업 · 클래스라 응답 뒤에 아래 진열이 밀리지 않는다. */
function ShopCategoryRowSkeleton() {
  return (
    <div className="ondam-catrow site-container px-0" aria-hidden="true">
      <div className="swiper solune-catrow-swiper">
        <div className="swiper-wrapper">
          {Array.from({ length: CATEGORY_SKELETON_CHIPS }, (_, index) => (
            <div key={index} className="swiper-slide">
              <a>
                <span className="ondam-catrow-icon skeleton" />
                <span className="ondam-catrow-label">
                  <span className={cn("skeleton inline-block h-3 align-middle", index % 2 === 0 ? "w-12" : "w-9")} />
                </span>
              </a>
            </div>
          ))}
        </div>
      </div>
      <CategoryPager ready={false} />
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
  const visibleCategories = runtimeCategories ?? categories;

  useEffect(() => {
    let active = true;
    getShopHomeData()
      .then((home) => {
        if (active) setRuntimeCategories(home.categories);
      })
      .catch(() => {
        // 받지 못하면 서버가 구운 분류로 둔다(없으면 줄을 감춘다).
        if (active) setRuntimeCategories((current) => current ?? categories);
      });
    return () => {
      active = false;
    };
    // 처음 붙을 때 한 번 받는다. categories 는 서버가 구운 첫 값이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (runtimeCategories === null && categories.length === 0) return <ShopCategoryRowSkeleton />;
  if (visibleCategories.length === 0) return null;

  return (
    <ShopCategoryCarousel
      key={visibleCategories.map((category) => category.ca_id).join(",")}
      categories={visibleCategories}
    />
  );
}
