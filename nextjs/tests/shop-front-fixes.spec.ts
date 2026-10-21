import { expect, test } from "@playwright/test";
import { addressFromMember } from "../src/app/shop/order/orderDataHelpers";
import { isClosedOrderStatus, normalizeOrderStatus, orderStatusLabel } from "../src/lib/order-status";
import { shopSearchHref } from "../src/lib/product-url";
import { formatDateTime } from "../src/lib/utils";

test.describe("shop front fixes", () => {
  test("the shop header search goes to the product search", () => {
    expect(shopSearchHref("  린넨 셔츠 ")).toBe("/shop/search?q=%EB%A6%B0%EB%84%A8%20%EC%85%94%EC%B8%A0");
    expect(shopSearchHref("a&b")).toBe("/shop/search?q=a%26b");
    expect(shopSearchHref("   ")).toBe("/shop/search");
  });

  test("order times show the year and the shop-local time", () => {
    expect(formatDateTime("2026-10-20T14:05:09+09:00")).toBe("2026-10-20 14:05");
    expect(formatDateTime("2026-10-20 09:30:00")).toBe("2026-10-20 09:30");
    expect(formatDateTime("2026-10-20")).toBe("2026-10-20");
    expect(formatDateTime("0000-00-00 00:00:00")).toBe("");
    expect(formatDateTime("")).toBe("");
    expect(formatDateTime(undefined)).toBe("");
    expect(formatDateTime("not a date")).toBe("");
  });

  test("one status label table for list and detail", () => {
    expect(orderStatusLabel("주문").label).toBe("입금확인중");
    expect(orderStatusLabel("입금대기").label).toBe("입금확인중");
    expect(orderStatusLabel("입금").label).toBe("입금완료");
    expect(orderStatusLabel("준비").label).toBe("상품준비중");
    expect(orderStatusLabel("배송").label).toBe("상품배송");
    expect(orderStatusLabel("완료").label).toBe("배송완료");
    expect(orderStatusLabel("취소").label).toBe("주문취소");
    // orderinquiry.sub.php: anything else reads as a cancelled order
    expect(orderStatusLabel("알수없음")).toEqual({ label: "주문취소", tone: "error" });
    expect(normalizeOrderStatus(" 배송중 ")).toBe("배송");
    // admin line changes (orderformcartupdate.php) close an order as 반품, a line also as 품절
    expect(orderStatusLabel("반품").label).toBe("반품");
    expect(orderStatusLabel("품절").label).toBe("품절취소");
    expect(["취소", "반품", "품절", "배송"].map(isClosedOrderStatus)).toEqual([true, true, true, false]);
  });

  test("the order form prefills the member contact returned by /auth/me", () => {
    const address = addressFromMember({
      mb_name: "홍길동",
      mb_hp: "010-1234-5678",
      mb_tel: "",
      mb_zip1: "062",
      mb_zip2: "36",
      mb_addr1: "서울 강남구",
      mb_addr2: "101호",
      mb_addr3: "",
      mb_addr_jibeon: "R",
    });
    expect(address).toMatchObject({
      name: "홍길동",
      hp: "010-1234-5678",
      zip: "06236",
      addr1: "서울 강남구",
      addr2: "101호",
      addr_jibeon: "R",
    });
  });
});
