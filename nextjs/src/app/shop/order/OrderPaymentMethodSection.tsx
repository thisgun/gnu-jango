"use client";

import {
  PAYMENT_METHODS,
  easyPayButtonLabel,
  isPaymentMethodEnabled,
  type PaymentConfig,
} from "./orderPaymentHelpers";

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

  return (
    <section className="box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <div className="mb-4">
        <h2 className="text-lg font-bold">결제 수단</h2>
      </div>
      {enabledMethods.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
          {enabledMethods.map((method) => (
            <button
              key={method.value}
              type="button"
              onClick={() => setPaymentMethod(method.value)}
              className={`rounded-md border px-3 py-3 text-sm font-medium transition-colors ${
                paymentMethod === method.value
                  ? "border-primary bg-primary/5 text-primary"
                  : "hover:bg-accent"
              }`}
            >
              {method.value === "easy_pay"
                ? easyPayButtonLabel(paymentConfig?.easy_pay_services)
                : method.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="alert alert-warning py-3 text-sm" role="status">
          현재 이용할 수 있는 결제 수단이 설정되어 있지 않습니다.
        </div>
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
