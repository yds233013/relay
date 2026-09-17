import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ApiError, apiGet, apiSend, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeColumnMapping } from "../../../governance-actions";

export const dynamic = "force-dynamic";

const MAX_CONFIG_LENGTH = 20_000;

function configFrom(set: Schemas["ColumnMappingSetOut"] | undefined, fallback: unknown): string {
  const config = set
    ? {
        fields: Object.fromEntries(set.mappings.map((m) => [m.target_field, m.specification])),
        exclude_rows_where_blank: set.exclude_rows_where_blank,
      }
    : fallback;
  return JSON.stringify(config, null, 2);
}

export default async function ColumnMappingPage(
  props: PageProps<"/migrations/[migrationId]/mappings/columns/[datasetId]">,
) {
  const { migrationId, datasetId } = await props.params;
  const query = await props.searchParams;
  const [sets, suggestion] = await Promise.all([
    apiGet<Schemas["ColumnMappingSetOut"][]>(`/api/v1/datasets/${datasetId}/column-mapping-sets`),
    apiGet<Schemas["ColumnMappingSuggestionOut"]>(
      `/api/v1/datasets/${datasetId}/column-mapping-suggestion`,
    ),
  ]);
  const approved = sets.find((s) => s.status === "approved");
  const suggested = {
    fields: Object.fromEntries(
      suggestion.fields.filter((f) => f.specification).map((f) => [f.field, f.specification]),
    ),
    exclude_rows_where_blank: [],
  };
  const submitted = param(query.config);
  const editing =
    submitted && submitted.length <= MAX_CONFIG_LENGTH
      ? submitted
      : param(query.start) === "suggestion"
        ? JSON.stringify(suggested, null, 2)
        : configFrom(approved, suggested);
  let preview: Schemas["ColumnMappingPreviewOut"] | null = null;
  let previewError: string | undefined;
  if (submitted) {
    try {
      preview = await apiSend<Schemas["ColumnMappingPreviewOut"]>(
        "POST",
        `/api/v1/datasets/${datasetId}/column-mapping-preview`,
        JSON.parse(submitted),
      );
    } catch (error) {
      if (error instanceof ApiError) {
        previewError = error.message;
      } else if (error instanceof SyntaxError) {
        previewError = "The mapping is not valid JSON.";
      } else {
        throw error;
      }
    }
  }
  const previewFields = preview ? Object.keys(preview.rows[0]?.values ?? {}) : [];
  return (
    <div className="max-w-7xl">
      <PageHeader
        title={`Column mapping: ${humanize(suggestion.dataset_type)}`}
        description={
          <>
            <Link href={`/migrations/${migrationId}/mappings`} className="underline">
              Mappings
            </Link>{" "}
            · approved version {approved ? approved.version : "none"}
          </>
        }
      />
      <Notice error={param(query.error) ?? previewError} notice={param(query.notice)} />
      <Section title="Canonical fields and suggestions">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Canonical fields</caption>
            <thead>
              <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
                <th scope="col" className="px-2 py-1.5">
                  Field
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Required
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Approved source
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Suggested source
                </th>
                <th scope="col" className="px-2 py-1.5">
                  Notes
                </th>
              </tr>
            </thead>
            <tbody>
              {suggestion.fields.map((field) => {
                const current = approved?.mappings.find((m) => m.target_field === field.field);
                const source = (spec: Record<string, unknown> | null | undefined) =>
                  spec
                    ? typeof spec.source === "string"
                      ? spec.source
                      : spec.debit_credit
                        ? "debit and credit columns"
                        : "constant"
                    : "—";
                return (
                  <tr key={field.field} className="border-b border-gray-100 align-top">
                    <td className="px-2 py-1.5 font-mono text-xs">{field.field}</td>
                    <td className="px-2 py-1.5">{field.required ? "required" : "optional"}</td>
                    <td className="px-2 py-1.5">{source(current?.specification)}</td>
                    <td className="px-2 py-1.5">
                      {source(field.specification)}
                      {field.basis ? (
                        <span className="ml-1 text-xs text-gray-700">({field.basis})</span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-xs">{field.notes.join("; ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-gray-700">
          Unmatched columns: {suggestion.unmatched_columns.join(", ") || "none"}.{" "}
          <Link href="?start=suggestion" className="underline">
            Start from the suggestion
          </Link>
        </p>
      </Section>
      <Section title="Edit and preview">
        <form method="get" className="flex flex-col gap-2">
          <TextArea name="config" label="Mapping (JSON)" defaultValue={editing} rows={16} mono />
          <span>
            <SubmitButton tone="secondary">Preview first 50 rows</SubmitButton>
          </span>
        </form>
        {preview ? (
          <div className="mt-3">
            <p className="mb-2 text-sm">
              Missing required fields: {preview.missing_required_fields.join(", ") || "none"}.
              Unknown fields: {preview.unknown_fields.join(", ") || "none"}.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-xs" data-testid="preview">
                <caption className="sr-only">Preview</caption>
                <thead>
                  <tr className="border-b border-gray-300 uppercase tracking-wide text-gray-700">
                    <th scope="col" className="px-2 py-1">
                      Row
                    </th>
                    {previewFields.map((f) => (
                      <th key={f} scope="col" className="px-2 py-1">
                        {f}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row) => (
                    <tr key={row.row_number} className="border-b border-gray-100 align-top">
                      <td className="px-2 py-1">
                        {row.row_number}
                        {row.excluded ? <StatusChip status="excluded" /> : null}
                      </td>
                      {previewFields.map((f) => (
                        <td key={f} className="px-2 py-1 font-mono">
                          {row.errors[f] ? (
                            <span className="text-red-900">✕ {row.errors[f]}</span>
                          ) : (
                            (row.values[f] ?? "—")
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </Section>
      {preview ? (
        <Section title="Propose">
          <form action={proposeColumnMapping} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="datasetId" value={datasetId} />
            <input type="hidden" name="config" value={editing} />
            <TextField name="title" label="Title" required defaultValue="Column mapping change" />
            <TextArea name="justification" label="Justification" required />
            <p className="text-xs text-gray-700">
              Proposes the mapping previewed above. Edit and preview again to change it.
            </p>
            <span>
              <SubmitButton>Propose the previewed mapping</SubmitButton>
            </span>
          </form>
        </Section>
      ) : (
        <p className="mb-6 text-sm text-gray-700">Preview a mapping to propose it.</p>
      )}
      <Section title="Versions">
        <ul className="space-y-1 text-sm">
          {sets.map((s) => (
            <li key={s.id} className="flex items-center gap-2">
              Version {s.version} <StatusChip status={s.status} />
              {s.change_request_id ? (
                <Link
                  href={`/migrations/${migrationId}/change-requests/${s.change_request_id}`}
                  className="underline"
                >
                  change request
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
