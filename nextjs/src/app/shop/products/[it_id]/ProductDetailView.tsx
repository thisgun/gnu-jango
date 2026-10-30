"use client";

import type { ComponentProps, Dispatch, SetStateAction } from "react";
import dynamic from "next/dynamic";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { g5ShortHref } from "@/lib/g5-short-url";
import { sanitizeCommerceHtml } from "@/lib/sanitize";
import type { ShopRelatedDisplay } from "@/lib/shop-display";
import { productPointLabel } from "@/components/shop/productDetailHelpers";
import { RecommendationDialog, RestockAlertDialog } from "./ProductDetailDialogs";
import { ProductImageGallery, RecentlyViewed, RelatedProducts, SimilarProducts } from "./ProductDetailSections";
import { ProductDetailTabs, type ProductDetailTab } from "./ProductDetailTabs";
import { ProductPurchaseControls, type ProductPurchaseControlsProps } from "./ProductPurchaseControls";
import { ProductPurchasePanel, type ShippingPaymentDisplay } from "./ProductPurchasePanel";
import type { ProductMemberActions } from "./useProductMemberActions";
import type { ProductNaverPayActions } from "./useProductNaverPay";

const Lightbox = dynamic(
  () => import("@/components/ui/lightbox").then((mod) => ({ default: mod.Lightbox })),
  { ssr: false }
);

/** 탭 본문이 쓰는 값 — 상품 · 탭 목록 · 구매 상자 · 문의 건수는 이 화면이 채운다. */
export type ProductDetailTabsContent = Omit<
  ComponentProps<typeof ProductDetailTabs>,
  "product" | "tabs" | "productInfoItems" | "purchaseControls" | "qaTotal"
>;

interface ProductDetailViewProps {
  product: ShopProduct;
  itId: string;
  productRewriteMode: BbsRewriteMode;
  /** 관련상품 출력 여부 · 칸 수(관리자 진열 설정). */
  relatedDisplay: ShopRelatedDisplay;
  selectedImage: number;
  onSelectedImageChange: Dispatch<SetStateAction<number>>;
  lightboxOpen: boolean;
  onLightboxOpenChange: (open: boolean) => void;
  /** 옵션 · 수량 · 단추 묶음 — 위 패널과 따라다니는 구매 상자가 같은 것을 받는다. */
  purchaseControls: ProductPurchaseControlsProps;
  shippingPayment: ShippingPaymentDisplay;
  ctSendCostSelection: number;
  onCtSendCostSelectionChange: (value: number) => void;
  naverPay: ProductNaverPayActions | null;
  tabsContent: ProductDetailTabsContent;
  /** 상품문의 목록이 알려 준 전체 건수 — 받기 전에는 null(상품 정보의 qa_count 를 쓴다). */
  qaTotal: number | null;
  memberActions: ProductMemberActions;
}

/**
 * 상품 상세 화면 — 레퍼런스 앱 ProductDetailView 의 차례: 빵부스러기, 머리 HTML, 사진 + 구매 패널,
 * 탭 본문(넓은 화면은 옆에 따라다니는 구매 상자), 관련 · 최근 본 상품, 꼬리 HTML, 창들.
 * 상태와 불러오기는 ProductDetailClient 가 갖고, 여기는 그리기만 한다.
 */
