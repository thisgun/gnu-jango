"use client";

import { useEffect, useRef, type DependencyList, type RefObject } from "react";
import type { Swiper as SwiperInstance } from "swiper";
import type { SwiperOptions } from "swiper/types";

/**
 * Load Swiper only after the component has mounted.
 *
 * Swiper is a browser carousel and should not be part of the server render or
 * the initial hydration chunk. The reference site lazy-loads its carousel
 * module for the same reason; this hook keeps the fallback markup server-safe
 * and initializes it as soon as the browser is ready.
 */
export function useDynamicSwiper(
  containerRef: RefObject<HTMLElement | null>,
  options: () => SwiperOptions,
  dependencies: DependencyList
) {
  const instanceRef = useRef<SwiperInstance | null>(null);

  useEffect(() => {
    let active = true;
    let instance: SwiperInstance | null = null;

    void Promise.all([import("swiper"), import("swiper/modules")])
      .then(([{ default: Swiper }, modules]) => {
        if (!active || !containerRef.current) return;
        instance = new Swiper(containerRef.current, {
          ...options(),
          modules: [modules.A11y, modules.Keyboard, modules.Navigation, modules.Pagination],
        });
        instanceRef.current = instance;
      })
      .catch(() => undefined);

    return () => {
      active = false;
      instance?.destroy(true, true);
      instanceRef.current = null;
    };
    // The caller explicitly supplies the state that changes the carousel layout.
    // Options are read from the current refs after mount, not during SSR.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef, ...dependencies]);

  return instanceRef;
}
