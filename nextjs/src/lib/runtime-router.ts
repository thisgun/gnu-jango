import {
  g5BasePathForRuntime,
  g5PathForRuntime,
  isG5ThemeRuntime,
  shouldRouteThroughG5,
  stripG5BasePath,
} from "@/lib/config";
import { toG5ShortPath } from "@/lib/g5-short-url";
import { announceDocumentNavigation } from "@/lib/navigation-progress";

type RouterLike = {
  push(href: string): void;
  replace(href: string): void;
};

type NavigationMode = "push" | "replace";

function sameOriginRuntimePath(href: string): string | null {
  if (typeof window === "undefined") return null;

  try {
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin) return null;

    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

function splitPathSuffix(path: string): [string, string] {
  const match = path.match(/^([^?#]*)(.*)$/);
  return [match?.[1] || "/", match?.[2] || ""];
}

function shouldUseDocumentNavigation(href: string): boolean {
  const path = sameOriginRuntimePath(href);
  if (!path) return false;

  const [pathname, suffix] = splitPathSuffix(path);
  const runtimePath = `${stripG5BasePath(pathname || "/")}${suffix}`;
  const hasBasePath = !!g5BasePathForRuntime();
  const shouldShorten = isG5ThemeRuntime();
  if (!hasBasePath && !shouldShorten) return false;

  const targetPath = shouldShorten ? toG5ShortPath(runtimePath) : runtimePath;

  return (
    targetPath !== runtimePath ||
    (hasBasePath && shouldRouteThroughG5(targetPath.split(/[?#]/)[0] || "/"))
  );
}

function navigate(router: RouterLike, href: string, mode: NavigationMode) {
  if (shouldUseDocumentNavigation(href)) {
    const path = sameOriginRuntimePath(href) || href;
    const [pathname, suffix] = splitPathSuffix(path);
    const runtimePath = `${stripG5BasePath(pathname || "/")}${suffix}`;
    const targetPath = isG5ThemeRuntime() ? toG5ShortPath(runtimePath) : runtimePath;
    const target = g5PathForRuntime(targetPath);

    announceDocumentNavigation();
    if (mode === "replace") {
      window.location.replace(target);
    } else {
      window.location.assign(target);
    }
    return;
  }

  router[mode](href);
}

export function runtimeRouterPush(router: RouterLike, href: string) {
  navigate(router, href, "push");
}

export function runtimeRouterReplace(router: RouterLike, href: string) {
  navigate(router, href, "replace");
}
