import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import {
  BUTTON_STYLES,
  Callout,
  EmptyState,
  MetaList,
  Panel,
  ProvenanceBadge,
} from "@/components/ui";
import { ApiError, apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ImportPage(
  props: PageProps<"/migrations/[migrationId]/data/imports/[importId]">,
) {
  const { migrationId, importId } = await props.params;
  const search = await props.searchParams;
  const cursor = Number.parseInt(param(search.cursor) ?? "0", 10);
  const safeCursor = Number.isFinite(cursor) && cursor >= 0 ? cursor : 0;
  const [record, rows, quarantine, profile] = await Promise.all([
    apiGet<Schemas["ImportOut"]>(`/api/v1/imports/${importId}`),
    apiGet<Schemas["Page_SourceRowOut_"]>(`/api/v1/imports/${importId}/rows`, {
      cursor: safeCursor,
      limit: 50,
    }),
    apiGet<Schemas["QuarantinedRowOut"][]>(`/api/v1/imports/${importId}/quarantine`),
    apiGet<Schemas["DatasetProfile"]>(`/api/v1/imports/${importId}/profile`).catch(
      (error: unknown) => {
        // A missing profile is normal (for example a failed import); anything else is an error.
        if (error instanceof ApiError && error.status === 404) {
          return null;
        }
        throw error;
      },
    ),
  ]);
  const header = record.header ?? [];
  const columns = profile?.columns ?? [];
  const path = `/migrations/${migrationId}/data/imports/${importId}`;
  const firstRow = rows.items[0]?.row_number;
  const lastRow = rows.items[rows.items.length - 1]?.row_number;
  return (
    <div className="max-w-6xl">
      <PageHeader
        breadcrumbs={[
          { label: "Data", href: `/migrations/${migrationId}/data` },
          { label: `Import #${record.sequence}` },
        ]}
        title={`Import #${record.sequence}: ${record.original_filename}`}
        status={<ProvenanceBadge kind="source" />}
        description="The file exactly as the legacy system exported it. Rows are stored once and never edited, so this is the evidence every canonical record and every finding traces back to."
      >
        <StatusChip status={record.status} />
      </PageHeader>

      <Panel className="mb-5 p-3">
        <MetaList
          columns={4}
          items={[
            {
              label: "Rows read",
              value: <span className="tabular-nums">{record.row_count ?? 0}</span>,
            },
            {
              label: "Quarantined",
              value:
                (record.quarantined_count ?? 0) > 0 ? (
                  <a
                    href="#quarantine"
                    className="font-semibold text-[var(--critical)] tabular-nums"
                  >
                    {record.quarantined_count}
                  </a>
                ) : (
                  <span className="tabular-nums">0</span>
                ),
            },
            { label: "Encoding", value: record.encoding ?? "—" },
            { label: "Uploaded", value: <Timestamp value={record.created_at} /> },
          ]}
        />
      </Panel>

      <Section
        title="Rows"
        description="Values are shown verbatim, including the whitespace and formatting the export contained."
      >
        <Panel>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Source rows">
            <table className="w-full border-collapse text-left text-xs" data-testid="source-rows">
              <caption className="sr-only">Raw rows as read</caption>
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] uppercase tracking-wide text-[var(--ink-muted)]">
                  <th scope="col" className="px-2 py-1.5 font-medium">
                    Row
                  </th>
                  <th scope="col" className="px-2 py-1.5 font-medium">
                    Lines
                  </th>
                  {header.map((column) => (
                    <th
                      key={column}
                      scope="col"
                      className="px-2 py-1.5 font-medium whitespace-nowrap"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.items.map((row) => (
                  <tr
                    key={row.row_number}
                    id={`row-${row.row_number}`}
                    className="scroll-mt-16 border-b border-[var(--border)]/60 last:border-0 target:bg-[var(--accent-soft)] target:shadow-[inset_4px_0_0_var(--accent)]"
                  >
                    <th
                      scope="row"
                      className="px-2 py-1.5 font-normal tabular-nums text-[var(--ink-muted)]"
                    >
                      {row.row_number}
                    </th>
                    <td className="px-2 py-1.5 tabular-nums whitespace-nowrap text-[var(--ink-muted)]">
                      {row.line_start === row.line_end
                        ? row.line_start
                        : `${row.line_start}–${row.line_end}`}
                    </td>
                    {header.map((column) => (
                      <td key={column} className="px-2 py-1.5 font-mono whitespace-pre">
                        {row.values[column] ?? ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2">
            <p className="text-xs text-[var(--ink-muted)]">
              {rows.items.length === 0 ? (
                "No rows on this page."
              ) : (
                <>
                  Showing{" "}
                  <span className="tabular-nums">
                    {firstRow}–{lastRow}
                  </span>{" "}
                  of <span className="tabular-nums">{record.row_count ?? 0}</span> rows
                </>
              )}
            </p>
            <div className="flex items-center gap-2">
              {safeCursor > 0 ? (
                <Link
                  href={buildPath(path, { cursor: Math.max(0, safeCursor - 50) })}
                  className={`${BUTTON_STYLES.secondary} no-underline`}
                >
                  Previous page
                </Link>
              ) : null}
              {rows.next_cursor ? (
                <Link
                  href={buildPath(path, { cursor: rows.next_cursor })}
                  className={`${BUTTON_STYLES.secondary} no-underline`}
                >
                  Next page
                </Link>
              ) : null}
            </div>
          </div>
        </Panel>
      </Section>

      <Section
        title="Quarantined rows"
        description="Lines the reader could not turn into a row. They are kept verbatim and excluded from every result, so anything here is missing from the migration."
      >
        <div id="quarantine" className="scroll-mt-16">
          {quarantine.length === 0 ? (
            <Callout tone="positive">Every row was read.</Callout>
          ) : (
            <Panel tone="critical" className="divide-y divide-[var(--critical)]/20">
              {quarantine.map((row) => (
                <div key={row.id} className="p-3">
                  <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                    <span className="font-medium tabular-nums text-[var(--critical)]">
                      Lines {row.line_start}–{row.line_end}
                    </span>
                    <span className="text-[var(--ink)]">{row.reason.replaceAll("_", " ")}</span>
                    <span className="text-xs text-[var(--ink-muted)]">
                      field counts {row.field_counts.join(", ")}
                    </span>
                  </p>
                  <pre className="mt-2 overflow-x-auto rounded border border-[var(--border)] bg-white p-2 text-xs whitespace-pre-wrap">
                    {row.raw_text}
                  </pre>
                </div>
              ))}
            </Panel>
          )}
        </div>
      </Section>

      <Section
        title="Profile"
        description="What the reader observed per column, used to suggest a column mapping and to flag ambiguous dates."
      >
        {columns.length === 0 ? (
          <EmptyState title="No profile" hint="Profiles are written once an import parses." />
        ) : (
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <caption className="sr-only">Column profile</caption>
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] uppercase tracking-wide text-[var(--ink-muted)]">
                  <th scope="col" className="px-3 py-1.5 font-medium">
                    Column
                  </th>
                  <th scope="col" className="px-3 py-1.5 text-right font-medium">
                    Blank
                  </th>
                  <th scope="col" className="px-3 py-1.5 text-right font-medium">
                    Distinct
                  </th>
                  <th scope="col" className="px-3 py-1.5 text-right font-medium">
                    Max length
                  </th>
                  <th scope="col" className="px-3 py-1.5 font-medium">
                    Patterns
                  </th>
                  <th scope="col" className="px-3 py-1.5 text-right font-medium">
                    Ambiguous dates
                  </th>
                </tr>
              </thead>
              <tbody>
                {columns.map((column) => (
                  <tr
                    key={column.name}
                    className="border-b border-[var(--border)]/60 last:border-0"
                  >
                    <th scope="row" className="px-3 py-1.5 font-mono font-normal">
                      {column.name}
                    </th>
                    <td className="px-3 py-1.5 text-right tabular-nums">{column.blank_count}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {column.distinct_count}
                      {column.distinct_count_capped ? "+" : ""}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{column.max_length}</td>
                    <td className="px-3 py-1.5 text-[var(--ink-muted)]">
                      {Object.entries(column.pattern_counts)
                        .map(([pattern, count]) => `${pattern.replaceAll("_", " ")} ${count}`)
                        .join(", ") || "—"}
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums ${
                        column.ambiguous_date_count > 0 ? "font-medium text-[var(--warning)]" : ""
                      }`}
                    >
                      {column.ambiguous_date_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>
    </div>
  );
}
