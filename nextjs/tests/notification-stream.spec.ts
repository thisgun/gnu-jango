import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

const source = readFileSync(resolve("src/services/notification-stream.ts"), "utf8")
  .replace('import { apiClient } from "@/lib/api";', "const apiClient = window.notificationHarness.api;")
  .replace("export function watchNotificationStream", "function watchNotificationStream");
const script = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;

async function setup(page: Page) {
  await page.route("http://notification.test/", (route) => route.fulfill({ body: "<html></html>", contentType: "text/html" }));
  await page.goto("http://notification.test/");
  await page.clock.install();
  await page.evaluate(() => {
    const win = window as unknown as Record<string, unknown>;
    const requests: { resolve: (data: unknown) => void; aborted: boolean }[] = [];
    const sockets: FakeSocket[] = [];
    let hidden = false;
    let changes = 0;
    Math.random = () => 0;
    Object.defineProperty(document, "hidden", { get: () => hidden, configurable: true });
    class FakeSocket {
      url: string;
      sent: string[] = [];
      closed = false;
      onopen?: () => void;
      onclose?: () => void;
      onmessage?: (event: { data: string }) => void;
      constructor(url: URL) { this.url = String(url); sockets.push(this); }
      send(data: string) { this.sent.push(data); }
      close() { this.closed = true; this.onclose?.(); }
    }
    win.WebSocket = FakeSocket;
    win.notificationHarness = {
      requests, sockets,
      api: {
        post: (_path: string, _body: unknown, options: { signal: AbortSignal }) => new Promise((resolve, reject) => {
          const request = { resolve, aborted: false };
          requests.push(request);
          options.signal.addEventListener("abort", () => {
            request.aborted = true;
            reject(new DOMException("Aborted", "AbortError"));
          }, { once: true });
        }),
      },
      changed: () => { changes++; },
      changeCount: () => changes,
      visibility: (value: boolean) => { hidden = value; document.dispatchEvent(new Event("visibilitychange")); },
    };
  });
  await page.addScriptTag({ content: `${script}\nwindow.stopNotificationStream = watchNotificationStream(window.notificationHarness.changed);` });
}

type Harness = {
  requests: { resolve: (value: unknown) => void; aborted: boolean }[];
  sockets: { url: string; sent: string[]; closed: boolean; onopen: () => void; onmessage: (event: { data: string }) => void; close: () => void }[];
  visibility: (hidden: boolean) => void;
  changeCount: () => number;
};

async function ready(page: Page) {
  await page.evaluate(() => {
    const h = (window as unknown as { notificationHarness: Harness }).notificationHarness;
    h.requests[0].resolve({ data: { enabled: true, ticket: "one-use-secret", websocket_url: "ws://localhost/ws/notifications/" } });
  });
  await page.evaluate(() => {
    const h = (window as unknown as { notificationHarness: Harness }).notificationHarness;
    h.sockets[0].onopen();
    h.sockets[0].onmessage({ data: '{"type":"ready"}' });
  });
}

test("ticket is sent only in a frame and ready reconciles the inbox", async ({ page }) => {
  await setup(page);
  await ready(page);
  expect(await page.evaluate(() => {
    const h = (window as unknown as { notificationHarness: Harness }).notificationHarness;
    return h.sockets[0].url;
  })).not.toContain("secret");
  await page.clock.runFor(201);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.changeCount())).toBe(1);
});

test("a hanging HTTP ticket request aborts and retries", async ({ page }) => {
  await setup(page);
  await page.clock.runFor(8001);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests[0].aborted)).toBe(true);
  await page.clock.runFor(1100);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests.length)).toBe(2);
});

test("hidden tab cancels pending requests and resumes on return", async ({ page }) => {
  await setup(page);
  await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.visibility(true));
  await page.clock.runFor(20000);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests.length)).toBe(1);
  await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.visibility(false));
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests.length)).toBe(2);
});

test("disabled WebSocket retains REST polling", async ({ page }) => {
  await setup(page);
  await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests[0].resolve({ data: { enabled: false } }));
  await page.clock.runFor(60201);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.changeCount())).toBe(1);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.sockets.length)).toBe(0);
});

