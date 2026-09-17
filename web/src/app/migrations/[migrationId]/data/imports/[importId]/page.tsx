import { Timestamp } from "@/components/dates";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ApiError, apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";
import Link from "next/link";

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
  return (
    <div className="max-w-6xl">
      <PageHeader
        title={`Import #${record.sequence}: ${record.original_filename}`}
        description={
          <>
            {record.row_count ?? 0} rows, {record.quarantined_count ?? 0} quarantined, encoding{" "}
            {record.encoding ?? "—"}, uploaded <Timestamp value={record.created_at} />
          </>
        }
      >
        <StatusChip status={record.status} />
      </PageHeader>

      <Section title="Rows">
        <div className="overflow-x-auto">
          <table className="border-collapse text-left text-xs" data-testid="source-rows">
            <caption className="sr-only">Raw rows as read</caption>
            <thead>
              <tr className="border-b border-gray-300 text-gray-700">
                <th scope="col" className="px-2 py-1">
                  Row
                </th>
                <th scope="col" className="px-2 py-1">
                  Lines
                </th>
                {header.map((column) => (
                  <th key={column} scope="col" className="px-2 py-1 whitespace-nowrap">
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
                  className="border-b border-gray-100 target:bg-yellow-100"
                >
                  <th scope="row" className="px-2 py-1 font-normal tabular-nums">
                    {row.row_number}
                  </th>
                  <td className="px-2 py-1 tabular-nums whitespace-nowrap">
                    {row.line_start === row.line_end
                      ? row.line_start
                      : `${row.line_start}–${row.line_end}`}
                  </td>
                  {header.map((column) => (
                    <td key={column} className="px-2 py-1 font-mono whitespace-pre">
                      {row.values[column] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 flex gap-4 text-sm">
          {safeCursor > 0 ? (
            <Link
              href={buildPath(`/migrations/${migrationId}/data/imports/${importId}`, {
                cursor: Math.max(0, safeCursor - 50),
              })}
              className="text-blue-800 underline"
            >
              Previous page
            </Link>
          ) : null}
          {rows.next_cursor ? (
            <Link
              href={buildPath(`/migrations/${migrationId}/data/imports/${importId}`, {
                cursor: rows.next_cursor,
              })}
              className="text-blue-800 underline"
            >
              Next page
            </Link>
          ) : null}
        </p>
      </Section>

      <Section title="Quarantined rows">
        <div id="quarantine">
          {quarantine.length === 0 ? (
            <p className="text-sm text-gray-700">Every row was read.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {quarantine.map((row) => (
                <li key={row.id} className="rounded border border-red-200 p-2">
                  <p>
                    Lines {row.line_start}–{row.line_end}: {row.reason.replaceAll("_", " ")} (field
                    counts {row.field_counts.join(", ")})
                  </p>
                  <pre className="mt-1 overflow-x-auto bg-gray-50 p-1 text-xs whitespace-pre-wrap">
                    {row.raw_text}
                  </pre>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      <Section title="Profile">
        {columns.length === 0 ? (
          <p className="text-sm text-gray-700">No profile.</p>
        ) : (
          <table className="w-full border-collapse text-left text-xs">
            <caption className="sr-only">Column profile</caption>
            <thead>
              <tr className="border-b border-gray-300 text-gray-700">
                <th scope="col" className="px-2 py-1">
                  Column
                </th>
                <th scope="col" className="px-2 py-1 text-right">
                  Blank
                </th>
                <th scope="col" className="px-2 py-1 text-right">
                  Distinct
                </th>
                <th scope="col" className="px-2 py-1 text-right">
                  Max length
                </th>
                <th scope="col" className="px-2 py-1">
                  Patterns
                </th>
                <th scope="col" className="px-2 py-1 text-right">
                  Ambiguous dates
                </th>
              </tr>
            </thead>
            <tbody>
              {columns.map((column) => (
                <tr key={column.name} className="border-b border-gray-100">
                  <th scope="row" className="px-2 py-1 font-normal">
                    {column.name}
                  </th>
                  <td className="px-2 py-1 text-right tabular-nums">{column.blank_count}</td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {column.distinct_count}
                    {column.distinct_count_capped ? "+" : ""}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{column.max_length}</td>
                  <td className="px-2 py-1">
                    {Object.entries(column.pattern_counts)
                      .map(([pattern, count]) => `${pattern.replaceAll("_", " ")} ${count}`)
                      .join(", ") || "—"}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {column.ambiguous_date_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}
