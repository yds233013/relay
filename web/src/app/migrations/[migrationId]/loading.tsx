/**
 * Shown while a page's server data is being fetched. Deliberately quiet: a shape where content is
 * about to be, not a spinner and not a fake table of numbers that a reader might take for data.
 */
export default function Loading() {
  return (
    <div className="max-w-6xl" role="status" aria-label="Loading">
      <span className="sr-only">Loading this view</span>
      <div className="mb-6 h-28 rounded-md border border-[var(--border)] bg-[var(--surface-sunken)]" />
      <div className="mb-3 h-4 w-48 rounded bg-[var(--surface-sunken)]" />
      <div className="space-y-3">
        {[0, 1, 2].map((row) => (
          <div
            key={row}
            className="h-20 rounded-md border border-[var(--border)] bg-[var(--surface-sunken)]"
          />
        ))}
      </div>
    </div>
  );
}
