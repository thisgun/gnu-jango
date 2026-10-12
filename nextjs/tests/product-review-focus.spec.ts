import { expect, test } from "@playwright/test";

const productId = process.env.E2E_PRODUCT_ID || "1446772772";
const reviewId = process.env.E2E_REVIEW_ID || "793";

test("a direct product review link opens and focuses its review", async ({ page }) => {
  await page.goto(`/shop/${productId}?is_id=${reviewId}`, { waitUntil: "networkidle" });

  await expect(page.getByRole("tab", { name: /상품후기/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  const review = page.locator(`#is_${reviewId}`);
  await expect(review).toBeVisible();
  await expect(review).toBeInViewport();
  await expect(review).toHaveAttribute("data-focused", "true");
  await expect(review.locator("button[aria-expanded='true']")).toBeVisible();
  await expect(page.getByRole("button", { name: "1페이지" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("a direct review link selects the page containing that review", async ({ page }) => {
  const secondPageReviewId = process.env.E2E_SECOND_PAGE_REVIEW_ID || "485";
  await page.goto(`/shop/${productId}?is_id=${secondPageReviewId}`, {
    waitUntil: "networkidle",
  });

  const review = page.locator(`#is_${secondPageReviewId}`);
  await expect(review).toBeVisible();
  await expect(review).toBeInViewport();
  await expect(review).toHaveAttribute("data-focused", "true");
  await expect(page.getByRole("button", { name: "2페이지" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
