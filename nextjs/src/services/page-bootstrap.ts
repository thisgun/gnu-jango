import { apiClient } from "@/lib/api";
import { currentPathForRuntime } from "@/lib/config";

export type BootstrapScope = "community" | "shop";
const inFlight = new Map<BootstrapScope, Promise<Record<string, unknown>>>();

export function currentBootstrapScope(): BootstrapScope | null {
  if (typeof window === "undefined") return null;
  const path = currentPathForRuntime().replace(/\/+$/, "") || "/";
  if (path === "/") return "community";
  if (path === "/shop") return "shop";
  return null;
}

/** Share concurrent consumers only. Revisiting a page always checks the current server data. */
export function getPageBootstrap(scope: BootstrapScope): Promise<Record<string, unknown>> {
  const pending = typeof window !== "undefined" ? inFlight.get(scope) : null;
  if (pending) return pending;
  const load = apiClient.get<Record<string, unknown>>(scope === "shop" ? "/shop/home" : "/home")
    .then(response => {
      if (!response.success || !response.data || typeof response.data !== "object") {
        throw new Error("첫 화면 데이터를 불러오지 못했습니다.");
      }
      return response.data;
    });
  if (typeof window === "undefined") return load;
  const request = load.finally(() => {
    if (inFlight.get(scope) === request) inFlight.delete(scope);
  });
  inFlight.set(scope, request);
  return request;
}
