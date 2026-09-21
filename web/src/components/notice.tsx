/** Outcome of a Server Function, carried in the URL after its redirect. */
export function Notice({ error, notice }: { error?: string; notice?: string }) {
  return (
    <>
      {error ? (
        <p
          role="alert"
          className="mb-4 rounded-[var(--radius-card)] border border-[var(--critical)]/30 bg-[var(--critical-soft)] px-3.5 py-2.5 text-sm text-[var(--critical)]"
        >
          {error}
        </p>
      ) : null}
      {notice ? (
        <p
          role="status"
          className="mb-4 rounded-[var(--radius-card)] border border-[var(--positive)]/30 bg-[var(--positive-soft)] px-3.5 py-2.5 text-sm text-[var(--positive)]"
        >
          {notice}
        </p>
      ) : null}
    </>
  );
}
