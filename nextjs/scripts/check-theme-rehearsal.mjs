import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';

const config = JSON.parse(readFileSync(0, 'utf8'));
if (!['baseline', 'deployed', 'restored'].includes(config.phase)) {
  throw new Error('Unknown rehearsal phase.');
}
const origin = new URL(config.origin);
if (!['127.0.0.1', 'localhost'].includes(origin.hostname) || origin.protocol !== 'http:') {
  throw new Error('Theme rehearsal is restricted to loopback HTTP.');
}
const checks = [];
const monitoringUserAgent = 'Mozilla/5.0 Chrome/131.0.0.0 GNUThemeRehearsal monitoring';
const context = await chromium.launchPersistentContext(config.profileRoot, {
  headless: true,
  viewport: { width: 1440, height: 900 },
  // Keep automated page reads out of the site's visit/search analytics.
  userAgent: monitoringUserAgent,
});
const page = await context.newPage();
context.setDefaultTimeout(15000);
context.setDefaultNavigationTimeout(15000);
const deadline = setTimeout(() => {
  console.error('[theme-rehearsal] Browser phase deadline exceeded.');
  process.exit(1);
}, 120000);
const externalHosts = new Set();
const pageErrors = [];
const caughtZodProbes = new Set();
await page.addInitScript(() => {
  window.__themeRehearsalCspViolations = [];
  document.addEventListener('securitypolicyviolation', (event) => {
    window.__themeRehearsalCspViolations.push({ directive: event.effectiveDirective,
      blocked: event.blockedURI, source: event.sourceFile, line: event.lineNumber });
  });
});
page.on('pageerror', (error) => pageErrors.push(new URL(page.url()).pathname + ': ' + error.message));
await context.route('**/*', async (route) => {
  const url = new URL(route.request().url());
  if (['http:', 'https:'].includes(url.protocol) && url.origin !== origin.origin) {
    externalHosts.add(url.hostname);
    await route.abort();
    return;
  }
  await route.continue();
});

function check(condition, message) {
  if (!condition) throw new Error(message);
  checks.push(message);
}

async function request(path) {
  const response = await context.request.get(new URL(path, origin).href, {
    headers: { 'User-Agent': monitoringUserAgent },
  });
  check(response.status() === 200, path + ' returns HTTP 200');
  return response;
}

async function selectTheme(theme) {
  const admin = await page.goto(new URL('/admin/theme/', origin).href);
  check(admin.headers()['content-security-policy'].includes("'unsafe-eval'"),
    'Unfold admin permits Alpine expressions');
  if (page.url().includes('/admin/login')) {
    await page.locator('input[name="username"]').fill(config.username);
    await page.locator('input[name="password"]').fill(config.password);
    const loginState = await page.locator('#login-form').evaluate((form) => ({
      action: form.action,
      valid: form.checkValidity(),
      invalidFields: [...form.elements].filter((field) => field.validity && !field.validity.valid)
        .map((field) => ({ name: field.name, type: field.type, message: field.validationMessage })),
      submitButtons: [...form.querySelectorAll('[type="submit"]')]
        .map((button) => ({ tag: button.tagName, disabled: button.disabled, form: button.form?.id })),
    }));
    check(pageErrors.length === 0, 'Admin login loads without JavaScript errors: ' + pageErrors.join('; '));
    check(loginState.valid, 'Login form accepts the isolated account fields');
    const loginResponse = await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/admin/login/'),
      page.locator('#login-form').locator('input[type="submit"],button[type="submit"]').click(),
    ]).catch(async (error) => {
      await page.screenshot({ path: join(config.screenshotRoot, 'login-failure.png') });
      throw error;
    });
    check(loginResponse[0].status() === 302, 'Isolated admin login succeeds');
    await page.waitForURL((url) => !url.pathname.includes('/admin/login'));
    await page.goto(new URL('/admin/theme/', origin).href);
  }
  const form = page.locator('form').filter({
    has: page.locator('input[name="theme"][value="' + theme + '"]'),
  });
  const button = form.locator('button[type="submit"]');
  if (!(await button.isDisabled())) {
    const [applied] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/admin/theme/'),
      button.click(),
    ]);
    check(applied.status() === 302, 'Admin applies theme ' + theme);
    await page.reload();
  }
  check(await button.isDisabled(), 'Admin selected theme ' + theme);
  const adminCss = await request('/static/admin_next/css/theme_settings.css');
  check(adminCss.headers()['content-type'].includes('text/css'), 'Theme admin stylesheet is served');
}

