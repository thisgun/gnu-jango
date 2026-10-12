import NextLink from "next/link";
import { forwardRef, type ComponentProps } from "react";

type G5LinkProps = ComponentProps<typeof NextLink>;

/**
 * Drop-in replacement for `next/link` that defaults `prefetch` to `false`.
 *
 * Under `output: export` (the static theme build) the framework still issues
 * RSC prefetch requests (`/path?_rsc=…`) for in-viewport links, and the static
 * host answers them with 404 — harmless to navigation but noisy in the console.
 * Static exports have no RSC payloads to prefetch, so disabling it loses
 * nothing. Callers can still opt back in with `prefetch`.
 */
const G5Link = forwardRef<HTMLAnchorElement, G5LinkProps>(function G5Link(
  { prefetch = false, ...props },
  ref
) {
  return <NextLink ref={ref} prefetch={prefetch} {...props} />;
});

export { G5Link };
export default G5Link;
