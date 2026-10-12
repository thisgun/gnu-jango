"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { runtimeRouterReplace } from "@/lib/runtime-router";
import { useAuthStore } from "@/store/auth";

export function RedirectIfAuthenticated({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const isInitialized = useAuthStore((s) => s.isInitialized);

  useEffect(() => {
    if (isInitialized && user) {
      runtimeRouterReplace(router, "/");
    }
  }, [isInitialized, user, router]);

  // Wait for auth to settle before rendering to avoid showing a flash of the
  // form to a user who is already logged in.
  if (!isInitialized || user) return null;

  return <>{children}</>;
}
