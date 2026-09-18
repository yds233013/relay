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
      <body className="min-h-screen bg-[var(--surface)]">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2"
        >
          Skip to content
        </a>
        <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-sunken)] px-4 py-2">
          <div className="flex items-baseline gap-2">
            <Link
              href="/migrations"
              className="font-semibold tracking-tight text-[var(--ink)] no-underline"
            >
              Relay
            </Link>
            <span className="hidden text-xs text-[var(--ink-subtle)] sm:inline">
              Migration operations
            </span>
          </div>
          <nav aria-label="Account" className="flex items-center gap-3 text-sm">
            <span className="text-[var(--ink-muted)]" data-testid="current-user">
              {user ? `Acting as ${user}` : "No user selected"}
            </span>
            <Link
              href="/select-user"
              className="rounded border border-[var(--border-strong)] bg-white px-2 py-0.5 text-[var(--ink)] no-underline hover:bg-[var(--surface-sunken)]"
            >
              Switch user
            </Link>
          </nav>
        </header>
        <div id="main">{children}</div>
      </body>
    </html>
  );
}