test("change bursts are coalesced and heartbeat is answered", async ({ page }) => {
  await setup(page);
  await ready(page);
  await page.clock.runFor(201);
  await page.evaluate(() => {
    const h = (window as unknown as { notificationHarness: Harness }).notificationHarness;
    for (let i = 0; i < 10; i++) h.sockets[0].onmessage({ data: '{"type":"notifications.changed"}' });
    h.sockets[0].onmessage({ data: '{"type":"ping"}' });
  });
  await page.clock.runFor(201);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.changeCount())).toBe(2);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.sockets[0].sent.at(-1))).toBe('{"type":"pong"}');
});

test("logout cleanup aborts in-flight HTTP and stops all retries", async ({ page }) => {
  await setup(page);
  await page.evaluate(() => (window as unknown as { stopNotificationStream: () => void }).stopNotificationStream());
  await page.clock.runFor(65000);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests.length)).toBe(1);
  expect(await page.evaluate(() => (window as unknown as { notificationHarness: Harness }).notificationHarness.requests[0].aborted)).toBe(true);
});

async function hangingAuthRequest(page: Page, hangRefresh: boolean) {
  await page.route("http://notification.test/", (route) => route.fulfill({ body: "<html></html>", contentType: "text/html" }));
  await page.goto("http://notification.test/");
  await page.clock.install();
  const apiSource = readFileSync(resolve("src/lib/api.ts"), "utf8")
    .replace(/^import .* from .*;\r?$/gm, "");
  const compiled = ts.transpileModule(apiSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText.replace(/^export \{\};?\s*$/gm, "").replace(/^export /gm, "");
  await page.addScriptTag({ content: `(() => {
    const apiBaseUrlForRuntime = () => 'http://notification.test/api/v1';
    const parseApiEnvelope = value => value;
    const localizeApiMessage = value => value;
    const localizeApiErrors = value => value;
    ${compiled}
    window.authRequests = [];
    window.authResult = '';
    document.cookie = 'g5_auth_hint=1; path=/';
    window.fetch = (url, options) => {
      window.authRequests.push(url);
      if (${hangRefresh} && url.endsWith('/auth/csrf')) {
        return Promise.resolve(new Response(JSON.stringify({success:true,data:{csrf_token:'csrf'}})));
      }
      if (${hangRefresh} && url.endsWith('/notifications/ticket')) {
        return Promise.resolve(new Response(JSON.stringify({success:false}), {status:401}));
      }
      return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason)));
    };
    const request = new ApiClient('http://notification.test/api/v1');
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 8000);
    request.post('/notifications/ticket', undefined, {signal:controller.signal})
      .then(() => window.authResult = 'unexpected success', error => window.authResult = error.name);
  })();` });
  await page.clock.runFor(8001);
  expect(await page.evaluate(() => (window as unknown as { authResult: string }).authResult)).toBe("AbortError");
}

test("ticket cancellation interrupts a hanging CSRF request", async ({ page }) => {
  await hangingAuthRequest(page, false);
});

test("ticket cancellation interrupts a hanging shared token refresh", async ({ page }) => {
  await hangingAuthRequest(page, true);
  expect(await page.evaluate(() => (window as unknown as { authRequests: string[] }).authRequests)).toContain("http://notification.test/api/v1/auth/refresh");
});

test.describe("built Django theme notification bell", () => {
  const base = process.env.NOTIFICATION_UI_BASE_URL;
  test.skip(!base, "Set NOTIFICATION_UI_BASE_URL for the disposable local fixture server");

  for (const width of [1280, 320]) {
    test(`community bell stays inside ${width}px viewport and Escape closes it`, async ({ page, context }) => {
      const url = new URL(base!);
      expect(url.hostname).toBe("127.0.0.1");
      await page.setViewportSize({ width, height: 800 });
      const csrf = await (await context.request.get(`${base}/api/v1/auth/csrf`)).json();
      const login = await context.request.post(`${base}/api/v1/auth/login`, {
        headers: { "X-CSRFToken": csrf.data.csrf_token },
        data: { mb_id: "notification-browser", mb_password: "notification-local-test-only" },
      });
      expect(login.status()).toBe(200);
      await page.goto(base!, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "알림", exact: true }).click();
      const popup = page.getByRole("dialog", { name: "알림 목록", exact: true });
      await expect(popup).toBeVisible();
      const bounds = await popup.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await page.keyboard.press("Escape");
      await expect(popup).toBeHidden();
    });
  }
});
