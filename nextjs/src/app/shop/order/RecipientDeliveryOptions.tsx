"use client";

import { formatHopeDate } from "@/lib/hope-date";
import type { HopeDateRule } from "./orderPaymentHelpers";

type CashReceiptType = "income" | "expense";

type RecipientDeliveryOptionsProps = {
  inputClassName: string;
  memo: string;
  setMemo: (value: string) => void;
  hopeDate: string;
  setHopeDate: (value: string) => void;
  hopeDateRule: HopeDateRule | null;
  isMemberOrder: boolean;
  paymentMethod: string;
  cashReceiptEnabled: boolean;
  canRequestCashReceipt: boolean;
  taxRequest: boolean;
  setTaxRequest: (checked: boolean) => void;
  taxCompany: string;
  setTaxCompany: (value: string) => void;
  taxBusinessNo: string;
  setTaxBusinessNo: (value: string) => void;
  taxInvoiceEmail: string;
  setTaxInvoiceEmail: (value: string) => void;
  cashRequest: boolean;
  setCashRequest: (checked: boolean) => void;
  cashReceiptType: CashReceiptType;
  setCashReceiptType: (value: CashReceiptType) => void;
  cashReceiptIdentityNumber: string;
  setCashReceiptIdentityNumber: (value: string) => void;
};

export function RecipientDeliveryOptions({
  inputClassName,
  memo,
  setMemo,
  hopeDate,
  setHopeDate,
  hopeDateRule,
  isMemberOrder,
  paymentMethod,
  cashReceiptEnabled,
  canRequestCashReceipt,
  taxRequest,
  setTaxRequest,
  taxCompany,
  setTaxCompany,
  taxBusinessNo,
  setTaxBusinessNo,
  taxInvoiceEmail,
  setTaxInvoiceEmail,
  cashRequest,
  setCashRequest,
  cashReceiptType,
  setCashReceiptType,
  cashReceiptIdentityNumber,
  setCashReceiptIdentityNumber,
}: RecipientDeliveryOptionsProps) {
  const isManualBankTransfer = paymentMethod === "bank";
  const cashIdentityLabel =
    cashReceiptType === "expense"
      ? "사업자등록번호"
      : "휴대폰 번호 또는 현금영수증 카드 번호";

  return (
    <>
      <div className="mt-4">
        <label htmlFor="order-memo" className="mb-1 block text-sm font-medium">
          전하실 말씀
        </label>
        <textarea
          id="order-memo"
          value={memo}
          onChange={(event) => setMemo(event.target.value)}
          rows={2}
          placeholder="배송 요청사항"
          className={inputClassName}
        />
      </div>

      {hopeDateRule?.use && (
        <div className="mt-4">
          <label htmlFor="order-hope-date" className="mb-1 block text-sm font-medium">
            희망배송일 <span className="text-xs text-error">(필수)</span>
          </label>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <input
              id="order-hope-date"
              type="date"
              required
              value={hopeDate}
              onChange={(event) => setHopeDate(event.target.value)}
              min={hopeDateRule.min}
              max={hopeDateRule.max}
              aria-describedby="order-hope-date-help"
              className={`${inputClassName} max-w-[200px]`}
            />
            {hopeDate && (
              <span className="text-sm text-base-content/70">{formatHopeDate(hopeDate)}</span>
            )}
          </div>
          <p id="order-hope-date-help" className="mt-1 text-xs text-base-content/60">
            {formatHopeDate(hopeDateRule.min)} ~ {formatHopeDate(hopeDateRule.max)} 사이에서 선택해 주세요.
          </p>
        </div>
      )}

      {isMemberOrder && (
        <div className="mt-4 space-y-3">
          <div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={taxRequest}
                onChange={(event) => setTaxRequest(event.target.checked)}
                className="checkbox checkbox-sm"
              />
              세금계산서 신청 (사업자 전용)
            </label>
            {taxRequest && (
              <div className="mt-3 space-y-3 pl-6">
                <label className="block text-sm">
                  <span className="mb-1 block">상호명</span>
                  <input
                    type="text"
                    autoComplete="organization"
                    maxLength={100}
                    required
                    value={taxCompany}
                    onChange={(event) => setTaxCompany(event.target.value)}
                    className="input input-bordered input-sm w-full max-w-md"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block">사업자등록번호</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="off"
                    maxLength={12}
                    required
                    value={taxBusinessNo}
                    onChange={(event) =>
                      setTaxBusinessNo(event.target.value.replace(/\D/g, "").slice(0, 10))
                    }
                    placeholder="숫자 10자리"
                    className="input input-bordered input-sm w-full max-w-md"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block">세금계산서 수신 이메일</span>
                  <input
                    type="email"
                    autoComplete="email"
                    maxLength={254}
                    required
                    value={taxInvoiceEmail}
                    onChange={(event) => setTaxInvoiceEmail(event.target.value)}
                    className="input input-bordered input-sm w-full max-w-md"
                  />
                </label>
                <p className="text-xs text-base-content/60">
                  입력한 사업자 정보는 세금계산서 요청을 처리하기 위해 주문에 보관됩니다.
                </p>
              </div>
            )}
          </div>

          {cashReceiptEnabled && (
            <div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={cashRequest && canRequestCashReceipt}
                  onChange={(event) => setCashRequest(event.target.checked)}
                  className="checkbox checkbox-sm"
                  disabled={!canRequestCashReceipt}
                />
                현금영수증 발급 요청
              </label>
              {!canRequestCashReceipt ? (
                <p className="pl-6 text-xs text-base-content/60">
                  선택한 결제수단은 현금영수증 신청 대상이 아닙니다.
                </p>
              ) : cashRequest ? (
                <div className="mt-3 space-y-3 pl-6">
                  <fieldset>
                    <legend className="mb-2 text-sm">발급 용도</legend>
                    <div className="flex flex-wrap gap-x-5 gap-y-2">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="radio"
                          name="cash-receipt-type"
                          value="income"
                          checked={cashReceiptType === "income"}
                          onChange={() => setCashReceiptType("income")}
                          className="radio radio-sm radio-primary"
                        />
                        소득공제
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="radio"
                          name="cash-receipt-type"
                          value="expense"
                          checked={cashReceiptType === "expense"}
                          onChange={() => setCashReceiptType("expense")}
                          className="radio radio-sm radio-primary"
                        />
                        사업자 지출증빙
                      </label>
                    </div>
                  </fieldset>

                  {!isManualBankTransfer && (
                    <label className="block text-sm">
                      <span className="mb-1 block">{cashIdentityLabel}</span>
                      <input
                        type="text"
                        inputMode="numeric"
                        autoComplete="off"
                        maxLength={30}
                        required
                        value={cashReceiptIdentityNumber}
                        onChange={(event) =>
                          setCashReceiptIdentityNumber(
                            event.target.value.replace(/\D/g, "").slice(0, 30)
                          )
                        }
                        className="input input-bordered input-sm w-full max-w-md"
                      />
                      <span className="mt-1 block text-xs text-base-content/60">
                        이 번호는 주문에 저장하지 않고 토스 결제 요청에만 전달합니다.
                      </span>
                    </label>
                  )}
                  <p className="text-xs text-base-content/60">
                    {isManualBankTransfer
                      ? "무통장입금은 입금 확인 후 관리자가 별도로 발급을 처리합니다. 발급을 위해 추가 정보가 필요하면 안내해 드립니다."
                      : "가상계좌는 입금이 확인된 뒤, 계좌이체는 결제가 승인된 뒤 발급 결과를 확인할 수 있습니다."}
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}
    </>
  );
}
