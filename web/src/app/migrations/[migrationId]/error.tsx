"use client";

import Link from "next/link";

/** Shown when a migration view cannot load (for example an API error). Details stay server-side. */
export default function MigrationError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div role="alert" className="max-w-xl rounded border border-red-300 bg-red-50 p-4 text-sm">
      <h1 className="mb-1 font-semibold text-red-900">This view could not be loaded</h1>
      <p className="mb-3 text-red-900">
        The request to the Relay API failed. The error has been logged on the server.
      </p>
      <p className="flex gap-3">
        <button
          type="button"
          onClick={reset}
          className="rounded border border-red-400 bg-white px-3 py-1"
        >
          Try again
        </button>
        <Link href="/migrations" className="underline">
          Back to portfolio
        </Link>
      </p>
    </div>
  );
}