export function ProductDetailView({
  product,
  itId,
  productRewriteMode,
  relatedDisplay,
  selectedImage,
  onSelectedImageChange,
  lightboxOpen,
  onLightboxOpenChange,
  purchaseControls,
  shippingPayment,
  ctSendCostSelection,
  onCtSendCostSelectionChange,
  naverPay,
  tabsContent,
  qaTotal,
  memberActions,
}: ProductDetailViewProps) {
  const images = (product.images?.length ? product.images : [product.image_url]).filter(
    (image): image is string => Boolean(image)
  );
  const qaCount = qaTotal ?? product.qa_count ?? 0;
  const tabs: ProductDetailTab[] = [
    { id: "description", label: "상품설명" },
    { id: "reviews", label: "상품후기", count: product.review_count ?? 0 },
    { id: "qa", label: "상품문의", count: qaCount },
    { id: "shipping", label: "배송정보" },
  ];
  const breadcrumbItems = [
    { label: "쇼핑몰", href: "/shop" },
    ...(product.ca_name
      ? [{ label: product.ca_name, href: g5ShortHref(`/shop/categories/${product.ca_id}`) }]
      : []),
    { label: product.it_name },
  ];
  const productHeadHtml = sanitizeCommerceHtml(product.it_head_html);
  const productTailHtml = sanitizeCommerceHtml(product.it_tail_html);

  return (
    <div className="product-detail-page">
      <Breadcrumb items={breadcrumbItems} />

      {productHeadHtml && (
        <div
          id="sit_hhtml"
          className="mb-6 prose max-w-none text-sm"
          dangerouslySetInnerHTML={{ __html: productHeadHtml }}
        />
      )}

      <div className="product-detail-grid grid gap-8 md:grid-cols-2">
        <ProductImageGallery
          product={product}
          images={images}
          selectedImage={selectedImage}
          onSelectImage={onSelectedImageChange}
          onOpenLightbox={() => onLightboxOpenChange(true)}
        />

        <ProductPurchasePanel
          {...purchaseControls}
          onOpenRecommendDialog={memberActions.openRecommendDialog}
          onRequireLogin={memberActions.requireLogin}
          productRewriteMode={productRewriteMode}
          pointLabel={productPointLabel(product)}
          shippingPayment={shippingPayment}
          ctSendCostSelection={ctSendCostSelection}
          onCtSendCostSelectionChange={onCtSendCostSelectionChange}
          naverPay={naverPay}
        />
      </div>

      <ProductDetailTabs
        {...tabsContent}
        tabs={tabs}
        product={product}
        productInfoItems={product.it_info_items ?? []}
        qaTotal={qaCount}
        purchaseControls={<ProductPurchaseControls {...purchaseControls} />}
      />

      <RelatedProducts items={product.related_items} productRewriteMode={productRewriteMode} display={relatedDisplay} />

      <SimilarProducts items={product.similar_items} productRewriteMode={productRewriteMode} />

      <RecentlyViewed currentId={itId || product.it_id} productRewriteMode={productRewriteMode} />

      {productTailHtml && (
        <div
          className="mt-10 prose max-w-none text-sm"
          dangerouslySetInnerHTML={{ __html: productTailHtml }}
        />
      )}

      <RestockAlertDialog
        open={memberActions.restockDialogOpen}
        onOpenChange={memberActions.setRestockDialogOpen}
        hp={memberActions.restockHp}
        onHpChange={memberActions.setRestockHp}
        agree={memberActions.restockAgree}
        onAgreeChange={memberActions.setRestockAgree}
        submitting={memberActions.restockSubmitting}
        privacyText={product.stock_sms_privacy?.trim() ?? ""}
        onSubmit={memberActions.submitRestockAlert}
      />

      <RecommendationDialog
        open={memberActions.recommendDialogOpen}
        onOpenChange={memberActions.setRecommendDialogOpen}
        toEmail={memberActions.recommendToEmail}
        onToEmailChange={memberActions.setRecommendToEmail}
        subject={memberActions.recommendSubject}
        onSubjectChange={memberActions.setRecommendSubject}
        content={memberActions.recommendContent}
        onContentChange={memberActions.setRecommendContent}
        submitting={memberActions.recommendSubmitting}
        onSubmit={memberActions.submitRecommendation}
      />

      {lightboxOpen && (
        <Lightbox
          images={images}
          currentIndex={selectedImage}
          onClose={() => onLightboxOpenChange(false)}
          onNavigate={onSelectedImageChange}
        />
      )}
    </div>
  );
}
