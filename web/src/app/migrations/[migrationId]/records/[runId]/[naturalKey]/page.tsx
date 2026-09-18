import Link from "next/link";

import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { Callout, EmptyState, PageHeader, Panel, ProvenanceBadge, Section } from "@/components/ui";
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
  const base = `/migrations/${migrationId}`;
  const key = decodeURIComponent(naturalKey);
  const record = await apiGet<Schemas["RecordOut"]>(
    `/api/v1/pipeline-runs/${runId}/records/${encodeURIComponent(key)}`,
  );
  const lineage = record.record.lineage as Schemas["LineageOut"] | null | undefined;
  const overridable = OVERRIDABLE[key.split(":", 1)[0] ?? ""] ?? [];
  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Record inspector"
        breadcrumbs={[{ label: "Overview", href: base }, { label: "Record" }]}
        description={
          <>
            One record, as the legacy system wrote it and as Relay understands it.{" "}
            <span className="font-mono text-xs text-[var(--ink)]">{key}</span>
          </>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      <Section
        title="Source row"
        description="Exactly what the export contained. Relay never edits it; corrections are overlays."
        actions={<ProvenanceBadge kind="source" />}
      >
        {record.source_row ? (
          <Panel className="overflow-hidden">
            <p
              className="border-b border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-1.5 text-sm"
              data-testid="source-location"
            >
              <SourceLocation migrationId={migrationId} lineage={lineage} />
            </p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm" data-testid="source-row">
                <caption className="sr-only">Raw source values</caption>
                <tbody>
                  {(record.source_header ?? Object.keys(record.source_row.values))
                    .map((column) => [column, record.source_row?.values[column] ?? ""] as const)
                    .map(([column, value]) => (
                      <tr key={column} className="border-b border-[var(--border)]/60 last:border-0">
                        <th
                          scope="row"
                          className="w-56 px-3 py-1 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]"
                        >
                          {column}
                        </th>
                        <td className="whitespace-pre-wrap px-3 py-1 font-mono text-xs text-[var(--ink)]">
                          {value}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Panel>
        ) : (
          <EmptyState
            title="This record has no single source row."
            hint="Derived records — such as an aggregate — carry lineage to every row behind them instead."
          />
        )}
      </Section>

      <Section
        title="Canonical record"
        description="Relay's normalized form, produced from the row above by the approved column mapping."
        actions={<ProvenanceBadge kind="canonical" />}
      >
        <Panel className="overflow-hidden">
          <pre className="overflow-x-auto px-3 py-2 text-xs text-[var(--ink)]">
            {JSON.stringify(record.data, null, 2)}
          </pre>
        </Panel>
      </Section>

      {overridable.length > 0 ? (
        <Section title="Propose a correction">
          <Panel className="p-3">
            <Callout tone="warning">
              The source row never changes. An approved override applies the new value on top of it,
              and every run checks that the value it replaces is still the one shown here.
            </Callout>
            <form action={proposeFieldOverride} className="mt-3 flex max-w-2xl flex-col gap-2">
              <input type="hidden" name="migrationId" value={migrationId} />
              <input type="hidden" name="runId" value={runId} />
              <input type="hidden" name="naturalKey" value={key} />
              <input
                type="hidden"
                name="returnTo"
                value={`/migrations/${migrationId}/records/${runId}/${encodeURIComponent(key)}`}
              />
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs font-medium text-[var(--ink-muted)]">Field</span>
                <select
                  name="field"
                  className="rounded border border-[var(--border-strong)] bg-white px-2 py-1"
                >
                  {overridable.map((field) => (
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
          </Panel>
        </Section>
      ) : null}

      <Section
        title="Related issues"
        description="Findings the deterministic engine raised against this record."
        actions={<ProvenanceBadge kind="derived" />}
      >
        {record.related_issues.length === 0 ? (
          <EmptyState title="No issue names this record as a subject." />
        ) : (
          <Panel className="divide-y divide-[var(--border)]">
            {record.related_issues.map((issue) => (
              <p key={issue.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <Link href={`${base}/issues/${issue.id}`} className="font-medium">
                  {issue.key}
                </Link>
                <StatusChip status={issue.severity} />
                <StatusChip status={issue.status} />
                <span className="text-[var(--ink-muted)]">{issue.title}</span>
              </p>
            ))}
          </Panel>
        )}
      </Section>
    </div>
  );
}
