"use client";

import { useEffect } from "react";
import {
  g5BasePathForRuntime,
  g5PathForRuntime,
  isG5ThemeRuntime,
  shouldRouteThroughG5,
  stripG5BasePath,
} from "@/lib/config";
import { toG5ShortPath } from "@/lib/g5-short-url";

function isPlainClick(event: MouseEvent): boolean {
  return (
    event.button === 0 &&
    !event.defaultPrevented &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

function closestAnchor(target: EventTarget | null): HTMLAnchorElement | null {
  return target instanceof Element ? target.closest<HTMLAnchorElement>("a[href]") : null;
}

function isIgnoredHref(href: string): boolean {
  const normalized = href.trim().toLowerCase();
  return (
    !normalized ||
    normalized.startsWith("#") ||
    normalized.startsWith("mailto:") ||
    normalized.startsWith("tel:") ||
    normalized.startsWith("javascript:") ||
    normalized.startsWith("data:") ||
    normalized.startsWith("vbscript:")
  );
}

function splitPathSuffix(path: string): [string, string] {
  const match = path.match(/^([^?#]*)(.*)$/);
  return [match?.[1] || "/", match?.[2] || ""];
}

export function RuntimeNavigationBridge() {
  useEffect(() => {
    const basePath = g5BasePathForRuntime();
    const shouldShorten = isG5ThemeRuntime();
    if (!basePath && !shouldShorten) return;

    function runtimeTargetFor(url: URL): string | null {
      if (url.origin !== window.location.origin) return null;

      const [pathname, suffix] = splitPathSuffix(`${url.pathname}${url.search}${url.hash}`);
      const runtimePath = `${stripG5BasePath(pathname)}${suffix}`;
      const targetPath = shouldShorten ? toG5ShortPath(runtimePath) : runtimePath;
      const targetRoute = targetPath.split(/[?#]/)[0] || "/";

      if (targetPath === runtimePath && !basePath) return null;
      if (!shouldRouteThroughG5(targetRoute) && targetPath === runtimePath) return null;

      return g5PathForRuntime(targetPath);
    }

    function handleClick(event: MouseEvent) {
      if (!isPlainClick(event)) return;

      const anchor = closestAnchor(event.target);
      if (!anchor) return;
      if (anchor.target && anchor.target !== "_self") return;
      if (anchor.hasAttribute("download")) return;

      const href = anchor.getAttribute("href") || "";
      if (isIgnoredHref(href)) return;

      const url = new URL(href, window.location.href);
      const target = runtimeTargetFor(url);
      if (!target) return;
      if (`${url.pathname}${url.search}${url.hash}` === target) return;

      event.preventDefault();
      window.location.assign(target);
    }

    // Keep React-owned href attributes unchanged so the server-rendered HTML
    // and the hydrated client tree stay identical. Runtime paths are applied
    // when the visitor activates a link.
    document.addEventListener("click", handleClick, true);

    return () => {
      document.removeEventListener("click", handleClick, true);
    };
  }, []);

  return null;
}
