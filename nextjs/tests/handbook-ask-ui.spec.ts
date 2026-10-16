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

  /** 질문 검색 API를 고정 응답으로 바꾼다. 결과 링크는 일부러 첫 화면("/")을 가리킨다. */
  async function mockQuestionSearch(page: import("@playwright/test").Page, answerRequests: string[]) {
    await page.route("**/api/v1/docs/ask?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("answer") === "1") answerRequests.push(url.search);
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          ok: true,
          data: {
            query: url.searchParams.get("q"),
            results: [{
              bo_table: "hb_start", wr_id: 1, book: "처음 따라하기", part: "", chapter: "다른 장", section: "",
              anchor: "", url: "/", snippet: "고정 문단", highlights: [], score: 1,
            }],
            answer: url.searchParams.get("answer") === "1" ? { text: "고정 답변 [1]", citations: [1] } : null,
            answer_enabled: true,
          },
        }),
      });
    });
  }

  test("문장 답변은 버튼을 눌렀을 때만 요청한다", async ({ page }) => {
    const answerRequests: string[] = [];
    await mockQuestionSearch(page, answerRequests);
    await page.goto("/");
    await page.getByRole("button", { name: "문서 검색" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("searchbox", { name: "문서 검색" }).fill("서버에 올리려면 무엇을 준비하나요");
    await expect(dialog.locator(".doc-ask-results a").first()).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(800);
    expect(answerRequests).toEqual([]);

    await dialog.getByRole("button", { name: "이 문단들로 문장 답변 받기" }).click();
    await expect(dialog.getByText("고정 답변 [1]")).toBeVisible();
    expect(answerRequests).toHaveLength(1);
  });

  test("장 제목을 그대로 치고 Enter 를 누르면 질문 검색 1위가 아니라 그 장을 연다", async ({ page }) => {
    await mockQuestionSearch(page, []);
    await page.goto("/");
    await page.getByRole("button", { name: "문서 검색" }).first().click();
    const dialog = page.getByRole("dialog");
    const input = dialog.getByRole("searchbox", { name: "문서 검색" });
    await input.fill("폴더 구조");
    await expect(dialog.locator(".doc-ask-results a").first()).toBeVisible({ timeout: 10000 });
    await input.press("Enter");
    await expect(page.locator("h1").first()).toHaveText("폴더 구조");
  });
});
