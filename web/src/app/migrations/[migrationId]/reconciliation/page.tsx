import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ReconciliationPage(
  props: PageProps<"/migrations/[migrationId]/reconciliation">,
) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const base = `/migrations/${migrationId}`;
  const readiness = await apiGet<Schemas["ReadinessOut"]>(
    `/api/v1/migrations/${migrationId}/readiness`,
  );
  const runId = param(search.run) ?? readiness.run_id;
  if (!runId) {
    return <PageHeader title="Reconciliation" description="No successful run yet." />;
  }
  const results = await apiGet<Schemas["ReconciliationResultOut"][]>(
    `/api/v1/pipeline-runs/${runId}/reconciliations`,
  );
  const selected = param(search.result) ?? results.find((r) => r.status === "discrepancy")?.id;
  const selectedResult = results.find((r) => r.id === selected);
  // Show discrepancies first when there are any; otherwise every line of the reconciliation.
  const status =
    param(search.status) ?? (selectedResult?.status === "discrepancy" ? "discrepancy" : undefined);
  const cursor = param(search.cursor);
  const lines = selected
    ? await apiGet<Schemas["Page_ReconciliationLineOut_"]>(
        `/api/v1/reconciliation-results/${selected}/lines`,
        {
          status,
          cursor,
          limit: 100,
        },
      )
    : null;

  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Reconciliation"
        description="Control reports against staged detail. Differences are left minus right."
      />
      <table className="mb-6 w-full border-collapse text-left text-sm">
        <caption className="sr-only">Reconciliation results</caption>
        <thead>
          <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
            <th scope="col" className="px-2 py-1.5">
              Reconciliation
            </th>
            <th scope="col" className="px-2 py-1.5">
              Left
            </th>
            <th scope="col" className="px-2 py-1.5">
              Right
            </th>
            <th scope="col" className="px-2 py-1.5">
              Status
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Discrepancies
            </th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <tr
              key={result.id}
              className={`border-b border-gray-100 ${result.id === selected ? "bg-blue-50" : ""}`}
            >
              <td className="px-2 py-1.5">
                <Link
                  href={buildPath(`${base}/reconciliation`, { run: runId, result: result.id })}
                  className="font-medium text-blue-800 underline"
                  aria-current={result.id === selected ? "true" : undefined}
                >
                  {result.recon_id}
                </Link>{" "}
                {result.title}
              </td>
              <td className="px-2 py-1.5 text-gray-700">{result.left_label}</td>
              <td className="px-2 py-1.5 text-gray-700">{result.right_label}</td>
              <td className="px-2 py-1.5">
                <StatusChip status={result.status} />
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {result.discrepancy_count} of {result.line_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {lines && selected ? (
        <>
          <FilterForm>
            <input type="hidden" name="run" value={runId} />
            <input type="hidden" name="result" value={selected} />
            <SelectFilter
              name="status"
              label="Line status"
              value={status}
              options={[
                ["discrepancy", "Discrepancy"],
                ["explained", "Explained"],
                ["tied", "Tied"],
              ]}
            />
          </FilterForm>
          <DataTable<Schemas["ReconciliationLineOut"]>
            caption={`Lines of ${results.find((r) => r.id === selected)?.recon_id ?? ""}`}
            rows={lines.items}
            rowKey={(line) => line.id}
            nextHref={
              lines.next_cursor
                ? buildPath(`${base}/reconciliation`, {
                    run: runId,
                    result: selected,
                    status,
                    cursor: lines.next_cursor,
                  })
                : null
            }
            columns={[
              {
                header: "Grain",
                cell: (line) => (
                  <Link
                    href={`${base}/reconciliation/lines/${line.id}`}
                    className="font-mono text-xs text-blue-800 underline"
                  >
                    {Object.entries(line.grain)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", ")}
                  </Link>
                ),
              },
              {
                header: "Left",
                align: "right",
                cell: (line) => (
                  <Money value={line.left_amount} currency={line.currency} showCurrency={false} />
                ),
              },
              {
                header: "Right",
                align: "right",
                cell: (line) => (
                  <Money value={line.right_amount} currency={line.currency} showCurrency={false} />
                ),
              },
              {
                header: "Difference",
                align: "right",
                cell: (line) => <Money value={line.difference} currency={line.currency} />,
              },
              {
                header: "Unexplained",
                align: "right",
                cell: (line) => <Money value={line.unexplained_amount} currency={line.currency} />,
              },
              { header: "Status", cell: (line) => <StatusChip status={line.status} /> },
            ]}
          />
        </>
      ) : null}
    </div>
  );
}
