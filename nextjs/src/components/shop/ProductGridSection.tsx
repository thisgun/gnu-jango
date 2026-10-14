"use client";

import { G5Link as Link } from "@/components/ui/g5-link";
import Image from "next/image";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, GitCompare, PackageSearch, ShoppingCart, Star } from "lucide-react";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { g5ShortHref } from "@/lib/g5-short-url";
import { shouldBypassImageOptimization } from "@/lib/image";
import { shopProductHref } from "@/lib/product-url";
import { toastError, toastSuccess } from "@/lib/toast";
import { formatPrice } from "@/lib/utils";
import { notifyCartChanged } from "@/lib/cart-events";
import { addCartItem } from "@/services/cart";
import { useCompareStore } from "@/store/compare";
import {
  hasPurchasableShopBaseOption,
  hasShopBaseOptions,
  ProductCardOptionPicker,
} from "./ProductCardOptionPicker";

const PRODUCT_TYPE_BADGES = [
  { key: "it_type1", label: "히트", colorClass: "badge-info" },
  { key: "it_type2", label: "추천", colorClass: "badge-warning" },
  { key: "it_type3", label: "최신", colorClass: "badge-success" },
  { key: "it_type4", label: "인기", colorClass: "badge-primary" },
  { key: "it_type5", label: "할인", colorClass: "badge-error" },
] as const;

export function ProductTypeBadges({
  product,
  className = "",
}: {
  product: ShopProduct;
  className?: string;
}) {
  const activeBadges = [
    ...PRODUCT_TYPE_BADGES.filter(({ key }) => product[key] === "1"),
    ...(product.has_coupon ? [{ key: "coupon", label: "쿠폰", colorClass: "badge-error" }] : []),
  ];
  if (activeBadges.length === 0) return null;

  return (
    <div
      className={`flex flex-wrap items-center gap-1 ${className}`.trim()}
      role="group"
      aria-label="상품 종류"
    >
      {activeBadges.map(({ key, label, colorClass }) => (
        <span key={key} className={`badge badge-sm ${colorClass}`}>
          {label}
        </span>
      ))}
    </div>
  );
}

