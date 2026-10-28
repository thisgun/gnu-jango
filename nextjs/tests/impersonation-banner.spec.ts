import { expect, test } from "@playwright/test";
import { formatRemaining, impersonationExpiryFromCookie } from "../src/lib/impersonation-banner";

test.describe("impersonation banner cookie", () => {
  test("reads the preview end time from the cookie header", () => {
    expect(impersonationExpiryFromCookie("g5_auth_hint=1; g5_impersonation=1761620000; other=x")).toBe(1761620000);
  });

  test("ignores a missing, malformed or similarly named cookie", () => {
    expect(impersonationExpiryFromCookie("")).toBeNull();
    expect(impersonationExpiryFromCookie("g5_auth_hint=1")).toBeNull();
    expect(impersonationExpiryFromCookie("g5_impersonation=soon")).toBeNull();
    expect(impersonationExpiryFromCookie("g5_impersonation_x=1761620000")).toBeNull();
  });

  test("formats the remaining time and never goes below zero", () => {
    expect(formatRemaining(1000, 95_000)).toBe("15:05");
    expect(formatRemaining(1000, 999_500)).toBe("0:00");
    expect(formatRemaining(1000, 2_000_000)).toBe("0:00");
  });
});
