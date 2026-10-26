"use client";

import { useEffect, useRef, type DependencyList, type RefObject } from "react";
import type { Swiper as SwiperInstance } from "swiper";
import type { SwiperModule, SwiperOptions } from "swiper/types";

type SwiperModules = typeof import("swiper/modules");

interface DynamicSwiperConfig {
  /** Modules to install. Defaults to the product-row set (A11y · Keyboard · Navigation · Pagination). */
  modules?: (modules: SwiperModules) => SwiperModule[];
  /** False skips Swiper entirely (e.g. a single banner has nothing to slide). */
  enabled?: boolean;
}

const defaultModules = (modules: SwiperModules): SwiperModule[] => [
  modules.A11y,
  modules.Keyboard,
  modules.Navigation,
  modules.Pagination,
];

/**
 * Load Swiper only after the component has mounted.
 *
 * Swiper is a browser carousel and should not be part of the server render or
 * the initial hydration chunk. The reference site lazy-loads its carousel
 * module for the same reason; this hook keeps the fallback markup server-safe
 * and initializes it as soon as the browser is ready.
 *
 * React keeps owning the markup, so callers must not change the `className`
 * of the `.swiper` container or its slides after mount — Swiper adds its own
 * classes there and a re-render with a new className would wipe them. Put
 * state classes on a wrapper element instead.
 */
export function useDynamicSwiper(
  containerRef: RefObject<HTMLElement | null>,
  options: () => SwiperOptions,
  dependencies: DependencyList,
  config: DynamicSwiperConfig = {}
) {
  const instanceRef = useRef<SwiperInstance | null>(null);
  const { modules: pickModules = defaultModules, enabled = true } = config;

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    let instance: SwiperInstance | null = null;

    void Promise.all([import("swiper"), import("swiper/modules")])
      .then(([{ default: Swiper }, modules]) => {
        if (!active || !containerRef.current) return;
        instance = new Swiper(containerRef.current, {
          ...options(),
          modules: pickModules(modules),
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
    // Options and modules are read from the current refs after mount, not during SSR.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef, enabled, ...dependencies]);

  return instanceRef;
}
