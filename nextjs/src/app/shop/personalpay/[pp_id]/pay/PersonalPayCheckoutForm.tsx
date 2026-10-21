"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatPrice } from "@/lib/utils";
import {
  PAYMENT_METHODS,
  isPaymentMethodEnabled,
  type PaymentConfig,
} from "@/app/shop/order/orderPaymentHelpers";
import { OrderPaymentMethodSection } from "@/app/shop/order/OrderPaymentMethodSection";
import { ORDER_INPUT_CLASS_NAME } from "@/app/shop/order/orderPageSectionProps";
import {
  isPersonalPayTossMethod,
  openPersonalPayTossWindow,
  type PersonalPayTossPrepared,
} from "@/lib/personal-pay-checkout";
import type { PersonalPay } from "./personalPayTypes";

type Props = {
  pp: PersonalPay;
  paymentConfig: PaymentConfig | null;
  onBankSaved: (pp: PersonalPay) => void;
};

function firstEnabledMethod(config: PaymentConfig | null) {
  return PAYMENT_METHODS.find((method) => isPaymentMethodEnabled(method, config))?.value ?? "";
}

export function PersonalPayCheckoutForm({ pp, paymentConfig, onBankSaved }: Props) {
  const bankAccounts = useMemo(() => paymentConfig?.bank_accounts ?? [], [paymentConfig]);
  const [paymentMethod, setPaymentMethod] = useState(() => firstEnabledMethod(paymentConfig));
  const [bankAccount, setBankAccount] = useState("");
  // 가려진 입금자명(홍*동)은 채워 넣지 않는다
  const [depositName, setDepositName] = useState((pp.pii_masked ? "" : pp.pp_deposit_name) || pp.pp_name || "");
  const payerCheck = pp.payer_check ?? "";
  const [payerProof, setPayerProof] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPaymentMethod((current) => {
      const def = PAYMENT_METHODS.find((method) => method.value === current);
      return def && isPaymentMethodEnabled(def, paymentConfig) ? current : firstEnabledMethod(paymentConfig);
    });
  }, [paymentConfig]);

  useEffect(() => {
    setBankAccount((current) => {
      if (current && bankAccounts.includes(current)) return current;
      if (pp.pp_bank_account && bankAccounts.includes(pp.pp_bank_account)) return pp.pp_bank_account;
      return bankAccounts[0] ?? "";
    });
  }, [bankAccounts, pp.pp_bank_account]);

  const amount = pp.pp_misu_price ?? pp.pp_price;
  const isBank = paymentMethod === "bank";
  const hasMethod = Boolean(paymentMethod);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    setError("");
    if (!hasMethod) {
      setError("결제 수단을 선택해 주세요.");
      return;
    }
    if (isBank && (!bankAccount || !depositName.trim())) {
      setError("입금 계좌와 입금자명을 입력해 주세요.");
      return;
    }
    if (payerCheck === "hp" && !/^\d{4}$/.test(payerProof.trim())) {
      setError("개인결제를 요청받은 휴대폰 번호 끝 4자리를 입력해 주세요.");
      return;
    }
    if (payerCheck === "email" && !payerProof.trim()) {
      setError("개인결제를 요청받은 이메일 주소를 입력해 주세요.");
      return;
    }
    if (!agreed) {
      setError("결제 진행에 동의해 주세요.");
      return;
    }
    const proof =
      payerCheck === "hp"
        ? { payer_hp_last4: payerProof.trim() }
        : payerCheck === "email"
          ? { payer_email: payerProof.trim() }
          : {};

    setSubmitting(true);
    try {
      const base = `/shop/personalpay/${encodeURIComponent(pp.pp_id)}`;
      if (isBank) {
        const res = await api.post<PersonalPay>(`${base}/bank`, {
          bank_account: bankAccount,
          deposit_name: depositName.trim(),
          agree: true,
          ...proof,
        });
        if (res.data) onBankSaved(res.data);
        setSubmitting(false);
        return;
      }
      if (!isPersonalPayTossMethod(paymentMethod)) {
        throw new Error("결제 수단을 다시 선택해 주세요.");
      }
      const res = await api.post<PersonalPayTossPrepared>(`${base}/toss/prepare`, {
        method: paymentMethod,
        agree: true,
        ...proof,
      });
      if (!res.data) throw new Error("결제 준비에 실패했습니다.");
      // 결제창이 결과 주소(?result=success|fail)로 이동한다
      await openPersonalPayTossWindow(res.data, window.location.origin);
      setSubmitting(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "결제 준비 중 오류가 발생했습니다.");
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <OrderPaymentMethodSection
        inputClassName={ORDER_INPUT_CLASS_NAME}
        paymentMethod={paymentMethod}
        setPaymentMethod={setPaymentMethod}
        paymentConfig={paymentConfig}
        bankAccounts={bankAccounts}
        bankAccount={bankAccount}
        setBankAccount={setBankAccount}
        depositName={depositName}
        setDepositName={setDepositName}
      />

      <section className="rounded-lg border bg-background p-6">
        <div className="flex gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0">
            <h2 className="font-semibold">결제 전 확인</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {isBank
                ? "선택한 계좌로 입금하시면 운영자가 입금을 확인한 뒤 결제 완료로 바뀝니다. 입금자명이 다르면 확인이 늦어질 수 있습니다."
                : "결제 금액은 운영자가 발급한 개인결제 금액으로 승인되며, 승인 후에는 이 화면에서 영수증을 확인할 수 있습니다."}
            </p>
          </div>
        </div>

        {payerCheck ? (
          <label className="mt-5 block text-sm">
            <span className="font-medium">
              {payerCheck === "hp" ? "결제자 확인 — 휴대폰 번호 끝 4자리" : "결제자 확인 — 요청받은 이메일 주소"}
            </span>
            <input
              className={`${ORDER_INPUT_CLASS_NAME} mt-1.5`}
              type={payerCheck === "hp" ? "text" : "email"}
              inputMode={payerCheck === "hp" ? "numeric" : "email"}
              autoComplete="off"
              maxLength={payerCheck === "hp" ? 4 : 254}
              value={payerProof}
              onChange={(event) => setPayerProof(event.target.value)}
            />
            <span className="mt-1 block text-xs text-muted-foreground">
              쇼핑몰이 개인결제를 보낸 연락처로 본인 여부를 확인합니다.
            </span>
          </label>
        ) : null}

        <label className="mt-5 flex cursor-pointer items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="checkbox checkbox-sm checkbox-primary mt-0.5"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />
          <span>결제 정보를 확인했으며 {formatPrice(amount)} 결제 진행에 동의합니다.</span>
        </label>

        {error ? (
          <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
            {error}
          </div>
        ) : null}

        <Button type="submit" className="mt-5 w-full" size="lg" disabled={!hasMethod || submitting}>
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {submitting
            ? "결제 준비 중..."
            : isBank
              ? pp.awaiting_deposit
                ? "입금 정보 변경"
                : `${formatPrice(amount)} 무통장입금 신청`
              : `${formatPrice(amount)} 결제하기`}
        </Button>
      </section>
    </form>
  );
}
