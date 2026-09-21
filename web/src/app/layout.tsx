import type { Metadata } from "next";
import Link from "next/link";

import { isPublicDemo } from "@/lib/demo";
import { currentUserEmail } from "@/lib/session";

import "./globals.css";

export const metadata: Metadata = {
  title: "Relay",
  description: "Migration operations for ERP implementations",
  robots: { index: false, follow: false },
};

/**
 * The application frame: an identity bar, the workspace, and one quiet line of disclosure.
 *
 * The bar is chrome — white, hairline-bordered, the same on every screen — so that the sunken
 * workspace below it reads as the thing being worked on. The disclosure stays at the foot of every
 * page rather than interrupting the product: a reader should be able to find out what this is
 * without being told twice on the way to the evidence.
 */
export default async function RootLayout({ children }: LayoutProps<"/">) {
  const publicDemo = isPublicDemo();
  const user = publicDemo ? null : await currentUserEmail();
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col bg-[var(--app)]">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded-[var(--radius-control)] focus:bg-[var(--surface)] focus:p-2 focus:shadow-[var(--shadow-raised)]"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface)] px-4 sm:px-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <Link
              href="/migrations"
              className="flex items-center gap-2 no-underline"
              aria-label="Relay — implementation command center"
            >
              <span
                aria-hidden="true"
                className="h-4 w-1.5 shrink-0 rounded-full bg-[var(--accent)]"
              />
              <span className="text-[15px] font-semibold tracking-tight text-[var(--ink)]">
                Relay
              </span>
            </Link>
            <span
              aria-hidden="true"
              className="hidden h-4 w-px shrink-0 bg-[var(--border)] sm:block"
            />
            <span className="hidden truncate text-xs text-[var(--ink-subtle)] sm:inline">
              ERP implementation operations
            </span>
          </div>
          {publicDemo ? (
            // No switcher: in the demo there is nothing to switch between, and a control that
            // looked like signing in would be claiming an access check that does not exist.
            <p className="flex items-center gap-2 text-sm" data-testid="demo-badge">
              <span className="rounded-full bg-[var(--accent-soft)] px-2.5 py-0.5 text-xs font-medium text-[var(--accent-ink)]">
                Public demo
              </span>
              <span className="hidden text-xs text-[var(--ink-subtle)] md:inline">
                View-only · fictional data
              </span>
            </p>
          ) : (
            <nav aria-label="Account" className="flex items-center gap-3 text-sm">
              <span
                className="max-w-[16rem] truncate text-xs text-[var(--ink-muted)]"
                data-testid="current-user"
              >
                {user ? `Acting as ${user}` : "No user selected"}
              </span>
              <Link
                href="/select-user"
                className="rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1 text-xs font-medium text-[var(--ink)] no-underline transition-colors hover:bg-[var(--surface-sunken)]"
              >
                Switch user
              </Link>
            </nav>
          )}
        </header>
        <div id="main" className="flex min-h-0 flex-1 flex-col">
          {children}
        </div>
        <footer className="shrink-0 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 sm:px-5">
          <p className="max-w-4xl text-xs leading-relaxed text-[var(--ink-subtle)]">
            Portfolio prototype · Fictional accounting data · No real company, ledger or person is
            represented here.
            {publicDemo ? (
              // Said once, here, rather than beside every action it applies to.
              <>
                {" "}
                This demo is one shared copy of a fictional implementation, so anything that would
                change it for the next visitor is left out. Everything else — the evidence, the
                reconciliation trail and the governed workflow behind each decision — is real and
                explorable.
              </>
            ) : null}
          </p>
        </footer>
      </body>
    </html>
  );
}
