/** Outcome of a Server Function, carried in the URL after its redirect. */
export function Notice({ error, notice }: { error?: string; notice?: string }) {
  return (
    <>
      {error ? (
        <p
          role="alert"
          className="mb-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900"
        >
          {error}
        </p>
      ) : null}
      {notice ? (
        <p
          role="status"
          className="mb-3 rounded border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-900"
        >
          {notice}
        </p>
      ) : null}
    </>
  );
}
