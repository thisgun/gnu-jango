"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import { api } from "@/lib/api";
import type { ShopPolicy, ShopProduct, ShopReview, ShopReviewSummary, ShopQA } from "@/lib/api";
import { toastSuccess, toastError } from "@/lib/toast";
import {
  currentPathForRuntime,
  currentPathHasTrailingSlashForRuntime,
  g5PathForRuntime,
} from "@/lib/config";
import { runtimeRouterPush } from "@/lib/runtime-router";
import type { BbsRewriteMode } from "@/lib/board-url";
import { isBbsSeoRewrite } from "@/lib/board-url";
import { isTelInquiry } from "@/lib/shop-product-state";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { useRecentProductsStore } from "@/store/recent-products";
import { addCartItemDirect, addCartItems, addWishlistItem } from "@/services/cart";
import { gaViewItem } from "@/lib/analytics";
import {
  getShopProductResult,
  getShopProductBySeoResult,
  getShopPolicy,
  getShopShippingFreeThreshold,
  getShopProductReviewSummary,
  getShopProductQaPage,
  getShopProductReviewPage,
} from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import { DEFAULT_SHOP_LIST_DISPLAY, shopListDisplayOf, type ShopRelatedDisplay } from "@/lib/shop-display";
import { addProductToCart, toastAddedToCart } from "@/components/shop/addProductToCart";
import {
  cartIdsFromAddResponse,
  isProductDetailSoldOut,
  productShippingPayment,
  productDetailTabFromSearch,
  productDetailFormFromSearch,
  qaFocusIdFromSearch,
  reviewFocusIdFromSearch,
  isLegacyShortProductPath,
} from "@/components/shop/productDetailHelpers";
import { useProductOptions } from "@/components/shop/useProductOptions";
import {
  scrollToProductDetailTabs,
  useProductDetailFocusScroll,
} from "./useProductDetailFocusScroll";
import { useProductDetailMetadata } from "./useProductDetailMetadata";
import { useProductMemberActions } from "./useProductMemberActions";
import { useProductNaverPay } from "./useProductNaverPay";
import { ProductDetailEmpty, ProductDetailLoading } from "./ProductDetailSections";
import { ProductDetailView } from "./ProductDetailView";
import type { ProductPurchaseControlsProps } from "./ProductPurchaseControls";

interface ProductDetailClientProps {
  itId?: string;
  initialProduct?: ShopProduct | null;
}

type QaPageResult = Awaited<ReturnType<typeof getShopProductQaPage>>;

