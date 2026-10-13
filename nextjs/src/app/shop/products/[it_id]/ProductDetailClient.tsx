"use client";

import { useEffect, useRef, useState, useCallback, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import { ApiError, api } from "@/lib/api";
import type { ShopPolicy, ShopProduct, ShopReview, ShopReviewSummary, ShopQA } from "@/lib/api";
import type { ShopNaverPayConfig, ShopNaverPayOrderOption } from "@/lib/api";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { toastSuccess, toastError, toastInfo } from "@/lib/toast";
import { ToastAction } from "@/components/ui/toast";
import { sanitizeCommerceHtml } from "@/lib/sanitize";
import {
  applyClientJsonLd,
  applyClientPageMetadata,
  clientAbsoluteUrl,
  plainTextSummary,
} from "@/lib/client-metadata";
import {
  currentPathForRuntime,
  currentPathHasTrailingSlashForRuntime,
  g5PathForRuntime,
} from "@/lib/config";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { notifyCartChanged } from "@/lib/cart-events";
import type { BbsRewriteMode } from "@/lib/board-url";
import { isBbsSeoRewrite } from "@/lib/board-url";
import { g5ShortHref } from "@/lib/g5-short-url";
import { shopProductPath } from "@/lib/product-url";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { useRecentProductsStore } from "@/store/recent-products";
import { useRestockAlertStore } from "@/store/restock-alerts";
import { useAuthStore } from "@/store/auth";
import {
  addCartItem,
  addCartItemDirect,
  addCartItems,
  addWishlistItem,
} from "@/services/cart";
import { gaViewItem, gaAddToCart } from "@/lib/analytics";
import {
  getShopProductResult,
  getShopProductBySeoResult,
  getShopPolicy,
  getShopShippingFreeThreshold,
  getShopProductReviewSummary,
  getShopProductQaPage,
  getShopProductReviewPage,
  getShopNaverPayConfig,
  registerShopNaverPayOrder,
  registerShopNaverPayWish,
} from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import {
  cartIdsFromAddResponse,
  productPointLabel,
  productShippingPayment,
  productDetailTabFromSearch,
  productDetailFormFromSearch,
  qaFocusIdFromSearch,
  reviewFocusIdFromSearch,
  isLegacyShortProductPath,
} from "./productDetailHelpers";
import {
  scrollToProductDetailTabs,
  useProductDetailFocusScroll,
} from "./useProductDetailFocusScroll";
import {
  ProductDetailEmpty,
  ProductDetailLoading,
  ProductImageGallery,
  RecentlyViewed,
  RelatedProducts,
} from "./ProductDetailSections";
import { RecommendationDialog, RestockAlertDialog } from "./ProductDetailDialogs";
import { ProductDetailTabs } from "./ProductDetailTabs";
import { ProductPurchasePanel } from "./ProductPurchasePanel";
import { useProductOptions } from "./useProductOptions";

const Lightbox = dynamic(
  () => import("@/components/ui/lightbox").then((mod) => ({ default: mod.Lightbox })),
  { ssr: false }
);

interface ProductDetailClientProps {
  itId?: string;
  initialProduct?: ShopProduct | null;
}

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
  const [reviewShownPage, setReviewShownPage] = useState(1);
  const [reviewLastPage, setReviewLastPage] = useState(1);
  const [pendingFocusIsId, setPendingFocusIsId] = useState(0);
  const [qaPage, setQaPage] = useState(1);
  const [qaShownPage, setQaShownPage] = useState(1);
  const [qaLastPage, setQaLastPage] = useState(1);
  const [qaTotal, setQaTotal] = useState(0);
  const [pendingFocusIqId, setPendingFocusIqId] = useState(0);
  const [addingToCart, setAddingToCart] = useState(false);
  const [naverPayConfig, setNaverPayConfig] = useState<ShopNaverPayConfig | null>(null);
  const [naverPaySubmitting, setNaverPaySubmitting] = useState(false);
  const [naverPayWishSubmitting, setNaverPayWishSubmitting] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [restockDialogOpen, setRestockDialogOpen] = useState(false);
  const [restockHp, setRestockHp] = useState("");
  const [restockAgree, setRestockAgree] = useState(false);
  const [restockSubmitting, setRestockSubmitting] = useState(false);
  const [recommendDialogOpen, setRecommendDialogOpen] = useState(false);
  const [recommendToEmail, setRecommendToEmail] = useState("");
  const [recommendSubject, setRecommendSubject] = useState("");
  const [recommendContent, setRecommendContent] = useState("");
  const [recommendSubmitting, setRecommendSubmitting] = useState(false);
  const addRecentProduct = useRecentProductsStore((s) => s.addProduct);
  const { isAlerted, addAlert, removeAlert } = useRestockAlertStore();
  const trackedViewItemIdRef = useRef<string | null>(null);
  const user = useAuthStore((s) => s.user);
  const isAuthInitialized = useAuthStore((s) => s.isInitialized);
  const {
    quantity,
    setQuantity,
    optionSelections,
    setOptionSelections,
    supplySelection,
    setSupplySelection,
    selectedCartOptions,
    setSelectedCartOptions,
    optionSubjects,
    minBuyQty,
    quantityMinQty,
    quantityMaxQty,
    supplyOptions,
    supplyLabel,
    getAvailableValues,
    selectedOption,
    handleAddSelectedOption,
    handleAddSupplyOption,
    updateSelectedOptionQty,
    removeSelectedOption,
    buildSelectedCartOptions,
    validateBuyQtyBeforeSubmit,
    displayTotal,
  } = useProductOptions({ product, resetKey: it_id });
  const isTelInquiry = String(product?.it_tel_inq ?? "0") === "1";
  const shippingFreeThreshold = getShopShippingFreeThreshold(shippingPolicy);
  const shippingPayment = productShippingPayment(product, ctSendCostSelection);
  const legacyProductForm = productDetailFormFromSearch(productQueryString);

  useEffect(() => {
    let alive = true;
    getClientPublicSettings()
      .then((settings) => {
        if (alive) setProductRewriteMode(settings.cf_bbs_rewrite);
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
    setQaTotal(0);
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
    let alive = true;

    getShopNaverPayConfig()
      .then((config) => {
        if (alive) setNaverPayConfig(config);
      })
      .catch(() => {
        if (alive) setNaverPayConfig(null);
      });

    return () => {
      alive = false;
    };
  }, []);

  const redirectToLogin = useCallback(() => {
    toastInfo("로그인 후 이용해주세요.");
    runtimeRouterPush(router, `/login?redirect=${encodeURIComponent(pathname)}`);
  }, [pathname, router]);

  const requireLogin = useCallback(() => {
    if (!isAuthInitialized) {
      toastInfo("로그인 상태를 확인하고 있습니다. 잠시 후 다시 시도해주세요.");
      return false;
    }

    if (!user) {
      redirectToLogin();
      return false;
    }

    return true;
  }, [isAuthInitialized, redirectToLogin, user]);

  const handleMemberActionError = useCallback(
    (err: unknown, fallbackMessage: string) => {
      if (err instanceof ApiError && err.status === 401) {
        redirectToLogin();
        return;
      }

      const message = err instanceof Error ? err.message : fallbackMessage;
      toastError(message);
    },
    [redirectToLogin]
  );

  const openRestockDialog = useCallback(() => {
    if (!requireLogin()) return;

    const userHp = (user as { mb_hp?: string } | null)?.mb_hp ?? "";
    setRestockHp(userHp);
    setRestockAgree(false);
    setRestockDialogOpen(true);
  }, [requireLogin, user]);

  const submitRestockAlert = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!product) return;

      const hp = restockHp.trim();
      if (!hp) {
        toastError("휴대폰 번호를 입력해주세요.");
        return;
      }

      if (!restockAgree) {
        toastError("개인정보처리방침 안내에 동의해 주세요.");
        return;
      }

      setRestockSubmitting(true);
      try {
        await api.post(`/shop/products/${encodeURIComponent(product.it_id)}/stock-notify`, {
          hp,
          agree: true,
        });
        addAlert(product.it_id, product.it_name);
        setRestockDialogOpen(false);
        setRestockAgree(false);
        toastSuccess("재입고 시 SMS로 알려드리겠습니다.");
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "신청에 실패했습니다.";
        toastError(message);
      } finally {
        setRestockSubmitting(false);
      }
    },
    [addAlert, product, restockAgree, restockHp]
  );

  const openRecommendDialog = useCallback(() => {
    if (!product || !requireLogin()) return;

    setRecommendToEmail("");
    setRecommendSubject(`${product.it_name} 추천`);
    setRecommendContent("");
    setRecommendDialogOpen(true);
  }, [product, requireLogin]);

  const submitRecommendation = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!product || !requireLogin()) return;

      const toEmail = recommendToEmail.trim();
      const subject = recommendSubject.trim();
      const content = recommendContent.trim();
      if (!toEmail || !subject || !content) {
        toastError("받는 사람 이메일, 제목, 내용을 입력해주세요.");
        return;
      }

      setRecommendSubmitting(true);
      try {
        const fromName = (user as { mb_nick?: string; mb_name?: string } | null)?.mb_nick
          || (user as { mb_name?: string } | null)?.mb_name
          || "";
        await api.post(`/shop/products/${encodeURIComponent(product.it_id)}/recommend`, {
          to_email: toEmail,
          from_name: fromName,
          subject,
          content,
        });
        setRecommendDialogOpen(false);
        toastSuccess("추천 메일을 발송했습니다.");
      } catch (err: unknown) {
        handleMemberActionError(err, "발송에 실패했습니다.");
      } finally {
        setRecommendSubmitting(false);
      }
    },
    [
      handleMemberActionError,
      product,
      recommendContent,
      recommendSubject,
      recommendToEmail,
      requireLogin,
      user,
    ]
  );

  useEffect(() => {
    const nextTab = productDetailTabFromSearch(productQueryString);
    setActiveTab((current) => (current === nextTab ? current : nextTab));
  }, [productQueryString]);

  useProductDetailFocusScroll(product?.it_id, productQueryString);

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

  useEffect(() => {
    if (!product) return;
    const productPath = shopProductPath(product, productRewriteMode);
    const canonical = new URL(g5ShortHref(productPath), window.location.origin).toString();
    const imageUrls = (product.images?.length ? product.images : [product.image_url])
      .map((image) => (image ? clientAbsoluteUrl(image) : undefined))
      .filter(Boolean) as string[];
    const description = product.it_explan || product.it_basic || product.it_name;

    applyClientPageMetadata({
      title: product.it_name,
      description,
      path: productPath,
      image: product.image_url || product.images?.[0],
    });
    applyClientJsonLd("article", null);
    applyClientJsonLd("product", {
      "@context": "https://schema.org/",
      "@type": "Product",
      name: product.it_name,
      description: plainTextSummary(description, product.it_name),
      sku: product.it_id,
      ...(product.it_brand ? { brand: { "@type": "Brand", name: product.it_brand } } : {}),
      ...(product.it_maker ? { manufacturer: product.it_maker } : {}),
      ...(product.it_origin ? { countryOfOrigin: product.it_origin } : {}),
      ...(imageUrls.length > 0 ? { image: imageUrls } : {}),
      offers: {
        "@type": "Offer",
        url: canonical,
        priceCurrency: "KRW",
        price: product.it_price,
        availability:
          product.it_soldout !== "1" && product.it_stock_qty !== 0
            ? "https://schema.org/InStock"
            : "https://schema.org/OutOfStock",
        itemCondition: "https://schema.org/NewCondition",
      },
      ...(product.review_count && product.review_avg
        ? {
            aggregateRating: {
              "@type": "AggregateRating",
              ratingValue: product.review_avg,
              reviewCount: product.review_count,
            },
          }
        : {}),
    });
    applyClientJsonLd("breadcrumb", {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "쇼핑몰",
          item: new URL(g5ShortHref("/shop"), window.location.origin).toString(),
        },
        ...(product.ca_id && product.ca_name
          ? [
              {
                "@type": "ListItem",
                position: 2,
                name: product.ca_name,
                item: new URL(
                  g5ShortHref(`/shop/categories/${product.ca_id}`),
                  window.location.origin
                ).toString(),
              },
            ]
          : []),
        {
          "@type": "ListItem",
          position: product.ca_id && product.ca_name ? 3 : 2,
          name: product.it_name,
          item: canonical,
        },
      ],
    });
  }, [product, productRewriteMode]);

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
    // GA4 view_item — 상품 페이지 진입 시 1회 (mount).
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
    if (product.it_soldout !== "1" && isAlerted(product.it_id)) {
      toastInfo(`${product.it_name} 재입고되었습니다!`);
      removeAlert(product.it_id);
    }
  }, [product, addRecentProduct, isAlerted, removeAlert]);

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

  const handleReviewPageChange = useCallback((nextPage: number) => {
    setPendingFocusIsId(0);
    setReviewPage(nextPage);
    scrollToProductDetailTabs();
  }, []);

  const applyQaPage = useCallback((result: Awaited<ReturnType<typeof getShopProductQaPage>>) => {
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
          setQaTotal(0);
        }
      });
    return () => {
      alive = false;
    };
  }, [activeTab, qaPage, it_id, pendingFocusIqId, applyQaPage]);

  const reloadQas = useCallback(() => {
    if (!it_id) return;
    getShopProductQaPage(it_id, qaShownPage)
      .then(applyQaPage)
      .catch(() => setQas([]));
  }, [applyQaPage, it_id, qaShownPage]);

  const handleQaPageChange = useCallback((nextPage: number) => {
    setPendingFocusIqId(0);
    setQaPage(nextPage);
    scrollToProductDetailTabs();
  }, []);

  const handleAddToCart = useCallback(async () => {
    if (!product) return;
    if (isTelInquiry) {
      toastError("전화문의 상품은 온라인 주문할 수 없습니다.");
      return;
    }

    const cartOptions = buildSelectedCartOptions();
    const hasBaseOption = cartOptions.some((option) => option.ioType === 0);
    if (optionSubjects.length > 0 && !hasBaseOption) {
      toastError("옵션을 선택해주세요.");
      return;
    }
    if (!validateBuyQtyBeforeSubmit(cartOptions)) {
      return;
    }
    setAddingToCart(true);
    try {
      if (cartOptions.length > 0) {
        if (optionSubjects.length === 0) {
          await addCartItem(product.it_id, quantity, "", {
            ctSendCost: shippingPayment.ctSendCost,
          });
        }
        await addCartItems(
          product.it_id,
          cartOptions.map((option) => ({
            io_id: option.io_id,
            ct_qty: option.qty,
            io_type: option.ioType,
          })),
          { ctSendCost: shippingPayment.ctSendCost }
        );
        setSelectedCartOptions([]);
      } else {
        await addCartItem(product.it_id, quantity, "", {
          ctSendCost: shippingPayment.ctSendCost,
        });
      }
      // GA4 add_to_cart — 옵션 합계 수량 + 단가 기준.
      gaAddToCart({
        item_id: product.it_id,
        item_name: product.it_name,
        item_category: product.ca_name,
        item_brand: product.it_brand,
        price: product.it_price,
        quantity: cartOptions.length > 0
          ? cartOptions.reduce((s, o) => s + o.qty, 0)
          : quantity,
      });
      notifyCartChanged();
      toastSuccess("장바구니에 추가되었습니다.", {
        action: (
          <ToastAction
            altText="장바구니 페이지로 이동"
            onClick={() => runtimeRouterPush(router, g5ShortHref("/shop/cart"))}
          >
            바로가기
          </ToastAction>
        ),
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "장바구니 추가에 실패했습니다.";
      toastError(message);
    } finally {
      setAddingToCart(false);
    }
  }, [
    product,
    isTelInquiry,
    quantity,
    buildSelectedCartOptions,
    validateBuyQtyBeforeSubmit,
    shippingPayment.ctSendCost,
    optionSubjects.length,
    setSelectedCartOptions,
    router,
  ]);

  const handleBuyNow = useCallback(async () => {
    if (!product) return;
    if (isTelInquiry) {
      toastError("전화문의 상품은 온라인 주문할 수 없습니다.");
      return;
    }

    const cartOptions = buildSelectedCartOptions();
    const hasBaseOption = cartOptions.some((option) => option.ioType === 0);
    if (optionSubjects.length > 0 && !hasBaseOption) {
      toastError("옵션을 선택해주세요.");
      return;
    }
    if (!validateBuyQtyBeforeSubmit(cartOptions)) {
      return;
    }
    try {
      const directCartIds: string[] = [];
      if (cartOptions.length > 0) {
        let addedDirectBase = false;
        if (optionSubjects.length === 0) {
          const response = await addCartItemDirect(product.it_id, quantity, "", {
            ctSendCost: shippingPayment.ctSendCost,
          });
          directCartIds.push(...cartIdsFromAddResponse(response));
          addedDirectBase = true;
        }
        const response = await addCartItems(
          product.it_id,
          cartOptions.map((option) => ({
            io_id: option.io_id,
            ct_qty: option.qty,
            io_type: option.ioType,
          })),
          {
            direct: true,
            replaceDirect: !addedDirectBase,
            ctSendCost: shippingPayment.ctSendCost,
          }
        );
        directCartIds.push(...cartIdsFromAddResponse(response));
        setSelectedCartOptions([]);
      } else {
        const response = await addCartItemDirect(product.it_id, quantity, "", {
          ctSendCost: shippingPayment.ctSendCost,
        });
        directCartIds.push(...cartIdsFromAddResponse(response));
      }
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
    product,
    isTelInquiry,
    quantity,
    buildSelectedCartOptions,
    validateBuyQtyBeforeSubmit,
    shippingPayment.ctSendCost,
    optionSubjects.length,
    setSelectedCartOptions,
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

  const buildNaverPayOptions = useCallback((): ShopNaverPayOrderOption[] => {
    if (!product) return [];

    const cartOptions = buildSelectedCartOptions();
    if (cartOptions.length === 0) {
      return [
        {
          io_id: "",
          io_type: 0,
          io_value: "",
          ct_qty: quantity,
        },
      ];
    }

    return cartOptions.map((option) => ({
      io_id: option.io_id,
      io_type: option.ioType,
      io_value: option.label,
      ct_qty: option.qty,
    }));
  }, [buildSelectedCartOptions, product, quantity]);

  const validateNaverPaySelection = useCallback(() => {
    if (!product) return false;
    if (isTelInquiry) {
      toastError("전화문의 상품은 네이버페이로 주문할 수 없습니다.");
      return false;
    }
    if (product.it_soldout === "1") {
      toastError("품절 상품은 네이버페이로 주문할 수 없습니다.");
      return false;
    }

    const cartOptions = buildSelectedCartOptions();
    const hasBaseOption = cartOptions.some((option) => option.ioType === 0);
    if (optionSubjects.length > 0 && !hasBaseOption) {
      toastError("옵션을 선택해주세요.");
      return false;
    }

    return validateBuyQtyBeforeSubmit(cartOptions);
  }, [
    buildSelectedCartOptions,
    isTelInquiry,
    optionSubjects.length,
    product,
    validateBuyQtyBeforeSubmit,
  ]);

  const handleNaverPayOrder = useCallback(async () => {
    if (!product || !naverPayConfig?.enabled || !validateNaverPaySelection()) return;

    setNaverPaySubmitting(true);
    try {
      const response = await registerShopNaverPayOrder({
        source: "item",
        it_id: product.it_id,
        quantity,
        options: buildNaverPayOptions(),
        back_url: window.location.href,
      });
      if (!response.redirect_url) {
        throw new Error("네이버페이 이동 URL이 없습니다.");
      }
      window.location.href = response.redirect_url;
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "네이버페이 주문 등록에 실패했습니다.";
      toastError(message);
    } finally {
      setNaverPaySubmitting(false);
    }
  }, [
    buildNaverPayOptions,
    naverPayConfig?.enabled,
    product,
    quantity,
    validateNaverPaySelection,
  ]);

  const handleNaverPayWish = useCallback(async () => {
    if (!product || !naverPayConfig?.enabled) return;

    const popup = window.open(
      "about:blank",
      "win_naverpay_wishlist",
      "scrollbars=yes,width=400,height=267"
    );
    setNaverPayWishSubmitting(true);
    try {
      const response = await registerShopNaverPayWish({ it_id: product.it_id });
      if (!response.redirect_url) {
        throw new Error("네이버페이 찜 URL이 없습니다.");
      }
      if (popup) {
        popup.location.href = response.redirect_url;
      } else {
        window.open(response.redirect_url, "_blank", "noopener,noreferrer");
      }
    } catch (err: unknown) {
      if (popup) popup.close();
      const message =
        err instanceof Error ? err.message : "네이버페이 찜 등록에 실패했습니다.";
      toastError(message);
    } finally {
      setNaverPayWishSubmitting(false);
    }
  }, [naverPayConfig?.enabled, product]);

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

  const images = (product.images?.length ? product.images : [product.image_url]).filter(Boolean);
  const pointLabel = productPointLabel(product);
  const canPurchaseProduct = !isTelInquiry && product.it_soldout !== "1";
  const hasDiscount =
    !isTelInquiry &&
    product.it_cust_price > 0 &&
    product.it_cust_price > product.it_price;
  const discountPercent = hasDiscount
    ? Math.round(
        ((product.it_cust_price - product.it_price) /
          product.it_cust_price) *
          100
      )
    : 0;

  const reviewTotal = reviewSummary?.total ?? product.review_count ?? 0;
  const reviewAverage = reviewSummary?.average ?? product.review_avg ?? 0;
  const reviewScores =
    reviewSummary?.scores ??
    Array.from({ length: 5 }, (_, index) => ({
      score: 5 - index,
      count: 0,
      percentage: 0,
    }));
  const tabs = [
    { id: "description", label: "상품설명" },
    {
      id: "reviews",
      label: `상품후기 (${product.review_count ?? 0})`,
    },
    { id: "qa", label: `상품문의 (${product.qa_count ?? 0})` },
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
  const productInfoItems = product.it_info_items ?? [];
  const restockPrivacyText = product.stock_sms_privacy?.trim() ?? "";
  const purchasePanelProps = {
    product,
    productRewriteMode,
    hasDiscount,
    discountPercent,
    isTelInquiry,
    pointLabel,
    shippingPayment,
    ctSendCostSelection,
    onCtSendCostSelectionChange: setCtSendCostSelection,
    canPurchaseProduct,
    optionSubjects,
    optionSelections,
    onOptionSelectionsChange: setOptionSelections,
    getAvailableValues,
    supplyOptions,
    supplyLabel,
    supplySelection,
    onSupplySelectionChange: setSupplySelection,
    onAddSupplyOption: handleAddSupplyOption,
    quantity,
    onQuantityChange: setQuantity,
    quantityMinQty,
    quantityMaxQty,
    minBuyQty,
    selectedOption,
    selectedCartOptions,
    onAddSelectedOption: handleAddSelectedOption,
    onUpdateSelectedOptionQty: updateSelectedOptionQty,
    onRemoveSelectedOption: removeSelectedOption,
    displayTotal,
    restockAlerted: isAlerted(product.it_id),
    onRemoveRestockAlert: () => {
      removeAlert(product.it_id);
      toastInfo("재입고 알림이 해제되었습니다.");
    },
    onOpenRestockDialog: openRestockDialog,
    addingToCart,
    onAddToCart: handleAddToCart,
    onBuyNow: handleBuyNow,
    onWishlist: handleWishlist,
    onOpenRecommendDialog: openRecommendDialog,
    naverPayConfig,
    naverPaySubmitting,
    onNaverPayOrder: handleNaverPayOrder,
    naverPayWishSubmitting,
    onNaverPayWish: handleNaverPayWish,
  };

  return (
    <div className="mx-auto w-full max-w-[1216px] md:px-2 lg:px-0">
      <Breadcrumb items={breadcrumbItems} className="mb-[30px]" />

      {productHeadHtml && (
        <div
          id="sit_hhtml"
          className="mb-6 prose max-w-none text-sm"
          dangerouslySetInnerHTML={{ __html: productHeadHtml }}
        />
      )}

      {/* Product Main */}
      <div className="grid gap-9 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] md:gap-10 lg:grid-cols-[minmax(0,1.62fr)_minmax(0,1fr)] lg:gap-16">
        <ProductImageGallery
          product={product}
          images={images}
          selectedImage={selectedImage}
          onSelectImage={setSelectedImage}
          onOpenLightbox={() => setLightboxOpen(true)}
        />

        <ProductPurchasePanel {...purchasePanelProps} />
      </div>

      <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
        <ProductDetailTabs
          activeTab={activeTab}
          onActiveTabChange={setActiveTab}
          tabs={tabs}
          product={product}
          productInfoItems={productInfoItems}
          canWriteReview={Boolean(user)}
          canWriteQa={Boolean(user)}
          shippingPolicy={shippingPolicy}
          legacyProductForm={legacyProductForm}
          onReviewSubmitted={() => {
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
          }}
          onQaSubmitted={() => {
            setPendingFocusIqId(0);
            setQaPage(1);
            getShopProductQaPage(product.it_id, 1)
              .then(applyQaPage)
              .catch(() => undefined);
          }}
          reviews={reviews}
          reviewPage={reviewShownPage}
          reviewLastPage={reviewLastPage}
          focusReviewId={reviewFocusIdFromSearch(productQueryString)}
          onReviewPageChange={handleReviewPageChange}
          reviewSummary={reviewSummary}
          reviewAverage={reviewAverage}
          reviewTotal={reviewTotal}
          reviewScores={reviewScores}
          qas={qas}
          qaPage={qaShownPage}
          qaLastPage={qaLastPage}
          qaTotal={qaTotal}
          focusQaId={qaFocusIdFromSearch(productQueryString)}
          onQaPageChange={handleQaPageChange}
          onQaChanged={reloadQas}
          shippingFreeThreshold={shippingFreeThreshold}
        />
        <aside className="mt-12 hidden min-w-0 xl:block" aria-label="고정 상품 구매 패널">
          <div className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto scrollbar-hide">
            <ProductPurchasePanel {...purchasePanelProps} variant="compact" />
          </div>
        </aside>
      </div>

      <RelatedProducts items={product.related_items} productRewriteMode={productRewriteMode} />

      <RecentlyViewed currentId={it_id} productRewriteMode={productRewriteMode} />

      {productTailHtml && (
        <div
          className="mt-10 prose max-w-none text-sm"
          dangerouslySetInnerHTML={{ __html: productTailHtml }}
        />
      )}

      <RestockAlertDialog
        open={restockDialogOpen}
        onOpenChange={setRestockDialogOpen}
        hp={restockHp}
        onHpChange={setRestockHp}
        agree={restockAgree}
        onAgreeChange={setRestockAgree}
        submitting={restockSubmitting}
        privacyText={restockPrivacyText}
        onSubmit={submitRestockAlert}
      />

      <RecommendationDialog
        open={recommendDialogOpen}
        onOpenChange={setRecommendDialogOpen}
        toEmail={recommendToEmail}
        onToEmailChange={setRecommendToEmail}
        subject={recommendSubject}
        onSubjectChange={setRecommendSubject}
        content={recommendContent}
        onContentChange={setRecommendContent}
        submitting={recommendSubmitting}
        onSubmit={submitRecommendation}
      />

      {/* Lightbox */}
      {lightboxOpen && (
        <Lightbox
          images={images.filter(Boolean) as string[]}
          currentIndex={selectedImage}
          onClose={() => setLightboxOpen(false)}
          onNavigate={(i) => {
            setSelectedImage(i);
          }}
        />
      )}
    </div>
  );
}
