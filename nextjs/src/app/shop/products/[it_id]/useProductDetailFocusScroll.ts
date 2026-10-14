"use client";

import { useEffect, useRef } from "react";
import { qaFocusIdFromSearch, reviewFocusIdFromSearch } from "@/components/shop/productDetailHelpers";

const TABLIST_SELECTOR = '[role="tablist"][aria-label="상품 상세 정보"]';

export function scrollToProductDetailTabs(): void {
  const tablist = document.querySelector<HTMLElement>(TABLIST_SELECTOR);
  if (!tablist) return;
  const header = document.querySelector<HTMLElement>("header");
  const offset = (header?.getBoundingClientRect().height ?? 0) + 16;
  window.scrollTo({
    top: tablist.getBoundingClientRect().top + window.scrollY - offset,
    behavior: "instant",
  });
}

export function useProductDetailFocusScroll(
  productId: string | undefined,
  productQueryString: string
): void {
  const completedKey = useRef("");

  useEffect(() => {
    if (!productId) return;
    const reviewId = reviewFocusIdFromSearch(productQueryString);
    const qaId = reviewId > 0 ? 0 : qaFocusIdFromSearch(productQueryString);
    const focusId = reviewId || qaId;
    const focusSelector = reviewId
      ? `[data-review-id="${reviewId}"]`
      : `[data-qa-id="${qaId}"]`;
    const params = new URLSearchParams(productQueryString);
    if (!params.get("tab") && !params.get("form") && !focusId) return;

    const key = `${productId}?${productQueryString}`;
    if (completedKey.current === key) return;

    let stopped = false;
    let useTablist = focusId === 0;
    let tries = 0;
    const timers: number[] = [];
    const stopEvents = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    const stop = () => {
      stopped = true;
      timers.forEach((timer) => window.clearTimeout(timer));
      stopEvents.forEach((type) => window.removeEventListener(type, stop));
    };
    const findTarget = () =>
      useTablist
        ? document.querySelector<HTMLElement>(TABLIST_SELECTOR)
        : document.querySelector<HTMLElement>(focusSelector);
    const scrollToTarget = () => {
      const target = findTarget();
      if (!target) return null;
      const header = document.querySelector<HTMLElement>("header");
      const offset = (header?.getBoundingClientRect().height ?? 0) + (useTablist ? 16 : 24);
      window.scrollTo({
        top: target.getBoundingClientRect().top + window.scrollY - offset,
        behavior: "instant",
      });
      return target;
    };
    const attempt = () => {
      if (stopped) return;
      const target = scrollToTarget();
      if (target) {
        completedKey.current = key;
        if (!useTablist) {
          target.dataset.focused = "true";
          target.focus({ preventScroll: true });
          window.setTimeout(() => {
            target.dataset.focused = "false";
          }, 5000);
        }
        stopEvents.forEach((type) => window.addEventListener(type, stop, { passive: true }));
        [500, 1500].forEach((delay) =>
          timers.push(window.setTimeout(() => !stopped && scrollToTarget(), delay))
        );
        timers.push(window.setTimeout(stop, 1600));
        return;
      }
      if (++tries < 50) {
        timers.push(window.setTimeout(attempt, 100));
      } else if (!useTablist) {
        useTablist = true;
        tries = 0;
        timers.push(window.setTimeout(attempt, 0));
      }
    };

    timers.push(window.setTimeout(attempt, 0));
    return stop;
  }, [productId, productQueryString]);
}
