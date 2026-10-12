import { expect, test } from "@playwright/test";

const productId = process.env.E2E_PRODUCT_ID || "1446772772";

test("필수 옵션 상품은 옵션을 추가하기 전 합계를 0원으로 표시한다", async ({ page }) => {
  await page.goto("/shop/" + productId, { waitUntil: "networkidle" });

  const optionSelectors = page.locator("select[data-shop-option-select]");
  await expect(optionSelectors.first()).toBeVisible();
  await expect(optionSelectors.first()).toHaveValue("");

  const totals = page.getByText("총 상품 금액", { exact: true }).locator("xpath=..").locator("span").last();
  await expect(totals.first()).toBeVisible();
  await expect(totals.first()).toHaveText("0원");
});
