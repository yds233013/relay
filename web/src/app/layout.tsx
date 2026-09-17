import type { Metadata } from "next";
import Link from "next/link";

import { currentUserEmail } from "@/lib/session";

import "./globals.css";

export const metadata: Metadata = {
  title: "Relay",
  description: "Migration operations for ERP implementations",
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const user = await currentUserEmail();
  return (
    <html lang="en">
      <body className="min-h-screen">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2"
        >
          Skip to content
        </a>
        <header className="flex items-center justify-between border-b border-gray-300 bg-gray-50 px-4 py-2">
          <Link href="/migrations" className="font-semibold text-gray-900">
            Relay
          </Link>
          <nav aria-label="Account" className="flex items-center gap-3 text-sm">
            <span className="text-gray-700" data-testid="current-user">
              {user ? `Acting as ${user}` : "No user selected"}
            </span>
            <Link href="/select-user" className="text-blue-800 underline">
              Switch user
            </Link>
          </nav>
        </header>
        <div id="main">{children}</div>
      </body>
    </html>
  );
}
