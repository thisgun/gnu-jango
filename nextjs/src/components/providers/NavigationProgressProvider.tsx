"use client";

import { useEffect, type ReactNode } from "react";
import { ProgressProvider } from "@bprogress/next/app";
import { useProgress } from "@bprogress/react";
import { DOCUMENT_NAVIGATION_EVENT } from "@/lib/navigation-progress";

// Transitions that finish within this time never show the bar, so cached pages do not flash it.
const PROGRESS_DELAY_MS = 120;
// A bar still on screen after this long belongs to a navigation that never happened.
const STALLED_PROGRESS_MS = 10_000;
// How long a click on a data-disable-progress element keeps the next page unload from starting the bar.
const OPT_OUT_WINDOW_MS = 1_000;

/**
 * Starts the bar when the whole document is about to be replaced. The library only follows
 * client-side transitions, but here many links go through RuntimeNavigationBridge or
 * runtimeRouterPush as `location.assign`, and pages also set `window.location` or post plain forms.
 */
function DocumentLoadProgress() {
  const { start, stop } = useProgress();

  useEffect(() => {
    let optOutUntil = 0;

    const rememberOptOut = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[data-disable-progress="true"]')) {
        optOutUntil = Date.now() + OPT_OUT_WINDOW_MS;
      }
    };

    const startForDocumentLoad = () => {
      if (Date.now() < optOutUntil) return;
      start(0, PROGRESS_DELAY_MS);
    };

    // A page restored from the back/forward cache comes back frozen with the bar mid-way.
    const stopOnRestore = (event: PageTransitionEvent) => {
      if (event.persisted) stop();
    };

    document.addEventListener("click", rememberOptOut, true);
    window.addEventListener(DOCUMENT_NAVIGATION_EVENT, startForDocumentLoad);
    window.addEventListener("beforeunload", startForDocumentLoad);
    window.addEventListener("pageshow", stopOnRestore);

    return () => {
      document.removeEventListener("click", rememberOptOut, true);
      window.removeEventListener(DOCUMENT_NAVIGATION_EVENT, startForDocumentLoad);
      window.removeEventListener("beforeunload", startForDocumentLoad);
      window.removeEventListener("pageshow", stopOnRestore);
    };
  }, [start, stop]);

  // Whoever started it, a bar left on screen means the page stayed put: a link whose click a script
  // cancelled, an app link (sms:, kakaotalk:), a download, or a load the visitor stopped.
  useEffect(() => {
    let stalledTimer: number | undefined;

    const watch = () => {
      // The library mounts its bar as a direct child of <body> and removes it when done.
      const showing = document.body.querySelector(":scope > .bprogress") !== null;
      if (showing && stalledTimer === undefined) {
        stalledTimer = window.setTimeout(() => {
          stalledTimer = undefined;
          stop();
        }, STALLED_PROGRESS_MS);
      } else if (!showing && stalledTimer !== undefined) {
        window.clearTimeout(stalledTimer);
        stalledTimer = undefined;
      }
    };

    const observer = new MutationObserver(watch);
    observer.observe(document.body, { childList: true });
    watch();

    return () => {
      observer.disconnect();
      window.clearTimeout(stalledTimer);
    };
  }, [stop]);

  return null;
}

interface NavigationProgressProviderProps {
  children: ReactNode;
}

/**
 * Top-of-page navigation progress bar (@bprogress/next). Components that navigate in code must
 * take `useRouter` from "@bprogress/next/app" and render inside this provider.
 */
export function NavigationProgressProvider({ children }: NavigationProgressProviderProps) {
  return (
    <ProgressProvider
      color="hsl(var(--primary))"
      height="3px"
      delay={PROGRESS_DELAY_MS}
      options={{ showSpinner: false }}
    >
      <DocumentLoadProgress />
      {children}
    </ProgressProvider>
  );
}
