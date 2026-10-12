"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

function getUrl(value: string | URL | null | undefined) {
  if (!value) {
    return null;
  }

  try {
    return new URL(value.toString(), window.location.href);
  } catch {
    return null;
  }
}

function shouldShowForUrl(url: URL) {
  if (url.origin !== window.location.origin) {
    return false;
  }

  const current = window.location;
  return url.pathname !== current.pathname || url.search !== current.search;
}

function submitterAttribute(submitter: HTMLElement | null, name: string) {
  return submitter?.getAttribute(name) || "";
}

function formSubmitMethod(form: HTMLFormElement, submitter: HTMLElement | null) {
  return (submitterAttribute(submitter, "formmethod") || form.method || "get").toLowerCase();
}

function formSubmitUrl(form: HTMLFormElement, submitter: HTMLElement | null) {
  const url = getUrl(submitterAttribute(submitter, "formaction") || form.action || window.location.href);
  if (!url) {
    return null;
  }

  try {
    const params = new URLSearchParams(url.search);
    const formData = submitter ? new FormData(form, submitter) : new FormData(form);
    for (const [key, value] of formData) {
      params.append(key, typeof value === "string" ? value : value.name);
    }
    url.search = params.toString();
  } catch {
    // If FormData cannot be built for an unusual form, fall back to the action URL.
  }

  return url;
}

export function PageLoadingProvider() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const loadingRef = useRef(false);
  const fallbackTimer = useRef<number | null>(null);
  const finishTimer = useRef<number | null>(null);
  const submitTimer = useRef<number | null>(null);
  const historyStartTimer = useRef<number | null>(null);

  const clearTimers = () => {
    if (fallbackTimer.current) {
      window.clearTimeout(fallbackTimer.current);
      fallbackTimer.current = null;
    }
    if (finishTimer.current) {
      window.clearTimeout(finishTimer.current);
      finishTimer.current = null;
    }
    if (submitTimer.current) {
      window.clearTimeout(submitTimer.current);
      submitTimer.current = null;
    }
    if (historyStartTimer.current) {
      window.clearTimeout(historyStartTimer.current);
      historyStartTimer.current = null;
    }
  };

  const start = () => {
    clearTimers();
    loadingRef.current = true;
    setLoading(true);
    fallbackTimer.current = window.setTimeout(() => {
      loadingRef.current = false;
      setLoading(false);
      fallbackTimer.current = null;
    }, 8000);
  };

  const finish = () => {
    clearTimers();
    if (!loadingRef.current) return;

    if (finishTimer.current) {
      window.clearTimeout(finishTimer.current);
    }
    finishTimer.current = window.setTimeout(() => {
      loadingRef.current = false;
      setLoading(false);
      clearTimers();
    }, 180);
  };

  useEffect(() => {
    finish();
    // `searchParams` changes identity when the query string changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, searchParams]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      const target = event.target instanceof Element ? event.target : null;
      const anchor = target?.closest<HTMLAnchorElement>("a[href]");
      if (!anchor || anchor.target && anchor.target !== "_self" || anchor.download) {
        return;
      }

      const url = getUrl(anchor.href);
      if (!url || url.hash && url.pathname === location.pathname && url.search === location.search) {
        return;
      }

      if (shouldShowForUrl(url)) {
        start();
      }
    };

    const onSubmit = (event: SubmitEvent) => {
      if (event.defaultPrevented) {
        return;
      }

      const form = event.target instanceof HTMLFormElement ? event.target : null;
      if (!form) {
        return;
      }

      const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
      if (submitTimer.current) {
        window.clearTimeout(submitTimer.current);
      }

      submitTimer.current = window.setTimeout(() => {
        submitTimer.current = null;

        if (event.defaultPrevented || !form.isConnected || formSubmitMethod(form, submitter) !== "get") {
          return;
        }

        const url = formSubmitUrl(form, submitter);
        if (url && shouldShowForUrl(url)) {
          start();
        }
      }, 0);
    };

    const onPopState = () => start();
    const onBeforeUnload = () => {
      loadingRef.current = true;
      setLoading(true);
    };
    const originalPushState = window.history.pushState;
    const originalReplaceState = window.history.replaceState;
    const scheduleHistoryStart = (url: URL | null) => {
      if (!url || !shouldShowForUrl(url)) return;
      if (historyStartTimer.current) {
        window.clearTimeout(historyStartTimer.current);
      }
      historyStartTimer.current = window.setTimeout(() => {
        historyStartTimer.current = null;
        start();
      }, 0);
    };

    window.history.pushState = function pushState(data, unused, url) {
      scheduleHistoryStart(getUrl(url));
      return originalPushState.call(this, data, unused, url);
    };

    window.history.replaceState = function replaceState(data, unused, url) {
      scheduleHistoryStart(getUrl(url));
      return originalReplaceState.call(this, data, unused, url);
    };

    document.addEventListener("click", onClick, true);
    document.addEventListener("submit", onSubmit, true);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("beforeunload", onBeforeUnload);

    return () => {
      clearTimers();
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("submit", onSubmit, true);
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.history.pushState = originalPushState;
      window.history.replaceState = originalReplaceState;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className={`pointer-events-none fixed inset-x-0 top-0 z-[100] h-1 overflow-hidden bg-primary/10 transition-opacity duration-150 ${
        loading ? "opacity-100" : "opacity-0"
      }`}
      role="status"
      aria-hidden={!loading}
      aria-live={loading ? "polite" : "off"}
      aria-label="페이지를 불러오는 중"
    >
      <div className="page-loading-bar h-full rounded-r-full bg-primary shadow-[0_0_14px_hsl(var(--primary)/0.55)]" />
      <span className="sr-only">페이지를 불러오는 중</span>
    </div>
  );
}

export default PageLoadingProvider;
