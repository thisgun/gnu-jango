import { apiClient } from "@/lib/api";

/** Private change hints; reconnect and missed/dropped events always reconcile through REST. */
export function watchNotificationStream(onChange: () => void): () => void {
  let stopped = false;
  let connected = false;
  let connecting = false;
  let attempt: AbortController | null = null;
  let failures = 0;
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let handshake: ReturnType<typeof setTimeout> | undefined;
  let refresh: ReturnType<typeof setTimeout> | undefined;
  let lastSync = Date.now();

  const reconcile = () => {
    if (stopped || document.hidden) return;
    if (refresh !== undefined) return;
    refresh = setTimeout(() => {
      refresh = undefined;
      if (!stopped) {
        lastSync = Date.now();
        onChange();
      }
    }, 200);
  };

  const schedule = (delay?: number) => {
    clearTimeout(retry);
    if (stopped || document.hidden) return;
    const backoff = Math.min(60_000, 1000 * 2 ** Math.min(failures++, 6));
    retry = setTimeout(() => void connect(), delay ?? backoff + Math.random() * 1000);
  };

  const connect = async () => {
    if (stopped || document.hidden || connecting || socket) return;
    connecting = true;
    const controller = new AbortController();
    attempt = controller;
    const deadline = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await apiClient.post<{
        enabled?: boolean; ticket?: string; websocket_url?: string;
      }>("/notifications/ticket", undefined, { signal: controller.signal });
      if (stopped || document.hidden) return;
      const data = response.data;
      if (!data?.enabled) {
        schedule(300_000); // WSGI/PythonAnywhere/disabled deployment: retain REST polling.
        return;
      }
      if (typeof data.ticket !== "string" || typeof data.websocket_url !== "string") {
        schedule();
        return;
      }
      const url = new URL(data.websocket_url, window.location.origin);
      if (url.protocol === "https:") url.protocol = "wss:";
      if (url.protocol === "http:") url.protocol = "ws:";
      if (!["ws:", "wss:"].includes(url.protocol) || url.username || url.password || url.search || url.hash
        || (window.location.protocol === "https:" && url.protocol !== "wss:")) {
        schedule(300_000);
        return;
      }
      const current = new WebSocket(url);
      socket = current;
      handshake = setTimeout(() => current.close(), 8000);
      current.onopen = () => {
        // One-use 30s credential in a frame, never a URL, localStorage or browser log.
        if (!stopped) current.send(JSON.stringify({ type: "authenticate", ticket: data.ticket }));
      };
      current.onmessage = (event) => {
        if (stopped || current !== socket) return;
        let message: { type?: string };
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (!message || typeof message !== "object") return;
        if (message.type === "ping") {
          current.send(JSON.stringify({ type: "pong" }));
        } else if (message.type === "ready") {
          clearTimeout(handshake);
          connected = true;
          failures = 0;
          reconcile();
        } else if (message.type === "notifications.changed") {
          reconcile();
        }
      };
      current.onerror = () => current.close();
      current.onclose = () => {
        if (current !== socket) return;
        clearTimeout(handshake);
        socket = null;
        connected = false;
        reconcile();
        schedule();
      };
    } catch {
      schedule();
    } finally {
      clearTimeout(deadline);
      if (attempt === controller) attempt = null;
      connecting = false;
    }
  };

  const visibility = () => {
    if (document.hidden) {
      clearTimeout(retry);
      clearTimeout(refresh);
      refresh = undefined;
      attempt?.abort();
      socket?.close();
    } else {
      reconcile();
      void connect();
    }
  };
  const online = () => {
    failures = 0;
    reconcile();
    void connect();
  };
  // Poll during a transport outage; reconcile every five minutes even while connected.
  const poll = setInterval(() => {
    if (!connected || Date.now() - lastSync >= 300_000) reconcile();
  }, 60_000);
  document.addEventListener("visibilitychange", visibility);
  window.addEventListener("online", online);
  void connect();

  return () => {
    stopped = true;
    attempt?.abort();
    clearTimeout(retry);
    clearTimeout(handshake);
    clearTimeout(refresh);
    clearInterval(poll);
    document.removeEventListener("visibilitychange", visibility);
    window.removeEventListener("online", online);
    socket?.close();
  };
}
