const DEV_API_BASE_URL = "http://127.0.0.9/api/v1";
const DEV_G5_BASE_URL = "http://127.0.0.9";
const DEV_APP_BASE_URL = "http://localhost:3000";

export const CLIENT_API_BASE_URL = "/api/v1";

export interface G5NextRuntimeConfig {
  apiBaseUrl?: string;
  g5BaseUrl?: string;
  appBaseUrl?: string;
  assetBaseUrl?: string;
  themeUrl?: string;
  currentPath?: string;
}

declare global {
  interface Window {
    __G5_NEXTJS25_CONFIG__?: G5NextRuntimeConfig;
  }
}

type PublicEnvName =
  | "NEXT_PUBLIC_API_URL"
  | "NEXT_PUBLIC_G5_URL"
  | "NEXT_PUBLIC_APP_URL"
  | "NEXT_PUBLIC_AUTH_MODE";

const PUBLIC_ENV: Record<PublicEnvName, string | undefined> = {
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_G5_URL: process.env.NEXT_PUBLIC_G5_URL,
  NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
  NEXT_PUBLIC_AUTH_MODE: process.env.NEXT_PUBLIC_AUTH_MODE,
};

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function trimSlashes(value: string): string {
  return value.replace(/^\/+|\/+$/g, "");
}

function pathnameFromUrl(value: string): string {
  try {
    const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";
    return new URL(value, base).pathname;
  } catch {
    return value.split(/[?#]/)[0] || "/";
  }
}

function normalizedPathname(value: string): string {
  const pathname = pathnameFromUrl(value);
  const trimmed = trimSlashes(pathname);
  return trimmed ? `/${trimmed}` : "/";
}

export function g5BasePathForRuntime(): string {
  const runtimeBase =
    typeof window !== "undefined" ? window.__G5_NEXTJS25_CONFIG__?.appBaseUrl?.trim() : undefined;
  const configuredBase = runtimeBase || PUBLIC_ENV.NEXT_PUBLIC_APP_URL || APP_BASE_URL;
  const basePath = normalizedPathname(configuredBase);

  return basePath === "/" ? "" : basePath;
}

/**
 * gnuboard PHP 호스트의 절대 URL — `http://127.0.0.20` 형태.
 * 소셜 로그인 등 PHP 페이지로 직접 점프할 때 사용.
 */
export function g5BaseUrlForRuntime(): string {
  if (typeof window !== "undefined") {
    const runtimeBase = window.__G5_NEXTJS25_CONFIG__?.g5BaseUrl?.trim();
    if (runtimeBase) return trimTrailingSlash(runtimeBase);
  }
  const configured = PUBLIC_ENV.NEXT_PUBLIC_G5_URL?.trim() || G5_BASE_URL;
  return trimTrailingSlash(configured);
}

export function isG5ThemeRuntime(): boolean {
  return typeof window !== "undefined" && !!window.__G5_NEXTJS25_CONFIG__;
}

export function stripG5BasePath(pathname: string): string {
  const path = normalizedPathname(pathname);
  const basePath = g5BasePathForRuntime();

  if (!basePath) return path;
  if (path === basePath) return "/";
  if (path.startsWith(`${basePath}/`)) {
    return path.slice(basePath.length) || "/";
  }

  return path;
}

export function currentPathForRuntime(fallbackPathname?: string): string {
  if (typeof window === "undefined") {
    return stripG5BasePath(fallbackPathname || "/");
  }

  const pathname =
    window.location.pathname ||
    fallbackPathname ||
    window.__G5_NEXTJS25_CONFIG__?.currentPath ||
    "/";

  return stripG5BasePath(pathname);
}

export function currentPathHasTrailingSlashForRuntime(fallbackPathname?: string): boolean {
  const source =
    typeof window !== "undefined"
      ? window.__G5_NEXTJS25_CONFIG__?.currentPath ||
        window.location.pathname ||
        fallbackPathname ||
        "/"
      : fallbackPathname || "/";
  const pathname = pathnameFromUrl(source);

  return pathname.length > 1 && pathname.endsWith("/");
}

export function g5PathForRuntime(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const basePath = g5BasePathForRuntime();
  return `${basePath}${normalized === "/" ? "" : normalized}` || "/";
}

const G5_APP_ROUTE_ROOTS = new Set([
  "admin",
  "boards",
  "content",
  "faq",
  "forgot-password",
  "login",
  "mypage",
  "offline",
  "polls",
  "recent",
  "register",
  "search",
  "shop",
]);

const G5_NON_ROUTE_ROOTS = new Set([
  "_next",
  "adm",
  "api",
  "bbs",
  "css",
  "data",
  "img",
  "install",
  "js",
  "lib",
  "mobile",
  "plugin",
  "theme",
]);

export function shouldRouteThroughG5(pathname: string): boolean {
  const path = normalizedPathname(pathname);
  if (path === "/") return true;

  const parts = trimSlashes(path).split("/");
  const root = parts[0] || "";

  if (G5_APP_ROUTE_ROOTS.has(root)) return true;
  if (G5_NON_ROUTE_ROOTS.has(root) || root.includes(".")) return false;

  return /^\/[0-9A-Za-z_]+(?:\/(?:write|[0-9]+|[^/]+))?$/.test(path);
}

function publicUrl(
  name: PublicEnvName,
  developmentFallback: string,
  options: { requiredInProduction?: boolean } = {}
): string {
  const value = PUBLIC_ENV[name]?.trim();
  if (value) return trimTrailingSlash(value);

  if (
    options.requiredInProduction !== false &&
    process.env.NODE_ENV === "production" &&
    typeof window === "undefined"
  ) {
    throw new Error(`Missing ${name}. Add it to the Next.js environment variables.`);
  }

  return developmentFallback;
}

function isLoopbackHost(hostname: string): boolean {
  return hostname === "localhost"
    || hostname === "127.0.0.1"
    || hostname === "127.0.0.9"
    || hostname === "::1";
}

function validatedG5BaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("NEXT_PUBLIC_G5_URL must be an absolute http(s) URL.");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("NEXT_PUBLIC_G5_URL must use http or https.");
  }

  if (
    process.env.NODE_ENV === "production"
    && typeof window === "undefined"
    && url.protocol !== "https:"
    && !isLoopbackHost(url.hostname)
  ) {
    throw new Error("NEXT_PUBLIC_G5_URL must use https in production.");
  }

  return trimTrailingSlash(url.toString());
}

