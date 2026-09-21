"use client";

import Link from "next/link";

/**
 * Shown when a migration view cannot load (for example an API error).
 *
 * It says what happened and offers the two ways forward, and nothing else: no stack, no status
 * code, no endpoint. Details stay server-side, which is the same rule in the public demo as
 * anywhere else.
 */
export default function MigrationError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div
      role="alert"
      className="max-w-xl rounded-[var(--radius-card)] border border-[var(--critical)]/30 bg-[var(--critical-soft)] p-5 shadow-[var(--shadow-card)]"
    >
      <h1 className="text-base font-semibold text-[var(--critical)]">
        This view could not be loaded
      </h1>
      <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-muted)]">
        The request to the Relay API did not come back. Nothing has been changed, and the failure
        has been recorded on the server.
      </p>
      <p className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center rounded-[var(--radius-control)] border border-[var(--critical)]/50 bg-[var(--surface)] px-3 py-1.5 text-sm font-medium text-[var(--critical)] transition-colors hover:bg-white"
        >
          Try again
        </button>
        <Link href="/migrations" className="text-sm">
          Back to the command center
        </Link>
      </p>
    </div>
  );
}
