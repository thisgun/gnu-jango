"use client";

import {
  PAYMENT_METHODS,
  easyPayButtonLabel,
  isPaymentMethodEnabled,
  type PaymentConfig,
} from "./orderPaymentHelpers";

/*
 * 결제수단 칸 — 레퍼런스 주문서(#od_pay_sl)의 타일 모양(shop-pay-method). 레퍼런스는 그누보드 설치본 img/ 의
 * pay_icon*.png 를 칸 왼쪽에 깔지만 이 앱에는 그 그림이 없어, 그림 없는 칸처럼 이름을 가운데 둔다.
 */
const TILE_CLASS =
  "shop-pay-method flex min-h-[58px] min-w-0 items-center justify-center gap-2.5 whitespace-normal break-keep rounded-[9px] border px-3 py-2 text-center text-[0.8125rem] font-medium leading-snug transition-colors";

function tileStateClass(pressed: boolean) {
  return pressed
    ? "border-primary bg-primary/5 font-bold text-primary shadow-[inset_0_0_0_1px_var(--color-primary)]"
    : "border-border hover:border-foreground/40 hover:bg-accent";
}

type OrderPaymentMethodSectionProps = {
  inputClassName: string;
  paymentMethod: string;
  setPaymentMethod: (value: string) => void;
  paymentConfig: PaymentConfig | null;
  bankAccounts: string[];
  bankAccount: string;
  setBankAccount: (value: string) => void;
  depositName: string;
  setDepositName: (value: string) => void;
};

export function OrderPaymentMethodSection({
  inputClassName,
  paymentMethod,
  setPaymentMethod,
  paymentConfig,
  bankAccounts,
  bankAccount,
  setBankAccount,
  depositName,
  setDepositName,
}: OrderPaymentMethodSectionProps) {
  const enabledMethods = PAYMENT_METHODS.filter((method) =>
    isPaymentMethodEnabled(method, paymentConfig)
  );
  // 영카트 주문서(#sod_frm_pt_alert): de_card_point 가 꺼져 있으면 PG 결제 주문에는 구매 포인트가 없다.
  const purchasePoint = paymentConfig?.purchase_point;
  const showPurchasePointNotice = Boolean(purchasePoint?.enabled && !purchasePoint.pg_orders);

  return (
    <section className="shop-order-section shop-order-section--payment box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="text-lg font-bold">결제 수단</h2>
      </div>
      {enabledMethods.length > 0 ? (
        /* 오른쪽 좁은 칸에 들어가므로 두 칸 격자로 둔다 — 레퍼런스 주문서의 #sod_frm_paysel 과 같다. */
        <div className="shop-pay-methods grid min-w-0 grid-cols-2 gap-2.5">
          {enabledMethods.map((method) => {
            const pressed = paymentMethod === method.value;
            const label =
              method.value === "easy_pay"
                ? easyPayButtonLabel(paymentConfig?.easy_pay_services)
                : method.label;
            return (
              <button
                key={method.value}
                type="button"
                onClick={() => setPaymentMethod(method.value)}
                aria-pressed={pressed}
                title={label}
                className={`${TILE_CLASS} ${tileStateClass(pressed)}`}
              >
                <span className="shop-pay-method-label min-w-0">{label}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="alert alert-warning py-3 text-sm" role="status">
          현재 이용할 수 있는 결제 수단이 설정되어 있지 않습니다.
        </div>
      )}

      {showPurchasePointNotice && enabledMethods.length > 0 && (
        <p className="shop-pay-point-notice mt-3 text-xs leading-relaxed text-muted-foreground">
          무통장입금·가상계좌 이외의 결제수단으로 결제하시면 구매 포인트를 적립해 드리지 않습니다.
        </p>
      )}

      {paymentMethod === "bank" && paymentConfig?.payment_methods.bank && (
        <div className="mt-4 space-y-3 rounded-md border bg-muted/30 p-4">
          <div>
            <label htmlFor="order-bank-account" className="mb-1 block text-sm font-medium">
              입금 계좌 <span className="text-red-700">*</span>
            </label>
            <select
              id="order-bank-account"
              aria-label="입금 계좌"
              value={bankAccount}
              onChange={(event) => setBankAccount(event.target.value)}
              className={inputClassName}
              disabled={bankAccounts.length === 0}
            >
              {bankAccounts.length === 0 ? (
                <option value="">등록된 입금 계좌가 없습니다</option>
              ) : (
                bankAccounts.map((account) => (
                  <option key={account} value={account}>
                    {account}
                  </option>
                ))
              )}
            </select>
          </div>
          <div>
            <label htmlFor="order-deposit-name" className="mb-1 block text-sm font-medium">
              입금자명 <span className="text-red-700">*</span>
            </label>
            <input
              id="order-deposit-name"
              aria-label="입금자명"
              type="text"
              value={depositName}
              onChange={(event) => setDepositName(event.target.value)}
              placeholder="입금자명"
              required
              className={inputClassName}
            />
          </div>
        </div>
      )}
    </section>
  );
}
