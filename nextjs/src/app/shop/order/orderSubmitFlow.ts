import { runtimeRouterPush as defaultRuntimeRouterPush } from "@/lib/runtime-router";
import {
  toastError as defaultToastError,
  toastSuccess as defaultToastSuccess,
} from "@/lib/toast";
import type {
  PaymentConfig,
  PaymentNotice,
  PayMethodDef,
} from "./orderPaymentHelpers";
import { PAYMENT_NOTICE_AUTO_DISMISS_MS } from "./orderPaymentHelpers";
import {
  CART_PAGE_PATH,
  PAYMENT_PREPARING_NOTICE,
  getCreatedOrderPath,
  isCartPriceChangedError,
  isPaymentCancelMessage,
} from "./orderSubmitFeedback";
import {
  createBankOrder as createBankOrderAction,
  requestPreparedOrderPayment as requestPreparedOrderPaymentAction,
} from "./orderSubmitActions";
import type { OrderBody } from "./orderSubmitTypes";

type RouterLike = {
  push(href: string): void;
  replace(href: string): void;
};

type SubmitBankOrderInput = {
  orderBody: OrderBody;
  bankAccount: string;
  depositName: string;
  router: RouterLike;
  setSubmitting: (submitting: boolean) => void;
  deps?: Partial<OrderSubmitFlowDeps>;
};

type SubmitPaymentOrderInput = {
  orderBody: OrderBody;
  paymentConfig: PaymentConfig | null;
  methodDef: PayMethodDef;
  origin: string;
  router?: RouterLike;
  setSubmitting: (submitting: boolean) => void;
  setPaymentNotice: (notice: PaymentNotice | null) => void;
  deps?: Partial<OrderSubmitFlowDeps>;
};

export type OrderSubmitFlowDeps = {
  createBankOrder: typeof createBankOrderAction;
  requestPreparedOrderPayment: typeof requestPreparedOrderPaymentAction;
  routerPush: typeof defaultRuntimeRouterPush;
  toastError: typeof defaultToastError;
  toastSuccess: typeof defaultToastSuccess;
  reloadPage: () => void;
};

// Long enough to read the price-change notice before the order page reloads.
const PRICE_CHANGE_RELOAD_DELAY_MS = 1800;

function reloadAfterNotice(): void {
  if (typeof window === "undefined") return;
  window.setTimeout(() => window.location.reload(), PRICE_CHANGE_RELOAD_DELAY_MS);
}

const defaultOrderSubmitFlowDeps: OrderSubmitFlowDeps = {
  createBankOrder: createBankOrderAction,
  requestPreparedOrderPayment: requestPreparedOrderPaymentAction,
  routerPush: defaultRuntimeRouterPush,
  toastError: defaultToastError,
  toastSuccess: defaultToastSuccess,
  reloadPage: reloadAfterNotice,
};

/**
 * After a cart_price_changed refusal: a buy-now order reloads the order page (its lines are not shown
 * in the cart, and the reload brings the new price); a cart order goes back to the cart.
 */
function returnToCurrentPrices(
  orderBody: OrderBody,
  router: RouterLike | undefined,
  flowDeps: OrderSubmitFlowDeps
): void {
  // buy-now and wish-list orders carry their cart line ids (the cart page orders the whole cart)
  if (orderBody.direct || orderBody.ct_ids) {
    flowDeps.reloadPage();
    return;
  }
  if (router) flowDeps.routerPush(router, CART_PAGE_PATH);
}

function resolveOrderSubmitFlowDeps(
  deps?: Partial<OrderSubmitFlowDeps>
): OrderSubmitFlowDeps {
  return { ...defaultOrderSubmitFlowDeps, ...deps };
}

export async function submitBankOrder({
  orderBody,
  bankAccount,
  depositName,
  router,
  setSubmitting,
  deps,
}: SubmitBankOrderInput): Promise<void> {
  const flowDeps = resolveOrderSubmitFlowDeps(deps);
  const runtimeRouterPush = flowDeps.routerPush;
  const toastError = flowDeps.toastError;
  const toastSuccess = flowDeps.toastSuccess;

  try {
    const createdOrder = await flowDeps.createBankOrder({
      orderBody,
      bankAccount,
      depositName,
    });
    const createdOrderPath = getCreatedOrderPath(createdOrder);
    toastSuccess("주문이 완료되었습니다. 입금을 진행해주세요.");
    runtimeRouterPush(router, createdOrderPath);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "주문에 실패했습니다.";
    toastError(message);
    if (isCartPriceChangedError(err)) returnToCurrentPrices(orderBody, router, flowDeps);
  } finally {
    setSubmitting(false);
  }
}

export async function submitPaymentOrder({
  orderBody,
  paymentConfig,
  methodDef,
  origin,
  router,
  setSubmitting,
  setPaymentNotice,
  deps,
}: SubmitPaymentOrderInput): Promise<void> {
  const flowDeps = resolveOrderSubmitFlowDeps(deps);
  const requestPreparedOrderPayment = flowDeps.requestPreparedOrderPayment;
  const toastError = flowDeps.toastError;

  if (!paymentConfig) {
    toastError("결제 설정을 불러오지 못했습니다.");
    setSubmitting(false);
    return;
  }
  if (!methodDef.pg_method) {
    toastError("결제 수단을 다시 선택해주세요.");
    setSubmitting(false);
    return;
  }

  try {
    setPaymentNotice(PAYMENT_PREPARING_NOTICE);
    await requestPreparedOrderPayment({
      orderBody,
      paymentConfig,
      methodDef,
      origin,
      onPaymentProgress: setPaymentNotice,
    });
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : "결제 요청에 실패했습니다.";
    const isCancelled = isPaymentCancelMessage(message);
    setPaymentNotice({
      tone: "error",
      title: isCancelled ? "결제가 취소되었습니다." : "결제 요청에 실패했습니다.",
      message,
    });
    toastError(message, { duration: PAYMENT_NOTICE_AUTO_DISMISS_MS });
    setSubmitting(false);
    if (isCartPriceChangedError(err)) returnToCurrentPrices(orderBody, router, flowDeps);
  }
}