async function verifyPage(path, title) {
  console.log('[theme-rehearsal] ' + config.phase + ': opening ' + path);
  const response = await page.goto(new URL(path, origin).href, { waitUntil: 'domcontentloaded' });
  check(response.status() === 200, 'Browser route ' + path + ' returns HTTP 200');
  if (title) await page.getByText(title, { exact: true }).first().waitFor({ timeout: 30000 });
  const csp = response.headers()['content-security-policy'];
  const nonce = csp?.match(/'nonce-([^']+)'/)?.[1];
  if (nonce) {
    const scriptTags = [...(await response.text()).matchAll(/<script\b([^>]*)>/gi)];
    check(scriptTags.length > 0 && scriptTags.every((tag) => tag[1].includes('nonce="' + nonce + '"')),
      'Exported Next scripts use the response nonce on ' + path);
    const violations = await page.evaluate(() => window.__themeRehearsalCspViolations);
    for (const violation of violations) {
      // Zod 4 probes Function("") inside try/catch, then uses its interpreter
      // when CSP rejects it. Verify the exact packaged source before allowing
      // this caught capability probe; other violations still fail the rehearsal.
      const source = new URL(violation.source, origin);
      check(violation.directive === 'script-src' && violation.blocked === 'eval' &&
        source.origin === origin.origin && source.pathname.startsWith('/_next/static/'),
      'Only the known caught Zod probe may be blocked: ' + JSON.stringify(violation));
      const bundled = await request(source.pathname);
      const bytes = await bundled.body();
      const expectedHash = config.fileHashes['theme_static/nextjs_default' + decodeURIComponent(source.pathname)];
      check(createHash('sha256').update(bytes).digest('hex') === expectedHash &&
        bytes.toString().includes('jitless') &&
        /try\{return Function\(""\),!0\}catch\([^)]*\)\{return!1\}/.test(bytes.toString()),
      'Blocked eval is the caught Zod capability probe in the verified bundle');
      caughtZodProbes.add(source.pathname);
    }
  }
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'No horizontal overflow on ' + path);
  const assetPaths = await page.locator('script[src],link[rel="stylesheet"][href]').evaluateAll(
    (nodes) => nodes.map((node) => node.src || node.href).filter(Boolean)
  );
  const localAssets = [...new Set(assetPaths)].filter((url) => new URL(url).origin === origin.origin);
  for (const url of localAssets) {
    const response = await context.request.get(url, { headers: { 'User-Agent': monitoringUserAgent } });
    check(response.status() === 200, 'Referenced asset ' + new URL(url).pathname + ' returns HTTP 200');
    const pathname = new URL(url).pathname;
    if (pathname.startsWith('/_next/static/')) {
      const expectedHash = config.fileHashes['theme_static/nextjs_default' + decodeURIComponent(pathname)];
      const actualHash = createHash('sha256').update(await response.body()).digest('hex');
      check(actualHash === expectedHash, 'Served asset matches installed bytes: ' + pathname);
    }
  }
  check(localAssets.length > 0, 'Page has local assets on ' + path);
  console.log('[theme-rehearsal] ' + config.phase + ': verified ' + path);
}

try {
  const theme = config.phase === 'deployed' ? 'nextjs_default' : 'basic';
  await selectTheme(theme);
  const home = await request('/');
  const homeHtml = await home.text();
  check(!home.headers()['content-security-policy'].includes("'unsafe-eval'"),
    'Public theme keeps eval disabled with DEBUG false');
  check(homeHtml.includes('/_next/static/') === (theme === 'nextjs_default'),
    'Home serves selected theme ' + theme);
  await verifyPage('/');
  await page.screenshot({ path: join(config.screenshotRoot, config.phase + '-home-1440.png') });
  if (theme === 'basic') {
    const homeIsBasic = await page.getByRole('heading', { name: '최신글', exact: true }).count();
    check(homeIsBasic > 0, 'Classic home renders its latest-post area');
  }
  await verifyPage(config.routes.post, config.routes.postTitle);
  await verifyPage(config.routes.product, config.routes.productTitle);
  const board = await request(config.routes.board);
  check((await board.text()).includes('/_next/static/'), 'Board route retains its supported theme shell');
  const rss = await request('/rss' + config.routes.board);
  check(rss.headers()['content-type'].includes('xml'), 'RSS remains XML across theme switching');
  const manifestResponse = await request('/manifest.webmanifest');
  const manifest = await manifestResponse.json();
  check(new URL(manifest.start_url, origin).origin === origin.origin,
    'PWA start URL uses the isolated site');
  const worker = await request('/sw.js');
  const workerHash = createHash('sha256').update(await worker.body()).digest('hex');
  check(workerHash === config.fileHashes['theme/nextjs_default/sw.js'],
    'Served service worker matches installed bytes');
  if (config.phase === 'deployed') {
    await verifyPage('/');
    // Django currently advertises pwa_enabled=false. Register explicitly in this
    // disposable browser to exercise the packaged worker's installation/update.
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await registration.update();
      window.__themeRehearsalRegistration = registration;
    });
    await page.waitForFunction(() => {
      const registration = window.__themeRehearsalRegistration;
      return registration?.active?.state === 'activated' && !registration.installing && !registration.waiting;
    }, null, { timeout: 15000 });
    const registration = await page.evaluate(async () => {
      const registration = window.__themeRehearsalRegistration;
      return { scope: registration.scope, scriptURL: registration.active?.scriptURL };
    });
    check(registration.scope === origin.origin + '/', 'Service worker owns only the staging origin');
    check(registration.scriptURL === origin.origin + '/sw.js', 'Service worker uses deployed /sw.js');
    const retained = await request('/_next/static/css/rehearsal-prior.css');
    check((await retained.text()).includes('Retained previous release asset'),
      'Previous release marker asset remains available after deployment');
    await page.setViewportSize({ width: 390, height: 844 });
    await verifyPage('/');
    await page.screenshot({ path: join(config.screenshotRoot, 'deployed-home-390.png') });
  }
  check(pageErrors.length === 0, 'Browser has no uncaught page errors: ' + [...new Set(pageErrors)].join('; '));
  check(!externalHosts.has('127.0.0.9'), 'Browser does not request the PHP reference site');
  writeFileSync(config.reportPath, JSON.stringify({
    phase: config.phase, theme, checks: checks.length,
    serviceWorkerSha256: workerHash, externalHostsBlocked: [...externalHosts],
    uncaughtPageErrors: pageErrors.length,
    caughtZodProbeBundles: [...caughtZodProbes],
  }, null, 2) + '\n');
  console.log('[theme-rehearsal-browser] ' + config.phase + ': ' + checks.length + ' checks passed');
} finally {
  await context.close();
  clearTimeout(deadline);
}
