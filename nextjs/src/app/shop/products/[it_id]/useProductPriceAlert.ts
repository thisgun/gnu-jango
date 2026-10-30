"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ShopProduct } from "@/lib/api";
import { toastInfo, toastSuccess } from "@/lib/toast";
import type { ProductMemberActions } from "./useProductMemberActions";

type PriceAlertState = { alerted: boolean; waiting: boolean };

/**
 * 가격 인하 알림 — 회원이 지금 가격보다 내려가면 메일과 알림으로 한 번 받는다
 * (서버 gnu_jango/shop/price_alerts.py). 쇼핑몰 설정(de_price_alert_use)이 꺼져 있으면 단추를 숨긴다.
 */
export function useProductPriceAlert(
  product: ShopProduct | null,
  enabled: boolean,
  memberActions: Pick<ProductMemberActions, "user" | "requireLogin" | "handleMemberActionError">
) {
  const { user, requireLogin, handleMemberActionError } = memberActions;
  const [alerted, setAlerted] = useState(false);
  const [busy, setBusy] = useState(false);
  const itId = product?.it_id ?? "";
  const url = `/shop/products/${encodeURIComponent(itId)}/price-alert`;

  useEffect(() => {
    // 다른 상품으로 넘어오면 앞 상품의 상태를 버리고 서버 응답을 기다린다.
    setAlerted(false);
    if (!enabled || !user || !itId) return;
    let alive = true;
    api
      .get<PriceAlertState>(url)
      .then((response) => {
        // 이미 알림을 받은 신청은 끝난 것으로 본다 — 다시 누르면 지금 가격으로 새로 신청한다.
        if (alive) setAlerted(Boolean(response.data?.alerted && response.data?.waiting));
      })
      .catch(() => {
        if (alive) setAlerted(false);
      });
    return () => {
      alive = false;
    };
  }, [enabled, itId, url, user]);

  const togglePriceAlert = useCallback(async () => {
    if (!itId || busy || !requireLogin()) return;
    setBusy(true);
    try {
      if (alerted) {
        await api.delete(url);
        setAlerted(false);
        toastInfo("가격 인하 알림을 해제했습니다.");
      } else {
        await api.post(url, {});
        setAlerted(true);
        toastSuccess("지금보다 가격이 내려가면 메일과 알림으로 알려 드릴게요.");
      }
    } catch (err: unknown) {
      handleMemberActionError(err, "가격 인하 알림을 바꾸지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }, [alerted, busy, handleMemberActionError, itId, requireLogin, url]);

  return { priceAlertEnabled: enabled, priceAlerted: alerted, priceAlertBusy: busy, togglePriceAlert };
}
