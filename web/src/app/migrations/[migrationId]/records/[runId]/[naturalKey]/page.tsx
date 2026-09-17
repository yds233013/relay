import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { SourceLocation } from "@/components/source-location";
import { apiGet, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

import { proposeFieldOverride } from "../../../governance-actions";

/** Canonical fields the engine can override, by natural key prefix. */
const OVERRIDABLE: Record<string, readonly string[]> = { je: ["entry_date", "posting_period"] };

export const dynamic = "force-dynamic";

export default async function RecordInspector(
  props: PageProps<"/migrations/[migrationId]/records/[runId]/[naturalKey]">,
) {
  const { migrationId, runId, naturalKey } = await props.params;
  const query = await props.searchParams;
  const key = decodeURIComponent(naturalKey);
  const record = await apiGet<Schemas["RecordOut"]>(
    `/api/v1/pipeline-runs/${runId}/records/${encodeURIComponent(key)}`,
  );
  const lineage = record.record.lineage as Schemas["LineageOut"] | null | undefined;
  return (
    <div className="max-w-5xl">
      <PageHeader title="Record inspector" description={<span className="font-mono">{key}</span>} />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Source row">
        {record.source_row ? (
          <>
            <p className="mb-2 text-sm" data-testid="source-location">
              <SourceLocation migrationId={migrationId} lineage={lineage} />
            </p>
            <table className="w-full border-collapse text-left text-sm" data-testid="source-row">
              <caption className="sr-only">Raw source values</caption>
              <tbody>
                {(record.source_header ?? Object.keys(record.source_row.values))
                  .map((column) => [column, record.source_row?.values[column] ?? ""] as const)
                  .map(([column, value]) => (
                    <tr key={column} className="border-b border-gray-100">
                      <th scope="row" className="w-48 px-2 py-1 font-normal text-gray-700">
                        {column}
                      </th>
                      <td className="px-2 py-1 font-mono text-xs whitespace-pre-wrap">{value}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="text-sm text-gray-700">This record has no single source row.</p>
        )}
      </Section>
      <Section title="Canonical record">
        <pre className="overflow-x-auto rounded bg-gray-50 p-2 text-xs">
          {JSON.stringify(record.data, null, 2)}
        </pre>
      </Section>
      {(OVERRIDABLE[key.split(":", 1)[0] ?? ""] ?? []).length > 0 ? (
        <Section title="Propose a correction">
          <p className="mb-2 text-sm text-gray-700">
            The source row never changes. An approved override applies the new value on top of it,
            and every run checks that the current value is still the one shown here.
          </p>
          <form action={proposeFieldOverride} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="runId" value={runId} />
            <input type="hidden" name="naturalKey" value={key} />
            <input
              type="hidden"
              name="returnTo"
              value={`/migrations/${migrationId}/records/${runId}/${encodeURIComponent(key)}`}
            />
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">Field</span>
              <select name="field" className="rounded border border-gray-400 bg-white px-2 py-1">
                {(OVERRIDABLE[key.split(":", 1)[0] ?? ""] ?? []).map((field) => (
                  <option key={field} value={field}>
                    {field.replaceAll("_", " ")} (currently {String(record.data[field] ?? "—")})
                  </option>
                ))}
              </select>
            </label>
            <TextField
              name="newValue"
              label="New value"
              required
              placeholder="YYYY-MM-DD or YYYY-MM"
            />
            <TextArea name="justification" label="Justification and evidence" required />
            <span>
              <SubmitButton>Propose correction</SubmitButton>
            </span>
          </form>
        </Section>
      ) : null}
      <Section title="Related issues">
        {record.related_issue_ids.length === 0 ? (
          <p className="text-sm text-gray-700">No issue names this record as a subject.</p>
        ) : (
          <ul className="list-inside list-disc text-sm">
            {record.related_issue_ids.map((id) => (
              <li key={id}>
                <Link href={`/migrations/${migrationId}/issues/${id}`} className="underline">
                  {id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
