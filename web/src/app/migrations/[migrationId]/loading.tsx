/**
 * Shown while a page's server data is being fetched.
 *
 * It approximates the shape of the page that is coming — a verdict band, a section label, a row
 * of tiles, then cards — so the layout does not jump when the data lands. It is deliberately
 * blank inside those shapes: a skeleton that draws fake numbers is a skeleton a reader can
 * mistake for data, which on an accounting screen is not a small mistake.
 */
function Block({ className }: { className: string }) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)] shadow-[var(--shadow-card)] ${className}`}
    />
  );
}

export default function Loading() {
  return (
    <div className="animate-pulse" role="status" aria-label="Loading">
      <span className="sr-only">Loading this view</span>
      <Block className="mb-6 h-32" />
      <div className="mb-3 h-3 w-40 rounded bg-[var(--border)]" />
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((tile) => (
          <Block key={tile} className="h-24" />
        ))}
      </div>
      <div className="mb-3 h-3 w-32 rounded bg-[var(--border)]" />
      <div className="space-y-3">
        {[0, 1, 2].map((row) => (
          <Block key={row} className="h-24" />
        ))}
      </div>
    </div>
  );
}
