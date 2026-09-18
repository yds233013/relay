import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { PurposeBadge, reconciliationGloss } from "@/components/reconciliation-glossary";
import { RunContext } from "@/components/run-context";
import { StatusChip } from "@/components/status-chip";
import { Callout, Panel } from "@/components/ui";
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
        description="Each control report against the detail Relay staged. Differences are left minus right."
        status={
          <RunContext
            base={base}
            runId={String(runId)}
            sequence={readiness.run_sequence}
            isCurrent={readiness.run_is_current}
          />
        }
      />
      <Panel className="mb-5 overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Reconciliation results</caption>
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
              <th scope="col" className="px-3 py-2 font-medium">
                Control
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Left side
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Right side
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Status
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Lines differing
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr
                key={result.id}
                className={`border-b border-[var(--border)]/60 last:border-0 ${
                  result.id === selected
                    ? "bg-[var(--accent-soft)] shadow-[inset_3px_0_0_var(--accent)]"
                    : ""
                }`}
              >
                <td className="px-3 py-2">
                  <Link
                    href={buildPath(`${base}/reconciliation`, { run: runId, result: result.id })}
                    className="font-semibold"
                    aria-current={result.id === selected ? "true" : undefined}
                  >
                    {result.recon_id}
                  </Link>{" "}
                  <span className="text-[var(--ink)]">{result.title}</span>
                </td>
                <td className="px-3 py-2 text-[var(--ink-muted)]">{result.left_label}</td>
                <td className="px-3 py-2 text-[var(--ink-muted)]">{result.right_label}</td>
                <td className="px-3 py-2">
                  <StatusChip status={result.status} />
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {result.discrepancy_count === 0 ? (
                    <span className="text-[var(--ink-subtle)]">0 of {result.line_count}</span>
                  ) : (
                    <>
                      <span className="font-medium text-[var(--critical)]">
                        {result.discrepancy_count}
                      </span>
                      <span className="text-[var(--ink-subtle)]"> of {result.line_count}</span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      {selectedResult ? (
        <Panel className="mb-4 p-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="text-base font-semibold text-[var(--ink)]">
              {selectedResult.recon_id} {selectedResult.title}
            </h2>
            <PurposeBadge purpose={selectedResult.purpose} />
            <StatusChip status={selectedResult.status} />
          </div>
          <p className="mt-1 max-w-4xl text-sm text-[var(--ink-muted)]">
            {reconciliationGloss(selectedResult.recon_id)}
          </p>
          <p className="mt-1 text-xs text-[var(--ink-subtle)]">
            Left: {selectedResult.left_label} · Right: {selectedResult.right_label} · tolerance{" "}
            <span className="tabular-nums">{selectedResult.tolerance}</span> ·{" "}
            {selectedResult.line_count - selectedResult.discrepancy_count} of{" "}
            {selectedResult.line_count} lines agree
          </p>
          {selectedResult.status === "tied_with_explained_items" ? (
            <div className="mt-2">
              <Callout tone="warning" title="Explained is not the same as accepted">
                Every part of this difference is identified and attributed to a named record, so the
                control ties. Items that indicate an error still raise their own findings, and the
                cash gate keeps failing until someone resolves or dispositions each one.
              </Callout>
            </div>
          ) : null}
        </Panel>
      ) : null}
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
                    className="font-mono text-xs underline"
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
                header: "Identified",
                align: "right",
                cell: (line) => (
                  <Money
                    value={line.explained_amount}
                    currency={line.currency}
                    showCurrency={false}
                  />
                ),
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