export function ProductCard({
  product,
  priority = false,
  productRewriteMode,
}: {
  product: ShopProduct;
  priority?: boolean;
  productRewriteMode?: BbsRewriteMode;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const [addingToCart, setAddingToCart] = useState(false);
  const isTelInquiry = String(product.it_tel_inq ?? "0") === "1";
  const hasDiscount =
    !isTelInquiry &&
    product.it_price > 0 &&
    product.it_cust_price > 0 && product.it_cust_price > product.it_price;
  const discountPercent = hasDiscount
    ? Math.round(((product.it_cust_price - product.it_price) / product.it_cust_price) * 100)
    : 0;
  const showImage = Boolean(product.image_url && !imageFailed);
  const href = shopProductHref(product, productRewriteMode);
  const hasBaseOptions = hasShopBaseOptions(product);
  const canSelectBaseOption = hasPurchasableShopBaseOption(product);
  const minQuantity = Math.max(1, Number(product.it_buy_min_qty || 1));
  const canQuickAdd =
    !hasBaseOptions &&
    !isTelInquiry &&
    product.it_soldout !== "1" &&
    product.it_stock_qty >= minQuantity;

  const handleQuickAdd = async () => {
    if (!canQuickAdd || addingToCart) return;
    setAddingToCart(true);
    try {
      await addCartItem(product.it_id, minQuantity);
      notifyCartChanged();
      toastSuccess("장바구니에 담았습니다.");
    } catch (error) {
      toastError(error instanceof Error ? error.message : "장바구니에 담지 못했습니다.");
    } finally {
      setAddingToCart(false);
    }
  };

  return (
    <div className="product-card group relative">
      <Link href={href} className="flex flex-1 flex-col gap-1.5">
        <div className="product-image-shell">
          {showImage ? (
            <Image
              src={product.image_url}
              alt={product.it_name}
              fill
              className="object-cover transition-transform duration-150 ease-in-out group-hover:scale-[1.03]"
              sizes="(max-width: 639px) 32vw, (max-width: 1023px) 22vw, 18vw"
              unoptimized={shouldBypassImageOptimization(product.image_url)}
              priority={priority}
              onError={() => setImageFailed(true)}
            />
          ) : (
            <div className="product-placeholder">
              <PackageSearch aria-hidden="true" className="size-7" />
              <span>상품 이미지 없음</span>
            </div>
          )}
        </div>
        <p className="mt-3 min-h-4 truncate text-xs font-medium text-muted-foreground">
          {product.ca_name || "\u00A0"}
        </p>
        <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5 text-base-content group-hover:text-primary">
          {product.it_name}
        </h3>
        {(product.review_count ?? 0) > 0 && (
          <div
            className="flex items-center gap-1 text-xs text-base-content/65"
            aria-label={`평점 ${product.review_avg ?? 0}점, 후기 ${product.review_count}개`}
          >
            <Star aria-hidden="true" className="size-3.5 fill-warning text-warning" />
            <span className="font-semibold text-base-content">{(product.review_avg ?? 0).toFixed(1)}</span>
            <span>({product.review_count})</span>
          </div>
        )}
        <div className="mt-auto">
          <div className="flex items-center gap-2">
            {hasDiscount && (
              <span className="text-sm font-black text-warning">{discountPercent}%</span>
            )}
            <span className="text-base font-black text-base-content">
              {isTelInquiry ? "전화문의" : formatPrice(product.it_price)}
            </span>
          </div>
          <span
            className={`block min-h-4 text-xs text-muted-foreground ${
              hasDiscount && !isTelInquiry ? "line-through" : ""
            }`}
          >
            {hasDiscount && !isTelInquiry ? formatPrice(product.it_cust_price) : "\u00A0"}
          </span>
        </div>
        <ProductTypeBadges product={product} className="mt-1" />
      </Link>
      {hasBaseOptions && canSelectBaseOption && !isTelInquiry && product.it_soldout !== "1" ? (
        <ProductCardOptionPicker product={product} />
      ) : canQuickAdd ? (
        <button
          type="button"
          className="btn btn-outline btn-primary btn-sm mt-2 min-h-10 w-full"
          disabled={addingToCart}
          aria-label={`${product.it_name} 장바구니 담기`}
          onClick={() => void handleQuickAdd()}
        >
          <ShoppingCart aria-hidden="true" className="size-4" />
          {addingToCart ? "담는 중…" : "장바구니 담기"}
        </button>
      ) : null}
      <CompareToggleButton product={product} />
    </div>
  );
}

export function CompareToggleButton({ product }: { product: ShopProduct }) {
  const { isCompared, add, remove } = useCompareStore();
  const active = isCompared(product.it_id);

  return (
    <button
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        if (active) {
          remove(product.it_id);
          return;
        }

        const ok = add({
          it_id: product.it_id,
          it_name: product.it_name,
          it_price: product.it_price,
          it_cust_price: product.it_cust_price,
          it_tel_inq: product.it_tel_inq,
          image_url: product.image_url,
          ca_name: product.ca_name,
          it_brand: product.it_brand,
          it_seo_title: product.it_seo_title,
        });

        if (!ok) {
          toastError("최대 4개까지 비교할 수 있습니다.");
          return;
        }

        toastSuccess("비교 목록에 추가했습니다.");
      }}
      className={
        "absolute right-2 top-2 z-10 rounded-full p-1.5 transition-colors " +
        (active
          ? "bg-primary text-primary-foreground"
          : "bg-base-100/95 text-muted-foreground opacity-0 shadow-[0_1px_3px_rgba(15,23,42,0.14)] group-hover:opacity-100")
      }
      title={active ? "비교 해제" : "비교 추가"}
      aria-label={active ? "비교 해제" : "비교 추가"}
    >
      <GitCompare className="h-3.5 w-3.5" />
    </button>
  );
}

