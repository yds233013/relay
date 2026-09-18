import Link from "next/link";

import type { Schemas } from "@/lib/api/client";

/** Link to the exact source row (and physical lines) a record came from. */
export function SourceLocation({
  migrationId,
  lineage,
}: {
  migrationId: string;
  lineage: Schemas["LineageOut"] | null | undefined;
}) {
  if (!lineage) {
    return <span className="text-[var(--ink-muted)]">no source row</span>;
  }
  const lines =
    lineage.line_start === lineage.line_end
      ? `line ${lineage.line_start}`
      : `lines ${lineage.line_start}–${lineage.line_end}`;
  return (
    <Link
      href={`/migrations/${migrationId}/data/imports/${lineage.import_id}?cursor=${lineage.row_number - 1}#row-${lineage.row_number}`}
      className="whitespace-nowrap underline"
    >
      row {lineage.row_number}, {lines}
    </Link>
  );
}