export const API_BASE_URL = publicUrl("NEXT_PUBLIC_API_URL", DEV_API_BASE_URL, {
  requiredInProduction: false,
});
export const G5_BASE_URL = validatedG5BaseUrl(
  publicUrl("NEXT_PUBLIC_G5_URL", DEV_G5_BASE_URL, {
    requiredInProduction: false,
  })
);
export const APP_BASE_URL = publicUrl("NEXT_PUBLIC_APP_URL", DEV_APP_BASE_URL, {
  requiredInProduction: false,
});

export const GALLERY_BOARDS = (process.env.NEXT_PUBLIC_GALLERY_BOARDS || "")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

export type AuthMode = "g5-jwt" | "authjs";

export const AUTH_MODE: AuthMode =
  PUBLIC_ENV.NEXT_PUBLIC_AUTH_MODE === "authjs" ? "authjs" : "g5-jwt";

export function apiBaseUrlForRuntime(): string {
  if (typeof window === "undefined") {
    // Server-side (SSR / RSC) calls the API directly instead of going through
    // the browser proxy. Prefer the server-only internal URL when set so the
    // front-end can proxy the browser via /api/v1 while SSR still reaches the
    // API host directly.
    const internal = process.env.G5_API_INTERNAL_URL?.trim();
    if (internal) return trimTrailingSlash(internal);
    return API_BASE_URL;
  }

  const runtimeApi = window.__G5_NEXTJS25_CONFIG__?.apiBaseUrl?.trim();
  if (runtimeApi) return trimTrailingSlash(runtimeApi);

  const publicApi = PUBLIC_ENV.NEXT_PUBLIC_API_URL?.trim();
  if (publicApi) return trimTrailingSlash(publicApi);

  return CLIENT_API_BASE_URL;
}

export function apiUrl(path: string): string {
  const baseUrl = apiBaseUrlForRuntime();
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export function appBaseUrlForRuntime(): string {
  if (typeof window !== "undefined") {
    const runtimeApp = window.__G5_NEXTJS25_CONFIG__?.appBaseUrl?.trim();
    if (runtimeApp) return trimTrailingSlash(runtimeApp);

    const publicApp = PUBLIC_ENV.NEXT_PUBLIC_APP_URL?.trim();
    if (publicApp) return trimTrailingSlash(publicApp);

    return window.location.origin;
  }

  return APP_BASE_URL;
}

export function assetBaseUrlForRuntime(): string {
  if (typeof window === "undefined") {
    return "";
  }

  const runtimeAssetBase = window.__G5_NEXTJS25_CONFIG__?.assetBaseUrl?.trim();
  if (runtimeAssetBase) return trimTrailingSlash(runtimeAssetBase);

  const runtimeThemeUrl = window.__G5_NEXTJS25_CONFIG__?.themeUrl?.trim();
  if (runtimeThemeUrl) return `${trimTrailingSlash(runtimeThemeUrl)}/app`;

  return "";
}

export function staticAssetUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const baseUrl = assetBaseUrlForRuntime();
  return baseUrl ? `${baseUrl}${normalizedPath}` : normalizedPath;
}

export function rootPublicAssetUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return g5PathForRuntime(normalizedPath);
}

export function appUrl(path: string): string {
  const baseUrl = appBaseUrlForRuntime();
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}
