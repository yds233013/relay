import Link from "next/link";

export interface Column<T> {
  readonly header: string;
  readonly cell: (row: T) => React.ReactNode;
  readonly align?: "left" | "right";
}

/**
 * Server-rendered table with cursor pagination. Pages are bounded by the API (at most 500 rows), so
 * the browser never holds a large result set; every page is a linkable URL.
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  nextHref,
  empty = "No rows.",
}: {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  nextHref?: string | null;
  empty?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="mb-2 text-left text-sm font-semibold text-[var(--ink)]">
          {caption}
        </caption>
        <thead>
          <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
            {columns.map((column) => (
              <th
                key={column.header}
                scope="col"
                className={`px-2 py-1.5 font-medium ${column.align === "right" ? "text-right" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-2 py-3 text-[var(--ink-muted)]">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className="border-b border-[var(--border)]/60 align-top hover:bg-[var(--surface-sunken)]"
              >
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={`px-2 py-1.5 ${column.align === "right" ? "text-right" : ""}`}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {nextHref ? (
        <p className="mt-2 text-sm">
          <Link href={nextHref} className="underline">
            Next page
          </Link>
        </p>
      ) : null}
    </div>
  );
}
