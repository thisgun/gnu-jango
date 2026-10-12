import { expect, test } from "@playwright/test";

const productId = process.env.E2E_PRODUCT_ID || "1446772772";
const qaId = process.env.E2E_QA_ID || "286";

test("a direct product Q&A link opens and focuses its question", async ({ page }) => {
  await page.goto(`/shop/${productId}?iq_id=${qaId}`, { waitUntil: "networkidle" });

  await expect(page.getByRole("tab", { name: /\uC0C1\uD488\uBB38\uC758/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  const question = page.locator(`#iq_${qaId}`);
  await expect(question).toBeVisible();
  await expect(question).toBeInViewport();
  await expect(question).toHaveAttribute("data-focused", "true");
  await expect(question.locator("button[aria-expanded='true']")).toBeVisible();
  await expect(page.getByRole("button", { name: "2\uD398\uC774\uC9C0" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
