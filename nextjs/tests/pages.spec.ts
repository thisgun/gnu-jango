import { test, expect } from '@playwright/test';

const pages = [
  { name: '메인 페이지', path: '/' },
  { name: '로그인', path: '/login' },
  { name: '회원가입', path: '/register' },
  { name: '게시판 목록', path: '/boards' },
  { name: '쇼핑몰', path: '/shop' },
  { name: '검색', path: '/search' },
  { name: '마이페이지', path: '/mypage' },
];

for (const page of pages) {
  test(`${page.name} (${page.path}) - 페이지 로드 확인`, async ({ page: p }) => {
    const errors: string[] = [];

    // 콘솔 에러 수집
    p.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(`[console.error] ${msg.text()}`);
      }
    });

    // 페이지 에러 수집
    p.on('pageerror', err => {
      errors.push(`[pageerror] ${err.message}`);
    });

    const response = await p.goto(page.path, { waitUntil: 'networkidle' });

    // HTTP 상태 확인
    const status = response?.status() ?? 0;
    console.log(`  → ${page.name}: HTTP ${status}`);

    if (errors.length > 0) {
      console.log(`  → 에러 ${errors.length}개:`);
      errors.forEach(e => console.log(`    ${e}`));
    }

    // 500 에러가 아닌지 확인
    expect(status, `${page.name} 서버 에러`).not.toBe(500);

    // 페이지에 Next.js 에러 오버레이가 없는지 확인
    const hasErrorOverlay = await p.locator('#nextjs__container_errors_label').count();
    if (hasErrorOverlay > 0) {
      const errorText = await p.locator('#nextjs__container_errors_desc').textContent();
      console.log(`  → Next.js 에러: ${errorText}`);
    }
    expect(hasErrorOverlay, `${page.name} Next.js 에러 오버레이`).toBe(0);
  });
}

test('익명 개인결제 목록은 로그인 안내만 표시한다', async ({ page }) => {
  let apiStatus = 0;
  page.on('response', (response) => {
    if (new URL(response.url()).pathname.endsWith('/api/v1/shop/personalpay')) {
      apiStatus = response.status();
    }
  });

  await page.goto('/shop/personalpay', { waitUntil: 'networkidle' });

  await expect(page.getByRole('heading', { name: '개인결제', exact: true })).toBeVisible();
  await expect(page.getByText('개인결제 목록은 로그인 후 확인할 수 있습니다.')).toBeVisible();
  await expect(page.getByRole('link', { name: '로그인', exact: true })).toHaveAttribute(
    'href',
    '/login?redirect=%2Fshop%2Fpersonalpay'
  );
  expect(apiStatus).toBe(401);
});
