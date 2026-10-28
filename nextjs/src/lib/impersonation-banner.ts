// Django sets this readable cookie while an admin views the storefront as a member
// (gnu_jango/users/impersonation.py). Its value is the preview's end time in epoch seconds.
// The cookie only drives the banner; the server enforces the read-only rule.
export const IMPERSONATION_HINT_COOKIE = "g5_impersonation";
export const IMPERSONATION_STOP_PATH = "/impersonation/";

export function impersonationExpiryFromCookie(cookieHeader: string): number | null {
  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rest] = part.split("=");
    if (rawName?.trim() !== IMPERSONATION_HINT_COOKIE) continue;
    const value = rest.join("=").trim();
    if (!/^\d{1,12}$/.test(value)) return null;
    return Number(value);
  }
  return null;
}

export function formatRemaining(expiresAtSeconds: number, nowMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(expiresAtSeconds - nowMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
