import { expect, test } from "@playwright/test";
import {
  PERSONAL_PAY_FAIL_DEFAULT_MESSAGE,
  PERSONAL_PAY_RETURN_INVALID_MESSAGE,
  createPersonalPayTossRequest,
  isPersonalPayTossMethod,
  parsePersonalPayReturn,
  personalPayReturnUrl,
  type PersonalPayTossPrepared,
} from "../src/lib/personal-pay-checkout";

const prepared: PersonalPayTossPrepared = {
  pp_id: "2026102100000001",
  order_id: "pp-2026102100000001",
  order_name: "개인결제 홍길동",
  amount: 45670,
  buyer_name: "홍길동",
  buyer_email: "",
  buyer_tel: "010-1234-5678",
  method: "iche",
  client_key: "test_ck",
};

test.describe("personal pay checkout helpers", () => {
  test("returns to the pay page with a result flag", () => {
    expect(personalPayReturnUrl("https://shop.example", "A 1", "success")).toBe(
      "https://shop.example/shop/personalpay/A%201/pay?result=success"
    );
  });

  test("builds the Toss request from the server's prepared values", () => {
    const request = createPersonalPayTossRequest(prepared, "https://shop.example");
    expect(request.method).toBe("TRANSFER");
    expect(request.amount).toEqual({ currency: "KRW", value: 45670 });
    expect(request.orderId).toBe("pp-2026102100000001");
    expect(request.successUrl).toBe(
      "https://shop.example/shop/personalpay/2026102100000001/pay?result=success"
    );
    expect(request.failUrl).toContain("result=fail");
    expect(request.customerMobilePhone).toBe("01012345678");
    expect("customerEmail" in request).toBe(false);
    expect(createPersonalPayTossRequest({ ...prepared, method: "easy_pay" }, "").method).toBe("CARD");
    expect(createPersonalPayTossRequest({ ...prepared, method: "hp" }, "").method).toBe("MOBILE_PHONE");
  });

  test("reads the success, failure and broken returns", () => {
    const params = (query: string) => new URLSearchParams(query);
    expect(parsePersonalPayReturn(params(""))).toEqual({ kind: "none" });
    expect(
      parsePersonalPayReturn(params("result=success&paymentKey=k&orderId=pp-1&amount=5000"))
    ).toEqual({ kind: "success", paymentKey: "k", orderId: "pp-1", amount: 5000 });
    expect(parsePersonalPayReturn(params("result=success&paymentKey=k&orderId=pp-1&amount=5e3"))).toEqual({
      kind: "invalid",
      message: PERSONAL_PAY_RETURN_INVALID_MESSAGE,
    });
    expect(parsePersonalPayReturn(params("result=fail&code=PAY_PROCESS_CANCELED&message=취소"))).toEqual({
      kind: "fail",
      code: "PAY_PROCESS_CANCELED",
      message: "취소",
    });
    expect(parsePersonalPayReturn(params("result=fail"))).toMatchObject({
      message: PERSONAL_PAY_FAIL_DEFAULT_MESSAGE,
    });
  });

  test("offers only the Toss methods a personal pay supports", () => {
    expect(["card", "iche", "hp", "easy_pay"].every(isPersonalPayTossMethod)).toBe(true);
    expect(isPersonalPayTossMethod("vbank")).toBe(false);
    expect(isPersonalPayTossMethod("bank")).toBe(false);
  });
});
