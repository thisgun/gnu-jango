"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight, PackageSearch } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { shouldBypassImageOptimization } from "@/lib/image";
import { shopProductHref } from "@/lib/product-url";
import { cn, formatPrice } from "@/lib/utils";
import { useRecentProductsStore, type RecentProduct } from "@/store/recent-products";

type ProductCardItem = Pick<ShopProduct, "it_id" | "it_name" | "it_price"> &
  Partial<Pick<ShopProduct, "it_cust_price" | "it_tel_inq" | "it_seo_title" | "image_url">>;

export function ProductDetailLoading() {
  return (
    <div className="animate-pulse">
      <div className="grid gap-8 md:grid-cols-2">
        <div className="aspect-square rounded-lg bg-muted" />
        <div className="space-y-4">
          <div className="h-8 w-3/4 rounded bg-muted" />
          <div className="h-6 w-1/2 rounded bg-muted" />
          <div className="h-10 w-1/3 rounded bg-muted" />
        </div>
      </div>
    </div>
  );
}

export function ProductDetailEmpty({
  message,
  description,
  onRetry,
}: {
  message: string;
  description: string;
  onRetry?: () => void;
}) {
  return (
    <div className="px-4 py-10">
      <section className="card card-border mx-auto max-w-lg bg-base-100">
        <div className="card-body items-center text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-base-200 text-base-content/70">
            <PackageSearch aria-hidden="true" className="size-6" />
          </div>
          <h1 className="card-title text-base-content">{message}</h1>
          <p className="text-sm text-base-content/70">{description}</p>
          <div className="card-actions justify-center">
            {onRetry && (
              <button type="button" className="btn btn-outline" onClick={onRetry}>
                다시 시도
              </button>
            )}
            <Link href="/shop/products" className="btn btn-outline">
              상품 목록으로 돌아가기
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

export function ProductImageGallery({
  product,
  images,
  selectedImage,
  onSelectImage,
  onOpenLightbox,
}: {
  product: ShopProduct;
  images: string[];
  selectedImage: number;
  onSelectImage: (index: number | ((previous: number) => number)) => void;
  onOpenLightbox: () => void;
}) {
  const [failedImages, setFailedImages] = useState<Record<string, true>>({});
  const imageSetKey = images.join("\u0000");
  const selectedSrc = images[selectedImage];

  useEffect(() => {
    setFailedImages({});
  }, [product.it_id, imageSetKey]);

  const markImageFailed = (image: string) => {
    setFailedImages((current) => ({ ...current, [image]: true }));
  };

  // 이름(product-gallery*)은 레퍼런스 앱과 같다 — 테마 CSS 가 큰 사진 모서리 16, 썸네일은 폭을 넷으로 나눈 네모로 그린다.
  return (
    <div className="product-gallery">
      <div className="product-gallery-main relative aspect-square overflow-hidden rounded-lg bg-muted">
        {selectedSrc && !failedImages[selectedSrc] ? (
          <button
            type="button"
            onClick={onOpenLightbox}
            aria-label={`${product.it_name} 큰 이미지 보기`}
            className="relative h-full w-full cursor-zoom-in"
          >
            <Image
              src={selectedSrc}
              alt={product.it_name}
              fill
              className="object-cover"
              sizes="(max-width: 768px) 100vw, 50vw"
              priority
              unoptimized={shouldBypassImageOptimization(selectedSrc)}
              onError={() => markImageFailed(selectedSrc)}
            />
          </button>
        ) : (
          <div
            role="img"
            aria-label={`${product.it_name} 이미지 없음`}
            className="flex h-full flex-col items-center justify-center gap-3 text-base-content/60"
          >
            <PackageSearch aria-hidden="true" className="size-10" />
            <span className="text-sm font-medium">
              {selectedSrc ? "이미지를 불러올 수 없습니다" : "등록된 이미지가 없습니다"}
            </span>
          </div>
        )}
        {images.length > 1 && (
          <>
            <button
              type="button"
              aria-label="이전 상품 이미지"
              onClick={() =>
                onSelectImage((previous) => (previous === 0 ? images.length - 1 : previous - 1))
              }
              className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white hover:bg-black/70"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button
              type="button"
              aria-label="다음 상품 이미지"
              onClick={() =>
                onSelectImage((previous) => (previous === images.length - 1 ? 0 : previous + 1))
              }
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white hover:bg-black/70"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          </>
        )}
      </div>
      {images.length > 1 && (
        <div className="product-gallery-thumbs mt-3 flex gap-2 overflow-x-auto">
          {images.map((image, index) => (
            <button
              key={`${product.it_id}-${image || index}`}
              type="button"
              onClick={() => onSelectImage(index)}
              aria-label={`${index + 1}번 상품 이미지 보기`}
              aria-current={index === selectedImage ? "true" : undefined}
              className={cn(
                "relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-md border-2",
                index === selectedImage ? "border-primary" : "border-transparent"
              )}
            >
              {image && !failedImages[image] ? (
                <Image
                  src={image}
                  alt={`${product.it_name} ${index + 1}`}
                  fill
                  className="object-cover"
                  sizes="(max-width: 768px) 25vw, 180px"
                  unoptimized={shouldBypassImageOptimization(image)}
                  onError={() => markImageFailed(image)}
                />
              ) : (
                <div className="flex size-full items-center justify-center bg-base-200 text-base-content/50">
                  <PackageSearch aria-hidden="true" className="size-5" />
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ProductGridCard({
  item,
  productRewriteMode,
  showComparePrice = false,
}: {
  item: ProductCardItem | RecentProduct;
  productRewriteMode?: BbsRewriteMode;
  showComparePrice?: boolean;
}) {
  const isTelInquiry = String(item.it_tel_inq ?? "0") === "1";
  const comparePrice = "it_cust_price" in item ? item.it_cust_price ?? 0 : 0;
  const hasDiscount =
    showComparePrice && !isTelInquiry && comparePrice > 0 && comparePrice > item.it_price;

  return (
    <a href={shopProductHref(item, productRewriteMode)} className="group block">
      <div className="relative aspect-square overflow-hidden rounded-lg bg-muted">
        {item.image_url ? (
          <Image
            src={item.image_url}
            alt={item.it_name}
            fill
            className="object-cover transition-transform group-hover:scale-105"
            sizes="(max-width: 768px) 50vw, 25vw"
            unoptimized={shouldBypassImageOptimization(item.image_url)}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            No Image
          </div>
        )}
      </div>
      <h3 className="mt-2 line-clamp-2 text-sm font-medium group-hover:text-primary">
        {item.it_name}
      </h3>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-sm font-bold">
          {isTelInquiry ? "전화문의" : formatPrice(item.it_price)}
        </span>
        {hasDiscount && (
          <span className="text-xs text-muted-foreground line-through">
            {formatPrice(comparePrice)}
          </span>
        )}
      </div>
    </a>
  );
}

export function RelatedProducts({
  items,
  productRewriteMode,
}: {
  items?: ShopProduct[];
  productRewriteMode?: BbsRewriteMode;
}) {
  if (!items || items.length === 0) return null;

  return (
    <section className="product-related mt-12 border-t pt-8">
      <h2 className="product-related-title mb-6 text-xl font-bold">관련 상품</h2>
      <div className="product-related-grid grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {items.map((item) => (
          <ProductGridCard
            key={item.it_id}
            item={item}
            productRewriteMode={productRewriteMode}
            showComparePrice
          />
        ))}
      </div>
    </section>
  );
}

export function RecentlyViewed({
  currentId,
  productRewriteMode,
}: {
  currentId: string;
  productRewriteMode?: BbsRewriteMode;
}) {
  const items = useRecentProductsStore((state) => state.items);
  const filtered = items.filter((product) => product.it_id !== currentId).slice(0, 8);

  if (filtered.length === 0) return null;

  return (
    <section className="product-related product-recent mt-12 border-t pt-8">
      <h2 className="product-related-title mb-6 text-xl font-bold">최근 본 상품</h2>
      <div className="product-related-grid grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
        {filtered.map((item) => (
          <ProductGridCard key={item.it_id} item={item} productRewriteMode={productRewriteMode} />
        ))}
      </div>
    </section>
  );
}
