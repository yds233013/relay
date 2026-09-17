import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
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
      <span className="text-xs font-medium text-gray-700">{label}</span>
      <select name={name} className="rounded border border-gray-400 bg-white px-2 py-1">
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
        description="Source systems and the datasets exported from them. Then upload each file, approve its column mapping, and run the pipeline."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Source systems">
        <ul className="mb-2 list-inside list-disc text-sm" data-testid="source-systems">
          {systems.map((s) => (
            <li key={s.id}>
              {s.name} ({humanize(s.kind)})
            </li>
          ))}
        </ul>
        <form action={createSourceSystem} className="flex flex-wrap items-end gap-3">
          <input type="hidden" name="migrationId" value={migrationId} />
          <TextField name="name" label="Name" required />
          <Select name="kind" label="Kind" options={SYSTEM_KINDS.map((k) => [k, humanize(k)])} />
          <SubmitButton tone="secondary">Add source system</SubmitButton>
        </form>
      </Section>
      {systems.length > 0 ? (
        <Section title="Datasets">
          <form action={createDataset} className="mb-3 flex flex-wrap items-end gap-3">
            <input type="hidden" name="migrationId" value={migrationId} />
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
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">As of (agings only)</span>
              <input
                type="date"
                name="asOfDate"
                className="rounded border border-gray-400 bg-white px-2 py-1"
              />
            </label>
            <TextField name="bankAccount" label="Bank account (bank statements)" />
            <TextField name="glAccount" label="GL cash account (bank statements)" />
            <SubmitButton tone="secondary">Add dataset</SubmitButton>
          </form>
          <ul className="list-inside list-disc text-sm" data-testid="setup-datasets">
            {datasets.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/migrations/${migrationId}/data/datasets/${d.id}`}
                  className="underline"
                >
                  {d.name}
                </Link>{" "}
                ({humanize(d.dataset_type)}) · {d.active_import_id ? "imported" : "no import yet"} ·{" "}
                <Link
                  href={`/migrations/${migrationId}/mappings/columns/${d.id}`}
                  className="underline"
                >
                  column mapping
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title="Run">
        <form action={requestRun}>
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="returnTo" value={`/migrations/${migrationId}/setup`} />
          <SubmitButton>Run the pipeline</SubmitButton>
        </form>
      </Section>
    </div>
  );
}
