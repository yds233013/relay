import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, EmptyState, Panel } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { createDataset, createSourceSystem, requestRun } from "../workflow-actions";

export const dynamic = "force-dynamic";

const SYSTEM_KINDS = ["legacy_erp", "spreadsheet", "bank", "billing", "crm", "other"] as const;
const DATASET_TYPES = [
  "legacy_coa", "target_coa", "account_mapping", "trial_balance", "gl_detail", "customers",
  "vendors", "invoices", "bills", "payments", "ar_aging", "ap_aging", "bank_transactions",
  "fx_rates",
] as const; // prettier-ignore

const CONTROL =
  "rounded border border-[var(--border-strong)] bg-white px-2 py-1 text-sm text-[var(--ink)]";

function Select({
  name,
  label,
  options,
}: {
  name: string;
  label: string;
  options: readonly (readonly [string, string])[];
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-[var(--ink-muted)]">{label}</span>
      <select name={name} className={CONTROL}>
        {options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export default async function SetupPage(props: PageProps<"/migrations/[migrationId]/setup">) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const [systems, datasets] = await Promise.all([
    apiGet<Schemas["SourceSystemOut"][]>(`/api/v1/migrations/${migrationId}/source-systems`),
    apiGet<Schemas["DatasetOut"][]>(`/api/v1/migrations/${migrationId}/datasets`),
  ]);
  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Setup"
        description="Declare the systems this company is migrating from, then the datasets exported from them. Each dataset takes an upload and an approved column mapping before a run can use it."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      <Section
        title="Stage 1 · Source systems"
        description="Where the legacy data comes from. One entry per system you will export files from."
      >
        <Panel className="divide-y divide-[var(--border)]">
          <ul className="text-sm" data-testid="source-systems">
            {systems.length === 0 ? (
              <li className="px-3 py-2.5 text-[var(--ink-subtle)]">
                No source systems yet. Add the first one below.
              </li>
            ) : (
              systems.map((s) => (
                <li
                  key={s.id}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--border)]/60 px-3 py-2 last:border-0"
                >
                  <span className="font-medium text-[var(--ink)]">{s.name}</span>
                  <span className="text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                    {humanize(s.kind)}
                  </span>
                </li>
              ))
            )}
          </ul>
          <form action={createSourceSystem} className="flex flex-wrap items-end gap-3 p-3">
            <input type="hidden" name="migrationId" value={migrationId} />
            <TextField name="name" label="Name" required />
            <Select name="kind" label="Kind" options={SYSTEM_KINDS.map((k) => [k, humanize(k)])} />
            <SubmitButton tone="secondary">Add source system</SubmitButton>
          </form>
        </Panel>
      </Section>

      {systems.length > 0 ? (
        <Section
          title="Stage 2 · Datasets"
          description="One dataset per exported file. The type tells Relay how to read it; agings need an as-of date and bank statements name the account they belong to."
        >
          <Panel className="mb-3">
            <form action={createDataset} className="p-3">
              <input type="hidden" name="migrationId" value={migrationId} />
              <div className="flex flex-wrap items-end gap-3">
                <Select
                  name="sourceSystemId"
                  label="Source system"
                  options={systems.map((s) => [s.id, s.name])}
                />
                <Select
                  name="datasetType"
                  label="Dataset type"
                  options={DATASET_TYPES.map((t) => [t, humanize(t)])}
                />
                <TextField name="name" label="Name" required />
              </div>
              <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-[var(--border)] pt-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-xs font-medium text-[var(--ink-muted)]">
                    As of (agings only)
                  </span>
                  <input type="date" name="asOfDate" className={CONTROL} />
                </label>
                <TextField name="bankAccount" label="Bank account (bank statements)" />
                <TextField name="glAccount" label="GL cash account (bank statements)" />
                <SubmitButton tone="secondary">Add dataset</SubmitButton>
              </div>
            </form>
          </Panel>
          <Panel>
            <ul className="text-sm" data-testid="setup-datasets">
              {datasets.length === 0 ? (
                <li className="px-3 py-2.5 text-[var(--ink-subtle)]">
                  No datasets yet. Add the first one above.
                </li>
              ) : (
                datasets.map((d) => (
                  <li
                    key={d.id}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[var(--border)]/60 px-3 py-2 last:border-0"
                  >
                    <span className="min-w-0">
                      <Link
                        href={`/migrations/${migrationId}/data/datasets/${d.id}`}
                        className="font-medium"
                      >
                        {d.name}
                      </Link>
                      <span className="ml-2 text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                        {humanize(d.dataset_type)}
                      </span>
                    </span>
                    <span className="flex flex-wrap items-baseline gap-3 text-xs">
                      <span
                        className={
                          d.active_import_id
                            ? "text-[var(--ink-muted)]"
                            : "font-medium text-[var(--warning)]"
                        }
                      >
                        {d.active_import_id ? "imported" : "no import yet"}
                      </span>
                      <Link href={`/migrations/${migrationId}/mappings/columns/${d.id}`}>
                        column mapping
                      </Link>
                    </span>
                  </li>
                ))
              )}
            </ul>
          </Panel>
        </Section>
      ) : (
        <Section title="Stage 2 · Datasets" description="Available once a source system exists.">
          <EmptyState
            title="Add a source system first"
            hint="Every dataset belongs to the system it was exported from."
          />
        </Section>
      )}

      <Section
        title="Stage 3 · Run"
        description="A run reads the active import of every dataset through its approved mapping, then validates and reconciles the result."
      >
        <Panel className="p-3">
          <Callout>
            Nothing here is destructive: a run recomputes results from the current inputs and leaves
            the imported rows untouched.
          </Callout>
          <form action={requestRun} className="mt-3">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="returnTo" value={`/migrations/${migrationId}/setup`} />
            <SubmitButton>Run the pipeline</SubmitButton>
          </form>
        </Panel>
      </Section>
    </div>
  );
}
