import Link from "next/link";

import { Panel } from "@/components/ui";
import { TABLE, TABLE_SCROLL, TD, TH, TH_RIGHT, THEAD_ROW, TR } from "@/components/table";

export interface Column<T> {
  readonly header: string;
  readonly cell: (row: T) => React.ReactNode;
  readonly align?: "left" | "right";
}

/**
 * Server-rendered table with cursor pagination. Pages are bounded by the API (at most 500 rows), so
 * the browser never holds a large result set; every page is a linkable URL.
 *
 * The caption is visible by default because a table lifted onto its own surface needs to say what
 * it is; `rowTone` lets a page tint rows whose state the data already carries.
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  rowTone,
  nextHref,
  empty = "No rows.",
}: {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  rowTone?: (row: T) => string | undefined;
  nextHref?: string | null;
  empty?: string;
}) {
  return (
    <>
      {/* A region that scrolls must be reachable by keyboard, or its rows are
          unreachable without a mouse (axe: scrollable-region-focusable). */}
      <Panel className={TABLE_SCROLL} tabIndex={0}>
        <table className={TABLE}>
          <caption className="border-b border-[var(--border)] px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
            {caption}
          </caption>
          <thead>
            <tr className={THEAD_ROW}>
              {columns.map((column) => (
                <th
                  key={column.header}
                  scope="col"
                  className={column.align === "right" ? TH_RIGHT : TH}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-[var(--ink-muted)]">
                  {empty}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={rowKey(row)} className={`${TR} ${rowTone?.(row) ?? ""}`}>
                  {columns.map((column) => (
                    <td
                      key={column.header}
                      className={`${TD} ${column.align === "right" ? "text-right tabular-nums" : ""}`}
                    >
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Panel>
      {nextHref ? (
        <p className="mt-2 text-sm">
          <Link href={nextHref}>Next page</Link>
        </p>
      ) : null}
    </>
  );
}
