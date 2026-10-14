import { expect, test } from "@playwright/test";
import { apiClient } from "../src/lib/api";
import { clearPageBootstrap, getPageBootstrap } from "../src/services/page-bootstrap";

const originalGet = apiClient.get;
let calls = 0;
let timers: Array<() => void> = [];

test.beforeEach(() => {
  calls = 0;
  timers = [];
  clearPageBootstrap();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { setTimeout: (callback: () => void) => { timers.push(callback); return timers.length; } },
  });
  apiClient.get = async <T>() => {
    calls++;
    return { success: true, data: { generation: calls } as T };
  };
});

test.afterEach(() => {
  clearPageBootstrap();
  apiClient.get = originalGet;
  Reflect.deleteProperty(globalThis, "window");
});

test("concurrent consumers and a later hydrated component share one request", async () => {
  const header = getPageBootstrap("shop");
  expect(getPageBootstrap("shop")).toBe(header);
  const data = await header;
  expect(await getPageBootstrap("shop")).toBe(data);
  expect(calls).toBe(1);
});

test("the brief completed response expires", async () => {
  await getPageBootstrap("shop");
  timers.forEach(callback => callback());
  expect((await getPageBootstrap("shop")).generation).toBe(2);
});

test("navigation or authentication invalidation asks for current data immediately", async () => {
  await getPageBootstrap("shop");
  clearPageBootstrap();
  expect((await getPageBootstrap("shop")).generation).toBe(2);
});

test("an old expiry cannot remove a newer navigation's request", async () => {
  await getPageBootstrap("shop");
  const oldExpiry = timers[0];
  clearPageBootstrap();
  const fresh = await getPageBootstrap("shop");
  oldExpiry();
  expect(await getPageBootstrap("shop")).toBe(fresh);
  expect(calls).toBe(2);
});

test("a failed request is not kept for the next consumer", async () => {
  const succeed = apiClient.get;
  apiClient.get = () => Promise.reject(new Error("offline"));
  await expect(getPageBootstrap("shop")).rejects.toThrow("offline");
  apiClient.get = succeed;
  await expect(getPageBootstrap("shop")).resolves.toEqual({ generation: 1 });
});

test("server requests do not share browser data", async () => {
  Reflect.deleteProperty(globalThis, "window");
  const [first, second] = await Promise.all([getPageBootstrap("shop"), getPageBootstrap("shop")]);
  expect(first.generation).toBe(1);
  expect(second.generation).toBe(2);
  expect(timers).toEqual([]);
});
