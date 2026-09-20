import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { BusinessDate } from "@/components/dates";
import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import {
  Callout,
  EmptyState,
  MetaList,
  PageHeader,
  Panel,
  ProvenanceBadge,
  Section,
} from "@/components/ui";
import { isPublicDemo } from "@/lib/demo";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeFieldOverride } from "../../../governance-actions";

/** Canonical fields the engine can override, by natural key prefix. */
const OVERRIDABLE: Record<string, readonly string[]> = { je: ["entry_date", "posting_period"] };

/**
 * What a staged record is, in the words an accountant would use for it.
 *
 * Copy only: the record types come from the canonical model, and anything not listed falls back to
 * its own name.
 */
const RECORD_TYPES: Record<string, { label: string; gloss: string }> = {
  journal_entry: {
    label: "Journal entry",
    gloss:
      "One posting in the general ledger: a header, with the debit and credit lines that sit beneath it.",
  },
  journal_line: {
    label: "Journal line",
    gloss:
      "One debit or credit line of a general ledger posting, against a single account — and, where the legacy system recorded one, a single customer, vendor or document.",
  },
  trial_balance: {
    label: "Trial balance line",
    gloss:
      "One account's balance on a control report the legacy system produced. Control reports are the independent side Relay checks the detail against.",
  },
  aging_item: {
    label: "Aging line",
    gloss:
      "One open invoice or bill exactly as the legacy aging report listed it at a cut-off date.",
  },
  invoice: {
    label: "Customer invoice",
    gloss: "An open item owed to the company, staged from the receivables subledger.",
  },
  bill: {
    label: "Vendor bill",
    gloss: "An open item the company owes, staged from the payables subledger.",
  },
  payment: {
    label: "Payment",
    gloss: "Cash received or paid out, as the legacy system recorded it.",
  },
  bank_transaction: {
    label: "Bank transaction",
    gloss:
      "One line of the bank statement. It comes from the bank, not from the ledger, which is what makes it usable as independent evidence.",
  },
  customer: { label: "Customer", gloss: "A party the company sells to." },
  vendor: { label: "Vendor", gloss: "A party the company buys from." },
  target_account: {
    label: "Target account",
    gloss: "One account of the chart of accounts this migration is landing on.",
  },
  account_mapping: {
    label: "Account mapping",
    gloss: "One legacy account and the target account it has been mapped to.",
  },
};

/** Whose problem a finding is. Mirrors the wording on the overview. */
const NATURE_HINT: Record<string, string> = {
  migration_defect: "Relay or the export is wrong — fix it before go-live",
  source_anomaly: "the legacy books are wrong — carry a decision forward",
};

/** A non-empty string field of an untyped record payload, or null. */
function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** An amount-and-currency pair as the canonical model writes it. Never parsed into a number. */
function moneyish(value: unknown): { amount: string; currency: string } | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const { amount, currency } = value as { amount?: unknown; currency?: unknown };
  return typeof amount === "string" && typeof currency === "string" ? { amount, currency } : null;
}