export default function ProductDetailClient({
  itId,
  initialProduct,
}: ProductDetailClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const productQueryString = searchParams.toString();
  const it_id =
    useRuntimeRouteParam("it_id", ["/shop/products/:it_id", "/shop/:it_id"], itId) ||
    searchParams.get("__g5_item_id") ||
    "";
  const [product, setProduct] = useState<ShopProduct | null>(
    initialProduct?.it_id === it_id ? initialProduct : null
  );
  const [loading, setLoading] = useState(
    () => (!!it_id && product?.it_id !== it_id) || (itId === "__g5_static__" && !it_id)
  );
  const [productErrorMessage, setProductErrorMessage] = useState("");
  const [productErrorDescription, setProductErrorDescription] = useState("");
  const [productRetryable, setProductRetryable] = useState(false);
  const [productLoadAttempt, setProductLoadAttempt] = useState(0);
  const [selectedImage, setSelectedImage] = useState(0);
  const [ctSendCostSelection, setCtSendCostSelection] = useState(0);
  const [activeTab, setActiveTab] = useState("description");
  const [reviews, setReviews] = useState<ShopReview[]>([]);
  const [reviewSummary, setReviewSummary] = useState<ShopReviewSummary | null>(null);
  const [qas, setQas] = useState<ShopQA[]>([]);
  const [shippingPolicy, setShippingPolicy] = useState<ShopPolicy | null>(null);
  const [reviewPage, setReviewPage] = useState(1);
  // 사용후기 쪽 — 서버가 실제로 연 쪽(찾아간 후기가 있으면 그 쪽)과 마지막 쪽.
  const [reviewShownPage, setReviewShownPage] = useState(1);
  const [reviewLastPage, setReviewLastPage] = useState(1);
  // 주소의 ?is_id= — 첫 불러오기에서만 서버에 넘겨 그 후기가 있는 쪽을 연다. 쪽을 옮기면 비운다.
  const [pendingFocusIsId, setPendingFocusIsId] = useState(0);
  const [qaPage, setQaPage] = useState(1);
  const [qaShownPage, setQaShownPage] = useState(1);
  const [qaLastPage, setQaLastPage] = useState(1);
  // 상품문의 전체 건수 — 목록을 받기 전에는 null(탭 건수는 상품 정보의 qa_count 를 쓴다).
  const [qaTotal, setQaTotal] = useState<number | null>(null);
  const [pendingFocusIqId, setPendingFocusIqId] = useState(0);
  const [addingToCart, setAddingToCart] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [relatedDisplay, setRelatedDisplay] = useState<ShopRelatedDisplay>(DEFAULT_SHOP_LIST_DISPLAY.related);
  const addRecentProduct = useRecentProductsStore((s) => s.addProduct);
  const trackedViewItemIdRef = useRef<string | null>(null);
  const {
    quantity,
    setQuantity,
    optionSelections,
    selectOptionValue,
    selectSupplyOption,
    supplyGroups,
    selectedCartOptions,
    clearSelectedOptions,
    optionSubjects,
    minBuyQty,
    maxBuyQty,
    quantityMinQty,
    getAvailableValues,
    updateSelectedOptionQty,
    removeSelectedOption,
    buildSelectedCartOptions,
    validateBuyQtyBeforeSubmit,
    displayTotal,
  } = useProductOptions({ product, resetKey: it_id });
  const memberActions = useProductMemberActions(product);
  const {
    user,
    isAuthInitialized,
    requireLogin,
    handleMemberActionError,
    openRecommendDialog,
    openRestockDialog,
  } = memberActions;
  const telInquiry = isTelInquiry(product);
  const hasOptionSubjects = optionSubjects.length > 0;
  const shippingFreeThreshold = getShopShippingFreeThreshold(shippingPolicy);
  const shippingPayment = productShippingPayment(product, ctSendCostSelection);
  const legacyProductForm = productDetailFormFromSearch(productQueryString);
  const naverPay = useProductNaverPay({
    product,
    isTelInquiry: telInquiry,
    quantity,
    hasOptionSubjects,
    buildSelectedCartOptions,
    validateBuyQtyBeforeSubmit,
  });

  useEffect(() => {
    let alive = true;
    getClientPublicSettings()
      .then((settings) => {
        if (!alive) return;
        setProductRewriteMode(settings.cf_bbs_rewrite);
        setRelatedDisplay(shopListDisplayOf(settings).related);
      })
      .catch(() => {
        if (alive) setProductRewriteMode(0);
      });

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!it_id) {
      setProduct(null);
      setProductErrorMessage("");
      setProductErrorDescription("");
      setProductRetryable(false);
      setLoading(false);
      return;
    }

    let alive = true;
    if (initialProduct) {
      setProduct(initialProduct);
      setLoading(false);
    } else {
      setLoading(true);
    }
    setProductErrorMessage("");
    setProductErrorDescription("");
    setProductRetryable(false);
    const runtimePath = currentPathForRuntime(pathname || undefined);
    const legacyShortProductPath = isLegacyShortProductPath(runtimePath);
    const legacySeoPath =
      legacyShortProductPath && currentPathHasTrailingSlashForRuntime(pathname || undefined);
    const request = (async () => {
      if (legacySeoPath) {
        return {
          productResult: await getShopProductBySeoResult(it_id),
          resolvedBySeo: true,
        };
      }

      const productResult = await getShopProductResult(it_id);
      if (productResult.ok || !legacyShortProductPath) {
        return { productResult, resolvedBySeo: false };
      }

      const seoResult = await getShopProductBySeoResult(it_id);
      if (seoResult.ok) {
        return { productResult: seoResult, resolvedBySeo: true };
      }
      if (productResult.status === 404 && seoResult.status !== 404) {
        return { productResult: seoResult, resolvedBySeo: false };
      }

      return { productResult, resolvedBySeo: false };
    })();
    const settingsRequest = legacyShortProductPath
      ? getClientPublicSettings().catch(() => null)
      : Promise.resolve(null);

    Promise.all([request, settingsRequest])
      .then(([lookup, settings]) => {
        if (!alive) return;
        const { productResult, resolvedBySeo } = lookup;
        const nextRewriteMode = settings?.cf_bbs_rewrite ?? 0;
        if (settings) setProductRewriteMode(nextRewriteMode);
        if (!productResult.ok) {
          const notFound = productResult.status === 404;
          setProductRetryable(!notFound);
          setProduct(notFound ? null : initialProduct ?? null);
          setProductErrorMessage(
            notFound
              ? "상품을 찾을 수 없습니다"
              : initialProduct
                ? ""
                : "상품 정보를 불러오지 못했습니다"
          );
          setProductErrorDescription(
            notFound
              ? "삭제되었거나 주소가 올바르지 않은 상품일 수 있습니다."
              : initialProduct
                ? ""
                : "잠시 후 다시 시도해 주세요."
          );
          return;
        }
        const nextProduct = productResult.data;
        if (resolvedBySeo && nextProduct?.it_id && !isBbsSeoRewrite(nextRewriteMode)) {
          window.location.replace(g5PathForRuntime(`/shop/${nextProduct.it_id}`));
          return;
        }
        setProduct(nextProduct);
        setProductErrorMessage("");
        setProductErrorDescription("");
        setProductRetryable(false);
      })
      .catch(() => {
        if (!alive) return;
        setProduct(initialProduct ?? null);
        setProductRetryable(!initialProduct);
        setProductErrorMessage(initialProduct ? "" : "상품 정보를 불러오지 못했습니다");
        setProductErrorDescription(initialProduct ? "" : "잠시 후 다시 시도해 주세요.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [initialProduct, it_id, pathname, productLoadAttempt]);

  useEffect(() => {
    setSelectedImage(0);
    setCtSendCostSelection(0);
    setReviews([]);
    setReviewSummary(null);
    setQas([]);
    setReviewPage(1);
    setReviewShownPage(1);
    setReviewLastPage(1);
    setPendingFocusIsId(reviewFocusIdFromSearch(productQueryString));
    setQaPage(1);
    setQaShownPage(1);
    setQaLastPage(1);
    setQaTotal(null);
    setPendingFocusIqId(qaFocusIdFromSearch(productQueryString));
    setActiveTab(productDetailTabFromSearch(productQueryString));
  }, [it_id, productQueryString]);

  useEffect(() => {
    let alive = true;

    getShopPolicy()
      .then((policy) => {
        if (alive) setShippingPolicy(policy);
      })
      .catch(() => {
        if (alive) setShippingPolicy(null);
      });

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const nextTab = productDetailTabFromSearch(productQueryString);
    setActiveTab((current) => (current === nextTab ? current : nextTab));
  }, [productQueryString]);

  useProductDetailFocusScroll(product?.it_id, productQueryString);

  // ?modal=recommend · ?modal=restock — 옛 주소(그누보드 itemrecommend · itemstocksms 팝업)는 그 창을 바로 연다.
  useEffect(() => {
    if (!product?.it_id) return;

    const params = new URLSearchParams(productQueryString);
    const modal = (params.get("modal") ?? params.get("action") ?? "").toLowerCase();
    if (modal === "recommend") {
      if (isAuthInitialized) {
        openRecommendDialog();
      }
      return;
    }
    if (modal === "restock" || modal === "stock" || modal === "stocksms") {
      openRestockDialog();
    }
  }, [
    isAuthInitialized,
    openRecommendDialog,
    openRestockDialog,
    product?.it_id,
    productQueryString,
  ]);

  useProductDetailMetadata(product, productRewriteMode);

  useEffect(() => {
    if (!product) return;
    addRecentProduct({
      it_id: product.it_id,
      it_name: product.it_name,
      it_seo_title: product.it_seo_title,
      it_price: product.it_price,
      it_tel_inq: product.it_tel_inq,
      image_url: product.image_url,
      viewed_at: Date.now(),
    });
    // GA4 view_item · 조회수 — 상품 페이지 진입 시 상품마다 1회.
    if (trackedViewItemIdRef.current !== product.it_id) {
      trackedViewItemIdRef.current = product.it_id;
      void api
        .post(`/shop/products/${encodeURIComponent(product.it_id)}/hit`)
        .catch(() => undefined);
      gaViewItem({
        item_id: product.it_id,
        item_name: product.it_name,
        item_category: product.ca_name,
        item_brand: product.it_brand,
        price: product.it_price,
      });
    }
  }, [product, addRecentProduct]);

  useEffect(() => {
    if (activeTab === "reviews" && it_id) {
      Promise.all([
        getShopProductReviewPage(it_id, reviewPage, pendingFocusIsId || undefined).catch(() => null),
        getShopProductReviewSummary(it_id).catch(() => null),
      ]).then(([nextReviews, nextSummary]) => {
        setReviews(nextReviews?.items ?? []);
        setReviewShownPage(nextReviews?.meta?.current_page ?? reviewPage);
        setReviewLastPage(nextReviews?.meta?.last_page ?? 1);
        setReviewSummary(nextSummary);
      });
    }
  }, [activeTab, reviewPage, it_id, pendingFocusIsId]);

  /** 사용후기 쪽 옮기기 — 찾아간 후기 표시는 그만두고, 탭 머리로 올라가 새 쪽을 처음부터 보게 한다. */
  const handleReviewPageChange = useCallback((nextPage: number) => {
    setPendingFocusIsId(0);
    setReviewPage(nextPage);
    scrollToProductDetailTabs();
  }, []);

  const applyQaPage = useCallback((result: QaPageResult) => {
    setQas(result.items);
    setQaShownPage(result.meta?.current_page ?? 1);
    setQaLastPage(result.meta?.last_page ?? 1);
    setQaTotal(result.meta?.total ?? result.items.length);
  }, []);

  useEffect(() => {
    if (activeTab !== "qa" || !it_id) return;
    let alive = true;
    getShopProductQaPage(it_id, qaPage, pendingFocusIqId || undefined)
      .then((result) => {
        if (!alive) return;
        applyQaPage(result);
        if (pendingFocusIqId > 0) {
          const focusedPage = result.meta?.current_page ?? qaPage;
          setQaPage(focusedPage);
          setPendingFocusIqId(0);
        }
      })
      .catch(() => {
        if (alive) {
          setQas([]);
          setQaShownPage(1);
          setQaLastPage(1);
          setQaTotal(null);
        }
      });
    return () => {
      alive = false;
    };
  }, [activeTab, qaPage, it_id, pendingFocusIqId, applyQaPage]);

  // 문의를 쓰거나 고치면 지금 보는 쪽을 다시 읽는다.
  const reloadQas = useCallback(() => {
    if (!it_id) return;
    getShopProductQaPage(it_id, qaShownPage)
      .then(applyQaPage)
      .catch(() => setQas([]));
  }, [applyQaPage, it_id, qaShownPage]);

  /** 상품문의 쪽 옮기기 — 사용후기와 같이 찾아간 문의 표시는 그만두고 탭 머리로 올라간다. */
  const handleQaPageChange = useCallback((nextPage: number) => {
    setPendingFocusIqId(0);
    setQaPage(nextPage);
    scrollToProductDetailTabs();
  }, []);

  /**
   * 담기 · 바로구매 전 확인 — 전화문의 상품은 막고, 선택옵션 상품은 선택옵션 줄이 하나는 있어야 한다
   * (추가옵션만으로는 담을 수 없다 — 영카트 fsubmit_check). 통과하면 담을 줄을 돌려준다.
   */
  const purchaseLinesOrNull = useCallback(() => {
    if (!product) return null;
    if (telInquiry) {
      toastError("전화문의 상품은 온라인 주문할 수 없습니다.");
      return null;
    }
    const cartOptions = buildSelectedCartOptions();
    if (hasOptionSubjects && !cartOptions.some((option) => option.ioType === 0)) {
      toastError("옵션을 선택해주세요.");
      return null;
    }
    return validateBuyQtyBeforeSubmit(cartOptions) ? cartOptions : null;
  }, [buildSelectedCartOptions, hasOptionSubjects, product, telInquiry, validateBuyQtyBeforeSubmit]);

  const handleAddToCart = useCallback(async () => {
    const cartOptions = purchaseLinesOrNull();
    if (!product || !cartOptions) return;

    setAddingToCart(true);
    try {
      await addProductToCart({
        product,
        quantity,
        cartOptions,
        hasOptionSubjects,
        ctSendCost: shippingPayment.ctSendCost,
      });
      // 담은 뒤 처음 모습으로 — 고른 줄과 select 를 비운다(영카트도 담고 나면 목록을 비운다).
      clearSelectedOptions();
      toastAddedToCart(router);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "장바구니 추가에 실패했습니다.";
      toastError(message);
    } finally {
      setAddingToCart(false);
    }
  }, [
    purchaseLinesOrNull,
    product,
    quantity,
    hasOptionSubjects,
    shippingPayment.ctSendCost,
    clearSelectedOptions,
    router,
  ]);

  /**
   * 바로구매 — 바로구매 칸(direct)에 담고 그 줄만으로 주문서를 연다. 옵션 없는 상품은 본품(quantity) 한 줄이 먼저
   * 바로구매 칸을 새로 채우고, 추가옵션 줄은 그 뒤에 붙인다(replace_direct: false). 선택옵션 상품은 고른 줄로 새로 채운다.
   */
  const handleBuyNow = useCallback(async () => {
    const cartOptions = purchaseLinesOrNull();
    if (!product || !cartOptions) return;

    const ctSendCost = shippingPayment.ctSendCost;
    try {
      const directCartIds: string[] = [];
      if (!hasOptionSubjects) {
        const response = await addCartItemDirect(product.it_id, quantity, "", { ctSendCost });
        directCartIds.push(...cartIdsFromAddResponse(response));
      }
      if (cartOptions.length > 0) {
        const response = await addCartItems(
          product.it_id,
          cartOptions.map((option) => ({
            io_id: option.io_id,
            ct_qty: option.qty,
            io_type: option.ioType,
          })),
          { direct: true, replaceDirect: hasOptionSubjects, ctSendCost }
        );
        directCartIds.push(...cartIdsFromAddResponse(response));
      }
      clearSelectedOptions();
      const uniqueCartIds = Array.from(new Set(directCartIds));
      const orderHref = uniqueCartIds.length > 0
        ? `/shop/order?ct_ids=${encodeURIComponent(uniqueCartIds.join(","))}`
        : "/shop/order";
      runtimeRouterPush(router, orderHref);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "오류가 발생했습니다.";
      toastError(message);
    }
  }, [
    purchaseLinesOrNull,
    product,
    quantity,
    hasOptionSubjects,
    shippingPayment.ctSendCost,
    clearSelectedOptions,
    router,
  ]);

  const handleWishlist = useCallback(async () => {
    if (!product) return;
    if (!requireLogin()) return;

    try {
      await addWishlistItem(product.it_id);
      toastSuccess("위시리스트에 추가되었습니다.");
    } catch (err: unknown) {
      handleMemberActionError(err, "위시리스트 추가에 실패했습니다.");
    }
  }, [product, requireLogin, handleMemberActionError]);

  const handleReviewSubmitted = useCallback(() => {
    if (!product) return;
    setPendingFocusIsId(0);
    setReviewPage(1);
    getShopProductReviewPage(product.it_id, 1)
      .then((result) => {
        setReviews(result.items);
        setReviewShownPage(result.meta?.current_page ?? 1);
        setReviewLastPage(result.meta?.last_page ?? 1);
      })
      .catch(() => undefined);
    getShopProductReviewSummary(product.it_id)
      .then(setReviewSummary)
      .catch(() => undefined);
  }, [product]);

  const handleQaSubmitted = useCallback(() => {
    if (!product) return;
    // 새 문의는 맨 앞(1쪽)에 선다 — 쪽 정보까지 새로 받는다.
    setPendingFocusIqId(0);
    setQaPage(1);
    getShopProductQaPage(product.it_id, 1)
      .then(applyQaPage)
      .catch(() => undefined);
  }, [product, applyQaPage]);

  if (loading) {
    return <ProductDetailLoading />;
  }

  if (!product && productErrorMessage) {
    return (
      <ProductDetailEmpty
        message={productErrorMessage}
        description={productErrorDescription}
        onRetry={productRetryable ? () => setProductLoadAttempt((attempt) => attempt + 1) : undefined}
      />
    );
  }

  if (!product) {
    return (
      <ProductDetailEmpty
        message="상품을 찾을 수 없습니다"
        description="삭제되었거나 주소가 올바르지 않은 상품일 수 있습니다."
      />
    );
  }

  // 품절 표시뿐 아니라 선택옵션이 모두 품절 · 옵션 없는 상품의 재고 0 도 품절이다(영카트 is_soldout — 서버도 담기를 거절).
  const isSoldOut = isProductDetailSoldOut(product);
  const reviewSummaryScores =
    reviewSummary?.scores ??
    Array.from({ length: 5 }, (_, index) => ({
      score: 5 - index,
      count: 0,
      percentage: 0,
    }));
  const purchaseControls: ProductPurchaseControlsProps = {
    product,
    canPurchaseProduct: !telInquiry && !isSoldOut,
    isTelInquiry: telInquiry,
    isSoldOut,
    optionSubjects,
    optionSelections,
    onSelectOptionValue: selectOptionValue,
    getAvailableValues,
    supplyGroups,
    onSelectSupplyOption: selectSupplyOption,
    quantity,
    onQuantityChange: setQuantity,
    quantityMinQty,
    minBuyQty,
    maxBuyQty,
    selectedCartOptions,
    onUpdateSelectedOptionQty: updateSelectedOptionQty,
    onRemoveSelectedOption: removeSelectedOption,
    displayTotal,
    restockAlerted: memberActions.restockAlerted,
    onRemoveRestockAlert: memberActions.handleRemoveRestockAlert,
    onOpenRestockDialog: openRestockDialog,
    addingToCart,
    onAddToCart: handleAddToCart,
    onBuyNow: handleBuyNow,
    onWishlist: handleWishlist,
  };

  return (
    <ProductDetailView
      product={product}
      itId={it_id}
      productRewriteMode={productRewriteMode}
      relatedDisplay={relatedDisplay}
      selectedImage={selectedImage}
      onSelectedImageChange={setSelectedImage}
      lightboxOpen={lightboxOpen}
      onLightboxOpenChange={setLightboxOpen}
      purchaseControls={purchaseControls}
      shippingPayment={shippingPayment}
      ctSendCostSelection={ctSendCostSelection}
      onCtSendCostSelectionChange={setCtSendCostSelection}
      naverPay={naverPay}
      qaTotal={qaTotal}
      memberActions={memberActions}
      tabsContent={{
        activeTab,
        onActiveTabChange: setActiveTab,
        canWriteReview: Boolean(user),
        canWriteQa: Boolean(user),
        shippingPolicy,
        legacyProductForm,
        onReviewSubmitted: handleReviewSubmitted,
        onQaSubmitted: handleQaSubmitted,
        reviews,
        reviewPage: reviewShownPage,
        reviewLastPage,
        focusReviewId: reviewFocusIdFromSearch(productQueryString),
        onReviewPageChange: handleReviewPageChange,
        reviewSummary,
        reviewAverage: reviewSummary?.average ?? product.review_avg ?? 0,
        reviewTotal: reviewSummary?.total ?? product.review_count ?? 0,
        reviewScores: reviewSummaryScores,
        qas,
        qaPage: qaShownPage,
        qaLastPage,
        focusQaId: qaFocusIdFromSearch(productQueryString),
        onQaPageChange: handleQaPageChange,
        onQaChanged: reloadQas,
        shippingFreeThreshold,
      }}
    />
  );
}
