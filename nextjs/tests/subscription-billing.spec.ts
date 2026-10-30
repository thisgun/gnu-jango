import { expect, test } from "@playwright/test";
import {
  createSubscriptionBillingRequest,
  parseSubscriptionBillingReturn,
} from "../src/lib/subscription-billing";
import { subscriptionLineOf } from "../src/app/shop/products/[it_id]/ProductSubscriptionPanel";

const registration = {
  subscription_id: 7,
  registration_token: "tok en/1",
  customer_key: "gj_random_customer_key_000",
  client_key: "test_ck_fake",
  customer_name: "구독 회원",
  customer_email: "",
  expires_at: null,
};

function params(values: Record<string, string>) {
  return new URLSearchParams(values);
}

test.describe("정기구독 카드 등록 helpers", () => {
  test("the billing window request carries the token in both return addresses and no empty email", () => {
    const request = createSubscriptionBillingRequest(registration, "https://shop.example.com");

    expect(request.method).toBe("CARD");
    expect(request.successUrl).toBe("https://shop.example.com/shop/subscriptions/billing/success?token=tok%20en%2F1");
    expect(request.failUrl).toBe("https://shop.example.com/shop/subscriptions/billing/fail?token=tok%20en%2F1");
    expect(request).toMatchObject({ customerName: "구독 회원" });
    expect(request).not.toHaveProperty("customerEmail");
  });

  test("the success return needs the token, authKey and customerKey", () => {
    expect(
      parseSubscriptionBillingReturn(params({ token: "t", authKey: "a", customerKey: "c" }), "success")
    ).toEqual({ kind: "success", registrationToken: "t", authKey: "a", customerKey: "c" });
    expect(parseSubscriptionBillingReturn(params({ token: "t", authKey: "a" }), "success")).toEqual({ kind: "invalid" });
  });

  test("the fail return keeps Toss's code and message", () => {
    expect(
      parseSubscriptionBillingReturn(params({ token: "t", code: "PAY_PROCESS_CANCELED", message: "취소" }), "fail")
    ).toEqual({ kind: "fail", registrationToken: "t", code: "PAY_PROCESS_CANCELED", message: "취소" });
  });

  test("a subscription takes exactly one chosen option line", () => {
    const line = (io_id: string, qty: number, ioType = 0) => ({ io_id, label: io_id, qty, price: 0, stockQty: 9, ioType });

    expect(subscriptionLineOf(false, [], 3)).toEqual({ ioId: "", qty: 3, label: "" });
    expect(subscriptionLineOf(true, [line("빨강", 2), line("포장", 1, 1)], 1)).toEqual({ ioId: "빨강", qty: 2, label: "빨강" });
    expect(subscriptionLineOf(true, [], 1)).toHaveProperty("error");
    expect(subscriptionLineOf(true, [line("빨강", 1), line("파랑", 1)], 1)).toHaveProperty("error");
  });
});
