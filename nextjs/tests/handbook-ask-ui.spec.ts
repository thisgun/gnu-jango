import { expect, test } from "@playwright/test";

const questions = [
  "서버에 올리려면 무엇을 준비하나요",
  "Vercel에 환경 변수를 어떻게 설정하나요",
  "테마를 빌드하고 정적 파일을 올리려면 무엇을 하나요",
];

test.describe("매뉴얼 질문 검색", () => {
  test("질문 문단을 찾고 결과 링크가 장 앵커로 이동한다", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    await page.getByRole("button", { name: "문서 검색" }).first().click();
    const dialog = page.getByRole("dialog");
    const input = dialog.getByRole("searchbox", { name: "문서 검색" });

    for (const question of questions) {
      await input.fill(question);
      const result = dialog.locator(".doc-ask-results a").first();
      await expect(result).toBeVisible({ timeout: 10000 });
      await expect(result).toContainText("장 열기");
      await result.click();
      await expect(page).toHaveURL(/#.+-\d+$/);
      await page.goto("/");
      await page.getByRole("button", { name: "문서 검색" }).first().click();
    }

    expect(consoleErrors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("390px 모바일에서도 질문 결과가 화면 너비 안에 들어온다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: "문서 검색" }).last().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("searchbox", { name: "문서 검색" }).fill(questions[0]);
    await expect(dialog.locator(".doc-ask-results a").first()).toBeVisible({ timeout: 10000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});
