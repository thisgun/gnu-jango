import { RedirectIfAuthenticated } from "./redirect-if-authenticated";
import type { Metadata } from "next";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-8rem)] py-12 px-4">
      <div className="w-full max-w-md">
        <RedirectIfAuthenticated>{children}</RedirectIfAuthenticated>
      </div>
    </div>
  );
}
