/** Fired just before code replaces the whole document with `location.assign` or `location.replace`. */
export const DOCUMENT_NAVIGATION_EVENT = "g5:document-navigation";

/**
 * Lets NavigationProgressProvider show the progress bar for a document load. It also listens for
 * `beforeunload`, but iOS Safari does not fire that event, so the bar would otherwise stay hidden
 * until the next page arrives.
 */
export function announceDocumentNavigation(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(DOCUMENT_NAVIGATION_EVENT));
}
