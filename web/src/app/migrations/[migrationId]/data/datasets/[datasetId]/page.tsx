import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { BusinessDate } from "@/components/dates";
import { SubmitButton } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Callout, EmptyState, Panel } from "@/components/ui";
import { isPublicDemo } from "@/lib/demo";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { requestRun, uploadImport } from "../../../workflow-actions";

export const dynamic = "force-dynamic";

export default async function DatasetPage(
  props: PageProps<"/migrations/[migrationId]/data/datasets/[datasetId]">,
) {
  const { migrationId, datasetId } = await props.params;
  const query = await props.searchParams;
  const [datasets, imports, sets] = await Promise.all([
    apiGet<Schemas["DatasetOut"][]>(`/api/v1/migrations/${migrationId}/datasets`),
    apiGet<Schemas["ImportOut"][]>(`/api/v1/datasets/${datasetId}/imports`),
    apiGet<Schemas["ColumnMappingSetOut"][]>(`/api/v1/datasets/${datasetId}/column-mapping-sets`),
  ]);
  const dataset = datasets.find((d) => d.id === datasetId);
  if (!dataset) {
    return <p className="text-sm">Dataset not found.</p>;
  }
  const approved = sets.find((s) => s.status === "approved");
  const page = `/migrations/${migrationId}/data/datasets/${datasetId}`;
  return (
    <div className="max-w-5xl">
      <PageHeader
        breadcrumbs={[
          { label: "Data", href: `/migrations/${migrationId}/data` },
          { label: dataset.name },
        ]}
        title={dataset.name}
        description={
          <>
            {humanize(dataset.dataset_type)}
            {dataset.as_of_date ? (
              <>
                {" "}
                as of <BusinessDate value={dataset.as_of_date} />
              </>
            ) : null}{" "}
            · <Link href={`/migrations/${migrationId}/data`}>all datasets</Link>
          </>
        }
        status={
          approved ? (
            <StatusChip status="approved" label={`mapping v${approved.version}`} />
          ) : (
            <StatusChip status="stale" label="no approved mapping" />
          )
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      <Section
        title="Upload a new export"
        description="A new file becomes a new import. When it has been read, it replaces the active import and the previous one is kept as superseded. Uploading a file that was already imported changes nothing."
      >
        <Panel className="p-3">
          {isPublicDemo() ? (
            <DemoUnavailable what="Uploading a corrected export replaces the active import, keeps the previous one as evidence, and re-runs every check." />
          ) : (
            <form action={uploadImport} className="flex flex-wrap items-end gap-3">
              <input type="hidden" name="migrationId" value={migrationId} />
              <input type="hidden" name="datasetId" value={datasetId} />
              <input type="hidden" name="returnTo" value={page} />
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs font-medium text-[var(--ink-muted)]">CSV file</span>
                <input
                  type="file"
                  name="file"
                  accept=".csv,text/csv"
                  required
                  className="text-sm"
                />
              </label>
              <SubmitButton>Upload</SubmitButton>
            </form>
          )}
        </Panel>
      </Section>

      <Section
        title="Column mapping"
        description="Which source column feeds which canonical field. Only an approved mapping is used by a run."
      >
        <Panel className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
          <span className={approved ? "text-[var(--ink)]" : "font-medium text-[var(--warning)]"}>
            {approved ? `Approved version ${approved.version}.` : "No approved column mapping yet."}
          </span>
          <Link href={`/migrations/${migrationId}/mappings/columns/${datasetId}`}>
            Review or change the column mapping
          </Link>
        </Panel>
      </Section>

      <Section
        title="Imports"
        description="Every upload is kept. The active import is the one runs read; earlier ones stay as evidence."
      >
        {imports.length === 0 ? (
          <EmptyState
            title="No imports yet"
            hint="Upload this dataset's export above to create the first import."
          />
        ) : (
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm" data-testid="imports">
              <caption className="sr-only">Imports of this dataset</caption>
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Import
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Rows
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Quarantined
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Uploaded
                  </th>
                </tr>
              </thead>
              <tbody>
                {imports.map((item) => {
                  const active = item.id === dataset.active_import_id;
                  return (
                    <tr
                      key={item.id}
                      className={`border-b border-[var(--border)]/60 last:border-0 ${
                        active ? "bg-[var(--accent-soft)] shadow-[inset_3px_0_0_var(--accent)]" : ""
                      }`}
                      data-sequence={item.sequence}
                    >
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <Link
                          href={`/migrations/${migrationId}/data/imports/${item.id}`}
                          className="whitespace-nowrap font-medium"
                        >
                          <span className="tabular-nums">#{item.sequence}</span>{" "}
                          {item.original_filename}
                        </Link>
                        {active ? (
                          <span className="ml-2 rounded border border-[var(--accent)]/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--accent-ink)]">
                            active
                          </span>
                        ) : null}
                      </th>
                      <td className="px-3 py-2">
                        <StatusChip status={item.status} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{item.row_count ?? "—"}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {(item.quarantined_count ?? 0) > 0 ? (
                          <span className="font-semibold text-[var(--critical)]">
                            {item.quarantined_count}
                          </span>
                        ) : (
                          <span className="text-[var(--ink-subtle)]">
                            {item.quarantined_count ?? "—"}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-[var(--ink-muted)]">
                        <LocalTime value={item.created_at} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        )}
      </Section>

      <Section
        title="Pipeline"
        description="Re-run the whole migration with this dataset's active import and approved mapping."
      >
        <Panel className="p-3">
          <Callout>
            A run recomputes results from the current inputs of every dataset, not only this one.
          </Callout>
          {isPublicDemo() ? (
            <DemoUnavailable what="A run recomputes every result from the current inputs of every dataset, not just this one." />
          ) : (
            <form action={requestRun} className="mt-3">
              <input type="hidden" name="migrationId" value={migrationId} />
              <input type="hidden" name="returnTo" value={page} />
              <SubmitButton tone="secondary">Run the pipeline on the current inputs</SubmitButton>
            </form>
          )}
        </Panel>
      </Section>
    </div>
  );
}
