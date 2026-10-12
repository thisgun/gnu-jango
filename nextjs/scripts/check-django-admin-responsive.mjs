import { chromium } from '@playwright/test';

const adminBaseUrl = trimTrailingSlash(process.env.ADMIN_BASE_URL || 'http://127.0.0.1:8000/admin');
const username = process.env.ADMIN_USERNAME || 'admin';
const password = process.env.ADMIN_PASSWORD || '1234';
const mobileOnly = process.argv.includes('--mobile');
const desktopOnly = process.argv.includes('--desktop');
const continueOnFailure = process.argv.includes('--continue-on-failure');

const supportedArgs = new Set(['--mobile', '--desktop', '--continue-on-failure']);
for (const arg of process.argv.slice(2)) {
  if (!supportedArgs.has(arg)) {
    fail(`Unknown argument: ${arg}`);
  }
}

const viewports = [
  { name: 'desktop', width: 1440, height: 960, isMobile: false },
  { name: 'tablet', width: 820, height: 1180, isMobile: true },
  { name: 'mobile', width: 390, height: 844, isMobile: true },
].filter((viewport) => {
  if (mobileOnly) return viewport.name === 'mobile';
  if (desktopOnly) return viewport.name === 'desktop';
  return true;
});

const paths = [
  ['Dashboard', '/'],
  ['Orders', '/shop/shoporder/'],
  ['Order report', '/shop/shoporder/reports/'],
  ['Sales rank', '/shop/shoporder/sales-rank/'],
  ['Order print', '/shop/shoporder/order-print/'],
  ['Personal pay', '/shop/shoppersonalpay/'],
  ['Products', '/shop/shopproduct/'],
  ['Site config', '/config/config/'],
  ['Users', '/auth/user/'],
  ['Groups', '/auth/group/'],
  ['Mail tools', '/core/notification/mail-tools/'],
  ['Mail campaigns', '/core/mailcampaign/'],
  ['Mail send logs', '/core/mailsendlog/'],
  ['Visit report', '/core/visitlog/reports/'],
  ['Search report', '/core/searchkeyword/reports/'],
  ['Admin logs', '/admin/logentry/'],
];

const browser = await chromium.launch();
const failures = [];
let shouldStop = false;

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      isMobile: viewport.isMobile,
      hasTouch: viewport.isMobile,
    });
    const page = await context.newPage();
    await login(page);

    for (const [label, path] of paths) {
      const url = `${adminBaseUrl}${path}`;
      const result = await checkPage(page, label, url, viewport);
      if (result.status === 'pass') {
        console.log(`[pass] ${viewport.name} ${label}`);
      } else {
        failures.push(result);
        console.error(`[fail] ${viewport.name} ${label}: ${result.reason}`);
        if (!continueOnFailure) {
          shouldStop = true;
          break;
        }
      }
    }

    await context.close();
    if (shouldStop) {
      break;
    }
  }
} finally {
  await browser.close();
}

finish();

async function login(page) {
  const response = await page.goto(`${adminBaseUrl}/login/`, { waitUntil: 'domcontentloaded' });
  if (!response || response.status() >= 400) {
    fail(`Admin login returned HTTP ${response?.status() || 'unknown'}`);
  }
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('/login/'), { timeout: 15000 }),
    page.click('input[type="submit"], button[type="submit"]'),
  ]);
}

async function checkPage(page, label, url, viewport) {
  const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  const status = response?.status() || 0;
  if (status >= 400) {
    return failure(label, url, viewport, `HTTP ${status}`);
  }

  const pageState = await page.evaluate(() => {
    const text = document.body?.innerText || '';
    const doc = document.documentElement;
    const body = document.body;
    const overflow = Math.max(doc.scrollWidth, body?.scrollWidth || 0) - doc.clientWidth;
    const tinyTargets = Array.from(document.querySelectorAll('a, button, input[type="submit"]'))
      .map((element) => element.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0 && (rect.width < 28 || rect.height < 28))
      .length;
    return {
      title: document.title,
      text,
      overflow,
      tinyTargets,
    };
  });

  if (/Traceback|Server Error|OperationalError|ProgrammingError/i.test(pageState.text)) {
    return failure(label, url, viewport, 'server error text rendered');
  }
  if (pageState.text.includes('\ufffd')) {
    return failure(label, url, viewport, 'replacement character rendered');
  }
  if (pageState.overflow > 4) {
    return failure(label, url, viewport, `document overflow ${pageState.overflow}px`);
  }
  if (viewport.isMobile && pageState.tinyTargets > 8) {
    return failure(label, url, viewport, `${pageState.tinyTargets} tiny touch targets`);
  }

  return { status: 'pass', label, url, viewport: viewport.name };
}

function failure(label, url, viewport, reason) {
  return { status: 'fail', label, url, viewport: viewport.name, reason };
}

function finish() {
  if (failures.length > 0) {
    console.error(JSON.stringify({ failures }, null, 2));
    process.exit(1);
  }
  console.log(
    JSON.stringify(
      {
        status: 'pass',
        pages: paths.length,
        viewports: viewports.map((viewport) => viewport.name),
      },
      null,
      2
    )
  );
}

function fail(message) {
  console.error(`[check-django-admin-responsive] ${message}`);
  process.exit(1);
}

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}
