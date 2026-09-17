import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { SubmitButton } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
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
            ·{" "}
            <Link href={`/migrations/${migrationId}/data`} className="underline">
              all datasets
            </Link>
          </>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Upload a new export">
        <p className="mb-2 text-sm text-gray-700">
          A new file becomes a new import. When it has been read, it replaces the active import and
          the previous one is kept as superseded. Uploading a file that was already imported changes
          nothing.
        </p>
        <form action={uploadImport} className="flex flex-wrap items-end gap-3">
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="datasetId" value={datasetId} />
          <input type="hidden" name="returnTo" value={page} />
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-gray-700">CSV file</span>
            <input type="file" name="file" accept=".csv,text/csv" required className="text-sm" />
          </label>
          <SubmitButton>Upload</SubmitButton>
        </form>
      </Section>
      <Section title="Column mapping">
        <p className="text-sm">
          {approved ? `Approved version ${approved.version}.` : "No approved column mapping yet."}{" "}
          <Link
            href={`/migrations/${migrationId}/mappings/columns/${datasetId}`}
            className="underline"
          >
            Review or change the column mapping
          </Link>
        </p>
      </Section>
      <Section title="Imports">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm" data-testid="imports">
            <caption className="sr-only">Imports of this dataset</caption>
            <thead>
              <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
                <th scope="col" className="px-2 py-1.5">
                  Import
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Status
                </th>
                <th scope="col" className="px-2 py-1.5 text-right">
                  Rows
                </th>
                <th scope="col" className="px-2 py-1.5 text-right">
                  Quarantined
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Uploaded
                </th>
              </tr>
            </thead>
            <tbody>
              {imports.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-gray-100"
                  data-sequence={item.sequence}
                >
                  <td className="px-2 py-1.5">
                    <Link
                      href={`/migrations/${migrationId}/data/imports/${item.id}`}
                      className="underline"
                    >
                      #{item.sequence} {item.original_filename}
                    </Link>
                    {item.id === dataset.active_import_id ? (
                      <span className="ml-2 text-xs font-medium">active</span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5">
                    <StatusChip status={item.status} />
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{item.row_count ?? "—"}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {item.quarantined_count ?? "—"}
                  </td>
                  <td className="px-2 py-1.5">
                    <LocalTime value={item.created_at} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Pipeline">
        <form action={requestRun}>
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="returnTo" value={page} />
          <SubmitButton tone="secondary">Run the pipeline on the current inputs</SubmitButton>
        </form>
      </Section>
    </div>
  );
}