/** One normalized field, shown as a value rather than as JSON where its shape is known. */
function FieldValue({ value }: { value: unknown }) {
  const money = moneyish(value);
  if (money) {
    return <Money value={money.amount} currency={money.currency} />;
  }
  if (value === null || value === undefined || value === "") {
    return <span className="text-[var(--ink-subtle)]">—</span>;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as { [key: string]: unknown });
    // A flat nested object (a party, a reference) reads better as labelled parts than as JSON.
    if (
      !Array.isArray(value) &&
      entries.every(([, part]) => part === null || typeof part !== "object")
    ) {
      return (
        <span>
          {entries
            .map(
              ([part, partValue]) =>
                `${humanize(part)}: ${partValue === null ? "—" : String(partValue)}`,
            )
            .join(" · ")}
        </span>
      );
    }
    return <span className="font-mono text-xs">{JSON.stringify(value)}</span>;
  }
  return <span className="font-mono text-xs">{String(value)}</span>;
}

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

  // What this record is, said in business terms before any raw values appear.
  const recordType = text(record.record.record_type);
  const described = recordType ? RECORD_TYPES[recordType] : undefined;
  const typeLabel = described?.label ?? (recordType ? humanize(recordType) : "Staged record");
  const typeGloss =
    described?.gloss ?? "One record Relay staged from the files imported for this migration.";
  // Prefer the canonical amount-and-currency pair; both are server-provided strings, never parsed.
  const canonicalAmount = moneyish(record.data.functional_amount) ?? moneyish(record.data.amount);
  const amount = canonicalAmount?.amount ?? text(record.record.functional_amount);
  const amountCurrency = canonicalAmount?.currency;
  const identity: { label: string; value: React.ReactNode }[] = [];
  const accountCode = text(record.record.account_code);
  if (accountCode) {
    identity.push({ label: "Account", value: <span className="font-mono">{accountCode}</span> });
  }
  const partyCode = text(record.record.party_code);
  if (partyCode) {
    identity.push({
      label: "Customer or vendor",
      value: <span className="font-mono">{partyCode}</span>,
    });
  }
  const documentNumber = text(record.record.document_number);
  if (documentNumber) {
    identity.push({
      label: "Document",
      value: <span className="font-mono">{documentNumber}</span>,
    });
  }
  const entryNumber = text(record.record.entry_number);
  if (entryNumber) {
    identity.push({
      label: "Journal entry number",
      value: <span className="font-mono">{entryNumber}</span>,
    });
  }
  const recordDate = text(record.record.record_date);
  if (recordDate) {
    identity.push({ label: "Date on the record", value: <BusinessDate value={recordDate} /> });
  }
  const postingPeriod = text(record.record.posting_period);
  if (postingPeriod) {
    identity.push({
      label: "Posting period",
      value: <span className="tabular-nums">{postingPeriod}</span>,
    });
  }
  if (amount && amountCurrency) {
    identity.push({ label: "Amount", value: <Money value={amount} currency={amountCurrency} /> });
  }

  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Record inspector"
        breadcrumbs={[{ label: "Overview", href: base }, { label: "Record" }]}
        description={
          <>
            One record, twice: exactly what the legacy system exported, beside Relay&apos;s
            normalized reading of it.{" "}
            <span className="font-mono text-xs text-[var(--ink)]">{key}</span>
          </>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />

      <Section title="What this record is">
        <Panel className="p-4">
          <p className="text-lg font-semibold tracking-tight text-[var(--ink)]">{typeLabel}</p>
          <p className="mt-0.5 max-w-3xl text-sm text-[var(--ink-muted)]">{typeGloss}</p>
          {identity.length > 0 ? (
            <div className="mt-3 border-t border-[var(--border)] pt-3">
              <MetaList items={identity} columns={4} />
            </div>
          ) : null}
        </Panel>
      </Section>

      <Section
        title="The exported row, and how Relay read it"
        description="The same record on both sides. The left is evidence and never changes; the right is Relay's interpretation of it, and is what every check reads."
      >
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2">
              <h3 className="text-sm font-semibold text-[var(--ink)]">Original source row</h3>
              <ProvenanceBadge kind="source" />
            </div>
            <p className="px-3 pt-2 text-xs text-[var(--ink-muted)]">
              Exactly what the export contained, stored append-only. Relay never edits it — a
              correction is an overlay recorded on top of it.
            </p>
            {record.source_row ? (
              <>
                <p
                  className="mt-2 border-y border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-1.5 text-sm"
                  data-testid="source-location"
                >
                  <SourceLocation migrationId={migrationId} lineage={lineage} />
                </p>
                <div className="overflow-x-auto" tabIndex={0}>
                  <table
                    className="w-full border-collapse text-left text-sm"
                    data-testid="source-row"
                  >
                    <caption className="sr-only">
                      Raw source values, column by column, as exported
                    </caption>
                    <tbody>
                      {(record.source_header ?? Object.keys(record.source_row.values))
                        .map((column) => [column, record.source_row?.values[column] ?? ""] as const)
                        .map(([column, value]) => (
                          <tr
                            key={column}
                            className="border-b border-[var(--border)]/60 last:border-0"
                          >
                            <th
                              scope="row"
                              className="w-48 px-3 py-1 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]"
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
              </>
            ) : (
              <div className="p-3">
                <EmptyState
                  title="This record has no single source row."
                  hint="Derived records — such as an aggregate — carry lineage to every row behind them instead."
                />
              </div>
            )}
          </Panel>

          <Panel tone="accent" className="overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--accent)]/30 px-3 py-2">
              <h3 className="text-sm font-semibold text-[var(--accent-ink)]">
                Relay&apos;s normalized record
              </h3>
              <ProvenanceBadge kind="canonical" />
            </div>
            <p className="px-3 pt-2 text-xs text-[var(--ink-muted)]">
              Produced from the exported row by the approved column mapping: the same values, parsed
              into typed fields. This is an interpretation, not evidence — when it looks wrong, the
              mapping or an approved override changes, never the row itself.
            </p>
            <div className="mt-2 overflow-x-auto" tabIndex={0}>
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">
                  Normalized fields Relay derived from the source row
                </caption>
                <tbody>
                  {Object.entries(record.data).map(([field, value]) => (
                    <tr key={field} className="border-b border-[var(--accent)]/20 last:border-0">
                      <th
                        scope="row"
                        className="w-48 px-3 py-1 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]"
                      >
                        {humanize(field)}
                      </th>
                      <td className="px-3 py-1 text-xs text-[var(--ink)]">
                        <FieldValue value={value} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className="border-t border-[var(--accent)]/30 px-3 py-2">
              <summary className="cursor-pointer text-xs text-[var(--ink-muted)]">
                Exact normalized values as stored
              </summary>
              <pre className="mt-2 overflow-x-auto text-xs text-[var(--ink)]" tabIndex={0}>
                {JSON.stringify(record.data, null, 2)}
              </pre>
            </details>
          </Panel>
        </div>
      </Section>

      {overridable.length > 0 ? (
        <Section
          title="Propose a correction"
          description="Proposing changes nothing on its own: it opens a change request for someone else to approve. Only then does a run apply the new value."
        >
          <Panel className="p-3">
            <Callout tone="warning" title="The source row is never edited">
              The source row never changes. An approved override applies the new value on top of it,
              and every run checks that the value it replaces is still the one shown here.
            </Callout>
            <p className="mt-3 text-sm text-[var(--ink-muted)]">
              The field below belongs to the normalized record on the right, not to the exported row
              on the left.
            </p>
            {isPublicDemo() ? (
              <DemoUnavailable what="A correction never edits the exported row: it is an approved overlay applied on top of it on every run." />
            ) : (
              <form action={proposeFieldOverride} className="mt-2 flex max-w-2xl flex-col gap-2">
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
            )}
          </Panel>
        </Section>
      ) : null}

      <Section
        title="What Relay's checks found here"
        description="Findings Relay's automatic rules and reconciliations raised against this record. They are produced by the run, never written or cleared by hand: a finding goes away when a run stops reporting it."
        actions={<ProvenanceBadge kind="derived" />}
      >
        {record.related_issues.length === 0 ? (
          <EmptyState
            title="No issue names this record as a subject."
            hint="Relay's checks read this record on the current run and raised nothing against it."
          />
        ) : (
          <Panel className="divide-y divide-[var(--border)]">
            {record.related_issues.map((issue) => (
              <div key={issue.id} className="px-3 py-2 text-sm">
                <p className="flex flex-wrap items-center gap-2">
                  <Link href={`${base}/issues/${issue.id}`} className="font-medium">
                    {issue.key}
                  </Link>
                  <StatusChip status={issue.severity} />
                  <StatusChip status={issue.status} />
                  <span className="text-[var(--ink-muted)]">{issue.title}</span>
                </p>
                <p className="mt-1 text-xs text-[var(--ink-subtle)]">
                  {issue.rule_or_recon_id ? (
                    <>
                      Raised by the automatic check{" "}
                      <span className="font-mono">{issue.rule_or_recon_id}</span>
                      {" · "}
                    </>
                  ) : null}
                  {humanize(issue.nature)}
                  {NATURE_HINT[issue.nature] ? `: ${NATURE_HINT[issue.nature]}` : null}
                  {issue.amount_at_risk ? (
                    <>
                      {" · "}
                      <Money value={issue.amount_at_risk} currency={issue.currency} /> at risk
                    </>
                  ) : null}
                </p>
              </div>
            ))}
          </Panel>
        )}
      </Section>
    </div>
  );
}
