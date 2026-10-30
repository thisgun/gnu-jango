// Pages whose query string carries a one-time secret (mail certify token, password reset token,
// social login / signup tickets). Analytics must never see that query, and the pages remove it from
// the address bar once they have read it.
export const SENSITIVE_QUERY_PATHS: readonly string[] = [
  "/email-certify",
  "/forgot-password",
  "/login/social-callback",
  "/register",
  // 정기구독 카드 등록 결과: the registration token and Toss's one-time authKey
  "/shop/subscriptions/billing/success",
  "/shop/subscriptions/billing/fail",
];

function normalizedPath(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, "");
  return trimmed || "/";
}

export function isSensitiveQueryPath(pathname: string): boolean {
  return SENSITIVE_QUERY_PATHS.includes(normalizedPath(pathname));
}

/** Drop the query string from the address bar (history entry included) without reloading. */
export function stripQueryFromAddressBar(): void {
  if (typeof window === "undefined" || !window.location.search) return;
  const { pathname, hash } = window.location;
  try {
    window.history.replaceState(window.history.state, "", `${pathname}${hash}`);
  } catch {
    /* replaceState can be refused in sandboxed frames — the page still works */
  }
}
