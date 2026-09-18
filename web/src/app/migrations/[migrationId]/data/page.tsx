import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { EmptyState, MetricCard, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DataPage(props: PageProps<"/migrations/[migrationId]/data">) {
  const { migrationId } = await props.params;
  const datasets = await apiGet<Schemas["DatasetOut"][]>(
    `/api/v1/migrations/${migrationId}/datasets`,
  );
  const imports = await Promise.all(
    datasets.map((dataset) =>
      apiGet<Schemas["ImportOut"][]>(`/api/v1/datasets/${dataset.id}/imports`),
    ),
  );
  const actives = datasets.map((dataset, index) =>
    (imports[index] ?? []).find((i) => i.id === dataset.active_import_id),
  );
  const withoutImport = actives.filter((active) => active === undefined).length;
  const quarantined = actives.reduce(
    (total, active) => total + (active?.quarantined_count ?? 0),
    0,
  );

  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Data"
        description="Every dataset, the import a run currently reads from it, and the rows that could not be read. Imported rows are kept exactly as exported and are never edited."
      />

      {datasets.length === 0 ? (
        <EmptyState
          title="No datasets yet"
          hint="Declare the source systems and their datasets on the Setup page, then upload each export."
        />
      ) : (
        <>
          <dl className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <MetricCard
              label="Datasets"
              value={datasets.length}
              hint="One per exported file the migration depends on"
            />
            <MetricCard
              label="Without an active import"
              value={withoutImport}
              hint="A run cannot read these yet"
              tone={withoutImport > 0 ? "warning" : "neutral"}
            />
            <MetricCard
              label="Quarantined rows"
              value={quarantined}
              hint="Rows the reader could not parse, across active imports"
              tone={quarantined > 0 ? "critical" : "neutral"}
            />
          </dl>

          <Section
            title="Datasets"
            description="Quarantined rows never reach the canonical model, so anything counted here is missing from the results below."
          >
            <Panel className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">Datasets</caption>
                <thead>
                  <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Dataset
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Type
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      As of
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Active import
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Rows
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Quarantined
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Imports
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((dataset, index) => {
                    const history = imports[index] ?? [];
                    const active = actives[index];
                    const quarantinedCount = active?.quarantined_count ?? 0;
                    return (
                      <tr
                        key={dataset.id}
                        className="border-b border-[var(--border)]/60 last:border-0 hover:bg-[var(--surface-sunken)]"
                      >
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          <Link
                            href={`/migrations/${migrationId}/data/datasets/${dataset.id}`}
                            className="font-medium"
                          >
                            {dataset.name}
                          </Link>
                        </th>
                        <td className="px-3 py-2 text-[var(--ink-muted)]">
                          {humanize(dataset.dataset_type)}
                        </td>
                        <td className="px-3 py-2 text-[var(--ink-muted)]">
                          <BusinessDate value={dataset.as_of_date} />
                        </td>
                        <td className="px-3 py-2">
                          {active ? (
                            <span className="flex flex-wrap items-center gap-2">
                              <Link
                                href={`/migrations/${migrationId}/data/imports/${active.id}`}
                                className="whitespace-nowrap"
                              >
                                <span className="tabular-nums">#{active.sequence}</span>{" "}
                                {active.original_filename}
                              </Link>
                              <StatusChip status={active.status} />
                            </span>
                          ) : (
                            <span className="font-medium text-[var(--warning)]">no import yet</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {active?.row_count ?? <span className="text-[var(--ink-subtle)]">—</span>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {active && quarantinedCount > 0 ? (
                            <Link
                              href={`/migrations/${migrationId}/data/imports/${active.id}#quarantine`}
                              className="font-semibold text-[var(--critical)]"
                              title="Rows that could not be read. Open the import to see them."
                            >
                              {quarantinedCount}
                            </Link>
                          ) : (
                            <span className="text-[var(--ink-subtle)]">
                              {active?.quarantined_count ?? "—"}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--ink-muted)]">
                          {history.length}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
          </Section>
        </>
      )}
    </div>
  );
}