export function ProductGridSection({
  title,
  eyebrow,
  products,
  viewAllHref,
  viewAllLabel = "더보기",
  scroll = false,
  compactCarousel = false,
  subtitle,
  className = "home-product-section",
  productRewriteMode,
}: {
  title: string;
  eyebrow?: string;
  products: ShopProduct[];
  viewAllHref: string;
  viewAllLabel?: string;
  scroll?: boolean;
  compactCarousel?: boolean;
  subtitle?: string;
  className?: string;
  productRewriteMode?: BbsRewriteMode;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollPosition, setScrollPosition] = useState({ canGoBack: false, canGoForward: false });

  const updateScrollPosition = () => {
    const element = scrollRef.current;
    if (!element) return;
    const next = {
      canGoBack: element.scrollLeft > 2,
      canGoForward: element.scrollLeft + element.clientWidth < element.scrollWidth - 2,
    };
    setScrollPosition((current) =>
      current.canGoBack === next.canGoBack && current.canGoForward === next.canGoForward
        ? current
        : next
    );
  };

  useEffect(() => {
    if (!scroll) return;
    const element = scrollRef.current;
    if (!element) return;
    updateScrollPosition();
    element.addEventListener("scroll", updateScrollPosition, { passive: true });
    window.addEventListener("resize", updateScrollPosition);
    return () => {
      element.removeEventListener("scroll", updateScrollPosition);
      window.removeEventListener("resize", updateScrollPosition);
    };
  }, [scroll, products.length]);

  const scrollProducts = (direction: -1 | 1) => {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    scrollRef.current?.scrollBy({
      left: direction * Math.max(220, (scrollRef.current?.clientWidth ?? 0) * 0.82),
      behavior,
    });
  };

  const handleCarouselKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!scroll || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    scrollProducts(event.key === "ArrowLeft" ? -1 : 1);
  };

  if (products.length === 0) return null;

  const sectionClassName = compactCarousel
    ? `${className} shop-home-product-row`
    : className;

  return (
    <section className={sectionClassName}>
      <div className="home-product-head">
        <div>
          {eyebrow && <p className="home-product-eyebrow">{eyebrow}</p>}
          <h2 className="home-product-title">{title}</h2>
          {subtitle && <p className="home-product-subtitle">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {scroll && (scrollPosition.canGoBack || scrollPosition.canGoForward) ? (
            <>
              <button
                type="button"
                className="home-product-scroll-button btn btn-ghost btn-sm btn-square"
                aria-label={`${title} 이전 상품`}
                disabled={!scrollPosition.canGoBack}
                onClick={() => scrollProducts(-1)}
              >
                <ChevronLeft aria-hidden="true" className="size-5" />
              </button>
              <button
                type="button"
                className="home-product-scroll-button btn btn-ghost btn-sm btn-square"
                aria-label={`${title} 다음 상품`}
                disabled={!scrollPosition.canGoForward}
                onClick={() => scrollProducts(1)}
              >
                <ChevronRight aria-hidden="true" className="size-5" />
              </button>
            </>
          ) : null}
          <Link href={g5ShortHref(viewAllHref)} className="section-more ml-1">
            {viewAllLabel}
            {compactCarousel && <ArrowRight aria-hidden="true" className="ml-1 size-3.5" />}
          </Link>
        </div>
      </div>

      {scroll ? (
        <div
          ref={scrollRef}
          className={
            compactCarousel
              ? "scrollbar-hide grid w-full min-w-0 max-w-full grid-flow-col auto-cols-[minmax(132px,37%)] gap-1 overflow-x-auto overscroll-x-contain pb-4 sm:auto-cols-[30%] sm:gap-2 md:auto-cols-[26%] md:gap-4 lg:auto-cols-[16%]"
              : "scrollbar-hide grid w-full min-w-0 max-w-full grid-flow-col auto-cols-[minmax(132px,37%)] gap-5 overflow-x-auto overscroll-x-contain pb-4 sm:auto-cols-[30%] md:auto-cols-[22%] lg:auto-cols-[18%]"
          }
          role="region"
          aria-label={`${title} 상품 목록`}
          aria-keyshortcuts="ArrowLeft ArrowRight"
          tabIndex={0}
          onScroll={updateScrollPosition}
          onKeyDown={handleCarouselKeyDown}
        >
          {products.map((product, idx) => (
            <ProductCard
              key={product.it_id}
              product={product}
              priority={idx < 2}
              productRewriteMode={productRewriteMode}
            />
          ))}
        </div>
      ) : (
        <ul className="flex w-full min-w-0 max-w-full snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain pb-2 scrollbar-hide sm:grid sm:grid-cols-3 sm:overflow-visible sm:pb-0 md:grid-cols-4">
          {products.map((product, idx) => (
            <li
              key={product.it_id}
              className="min-w-[108px] basis-[32%] shrink-0 snap-start sm:min-w-0 sm:basis-auto sm:shrink"
            >
              <ProductCard
                product={product}
                priority={idx < 4}
                productRewriteMode={productRewriteMode}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
