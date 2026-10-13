"use client";

import { useCallback, useRef, type FormEvent } from "react";
import { useRouter } from "@bprogress/next/app";
import { submitOrder, type UseOrderSubmitOptions } from "./orderSubmitHandler";

export function useOrderSubmit({
  orderer,
  recipient,
  addressSelection,
  saveAsNewAddress,
  newAddressSubject,
  newAddressDefault,
  email,
  memo,
  hopeDate,
  taxRequest,
  cashRequest,
  guestPassword,
  isMemberOrder,
  paymentMethod,
  paymentConfig,
  bankAccount,
  depositName,
  agreeTerms,
  agreePrivacy,
  selectedCouponId,
  selectedSendCouponId,
  pointUse,
  directCheckout,
  directCtIds,
  setSubmitting,
  setPaymentNotice,
}: UseOrderSubmitOptions) {
  const router = useRouter();
  // Synchronous re-entrancy guard. setSubmitting is async React state, so it
  // cannot prevent a rapid double-click from starting a second submit before
  // the first render commits — which would create a duplicate order. The ref
  // flips synchronously on the first call and is cleared once submitOrder
  // settles.
  const submittingRef = useRef(false);

  return useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (submittingRef.current) return;
      submittingRef.current = true;
      try {
        await submitOrder({
        orderer,
        recipient,
        addressSelection,
        saveAsNewAddress,
        newAddressSubject,
        newAddressDefault,
        email,
        memo,
        hopeDate,
        taxRequest,
        cashRequest,
        guestPassword,
        isMemberOrder,
        paymentMethod,
        paymentConfig,
        bankAccount,
        depositName,
        agreeTerms,
        agreePrivacy,
        selectedCouponId,
        selectedSendCouponId,
        pointUse,
        directCheckout,
        directCtIds,
        setSubmitting,
        setPaymentNotice,
        router,
        origin: window.location.origin,
        });
      } finally {
        submittingRef.current = false;
      }
    },
    [
      orderer,
      recipient,
      addressSelection,
      saveAsNewAddress,
      newAddressSubject,
      newAddressDefault,
      email,
      memo,
      hopeDate,
      taxRequest,
      cashRequest,
      guestPassword,
      isMemberOrder,
      paymentMethod,
      paymentConfig,
      bankAccount,
      depositName,
      agreeTerms,
      agreePrivacy,
      selectedCouponId,
      selectedSendCouponId,
      pointUse,
      directCheckout,
      directCtIds,
      setSubmitting,
      setPaymentNotice,
      router,
    ]
  );
}
