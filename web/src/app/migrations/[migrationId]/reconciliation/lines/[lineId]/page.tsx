import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, MetricCard, Panel, ProvenanceBadge } from "@/components/ui";
import { reconciliationGloss } from "@/components/reconciliation-glossary";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

type Record = Schemas["StagedRecordOut"];

/** What a document-level status means, without the reader needing the specification. */
const DOCUMENT_STATUS_HINT: { readonly [status: string]: string } = {
  left_only: "On the left side only — nothing on the right side matches it.",
  right_only: "On the right side only — nothing on the left side matches it.",
  different: "On both sides, but the two amounts do not agree.",
};

/** Plain English for each kind of reconciling item Relay identifies. */
const CLASSIFICATION_HINT: { readonly [classification: string]: string } = {
  deposit_in_transit: "The ledger recorded the money before the bank did.",
  outstanding_check: "The ledger recorded the payment; the bank has not cleared it yet.",
  bank_only_activity: "The bank statement shows activity the ledger never recorded.",
  ledger_only_activity: "The ledger shows activity the bank statement does not.",
};

function RecordsTable({
  caption,
  records,
  migrationId,
  runId,
  currency,
}: {
  caption: string;
  records: readonly Record[];
  migrationId: string;
  runId: string;
  currency: string;
}) {
  if (records.length === 0) {
    return (
      <p className="mb-2 rounded border border-dashed border-[var(--border)] px-3 py-2 text-sm text-[var(--ink-muted)]">
        {caption}: none.
      </p>
    );
  }
  return (
    <div className="mb-3 overflow-x-auto" tabIndex={0}>
      <table className="w-full border-collapse text-left text-sm">
        <caption className="mb-1 text-left text-xs font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
          {caption}
        </caption>
        <thead>
          <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
            <th scope="col" className="px-2 py-1">
              Record Relay staged
            </th>
            <th scope="col" className="px-2 py-1">
              Date
            </th>
            <th scope="col" className="px-2 py-1">
              Account
            </th>
            <th scope="col" className="px-2 py-1 text-right">
              Amount
            </th>
            <th scope="col" className="px-2 py-1">
              Line in the uploaded file
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr
              key={record.natural_key}
              className="border-b border-[var(--border)]/60 last:border-0"
            >
              <th scope="row" className="px-2 py-1 font-normal">
                <RecordRef
                  migrationId={migrationId}
                  runId={runId}
                  naturalKey={record.natural_key}
                />
                {record.role ? (
                  <span className="ml-1 text-xs text-[var(--ink-subtle)]">
                    ({humanize(record.role)})
                  </span>
                ) : null}
              </th>
              <td className="px-2 py-1">
                <BusinessDate value={record.record_date} />
              </td>
              <td className="px-2 py-1 font-mono text-xs text-[var(--ink-muted)]">
                {record.account_code ?? "—"}
              </td>
              <td className="px-2 py-1 text-right">
                <Money value={record.open_amount ?? record.functional_amount} currency={currency} />
              </td>
              <td className="px-2 py-1">
                <SourceLocation migrationId={migrationId} lineage={record.lineage} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One line telling the reader that everything in a section is a link to underlying evidence. */
function EvidenceHint() {
  return (
    <p className="mb-2 text-xs text-[var(--ink-subtle)]">
      Every record below links to what Relay staged, and every file reference links to the exact
      line of the uploaded export.
    </p>
  );
}

export default async function DrilldownPage(
  props: PageProps<"/migrations/[migrationId]/reconciliation/lines/[lineId]">,
) {
  const { migrationId, lineId } = await props.params;
  const d = await apiGet<Schemas["DrilldownOut"]>(
    `/api/v1/reconciliation-lines/${lineId}/drilldown`,
  );
  const grain = Object.entries(d.grain)
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
  const grainWords = Object.entries(d.grain)
    .map(([k, v]) => `${humanize(k).toLowerCase()} ${v}`)
    .join(", ");
  const leftLabel = d.left_label ?? "Left side";
  const rightLabel = d.right_label ?? "Right side";
  const gloss = reconciliationGloss(d.recon_id);
  const tableProps = { migrationId, runId: d.run_id, currency: d.currency };

  return (
    <div className="max-w-6xl">
      <PageHeader
        title={`${d.recon_id} drill-down: ${grain}`}
        breadcrumbs={[
          { label: "Overview", href: `/migrations/${migrationId}` },
          {
            label: "Reconciliation",
            href: `/migrations/${migrationId}/reconciliation?run=${d.run_id}`,
          },
          { label: d.recon_id },
        ]}
        description={
          <>
            Why the two sides of this control disagree — record by record, down to the line of the
            file each one came from.{" "}
            <Link href={`/migrations/${migrationId}/reconciliation?run=${d.run_id}`}>
              Back to reconciliation results
            </Link>
          </>
        }
        status={<StatusChip status={d.status} />}
      />

      <Panel className="mb-4 p-4">
        <p className="text-sm text-[var(--ink)]">
          {d.left_label && d.right_label ? (
            <>
              <span className="font-medium">{d.left_label}</span> should equal{" "}
              <span className="font-medium">{d.right_label}</span>
            </>
          ) : (
            <>The two sides of this control should agree</>
          )}
          {grainWords ? <> for {grainWords}</> : null}. Anything left over is money one side reports
          and the other does not.
        </p>
        {gloss ? <p className="mt-1 max-w-4xl text-sm text-[var(--ink-muted)]">{gloss}</p> : null}
        <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          {(
            [
              [leftLabel, d.left_amount, "neutral", "Left side of the comparison", false],
              [rightLabel, d.right_amount, "neutral", "Right side of the comparison", false],
              ["Difference", d.difference, "neutral", "Left side minus right side", true],
              [
                "Unexplained",
                d.unexplained_amount,
                // String inspection, never arithmetic: money is a server-provided decimal (FC-15).
                /[1-9]/.test(d.unexplained_amount) ? "critical" : "neutral",
                "Part of the difference no record accounts for",
                true,
              ],
            ] as const
          ).map(([label, value, tone, hint, emphasis]) => (
            <MetricCard
              key={label}
              label={label}
              tone={tone}
              hint={hint}
              emphasis={emphasis}
              value={<Money value={value} currency={d.currency} />}
            />
          ))}
        </dl>
      </Panel>
      {d.limits ? (
        <div className="mb-4">
          <Callout title="What this comparison can and cannot show">{d.limits}</Callout>
        </div>
      ) : null}

      {d.basis === "documents" ? (
        <Section
          title="Documents that differ"
          description="Invoices, bills and other documents that appear on one side only, or on both sides with different amounts. Documents that agree are not listed."
          actions={<ProvenanceBadge kind="canonical" />}
        >
          {d.opening ? (
            <p className="mb-2 text-sm">
              Opening control balance{" "}
              <Money value={d.opening.opening_control_balance} currency={d.currency} /> less opening
              aging <Money value={d.opening.opening_aging_total} currency={d.currency} /> leaves{" "}
              <Money value={d.opening.opening_unassigned} currency={d.currency} /> without a party.
            </p>
          ) : null}
          <p className="mb-2 text-sm text-[var(--ink-muted)]">
            {d.matched_document_count ?? 0} documents match on both sides and are not listed.
          </p>
          <EvidenceHint />
          <ul className="space-y-3" data-testid="drilldown-documents">
            {d.documents.map((document) => (
              <li
                key={document.document}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3 transition-colors hover:border-[var(--border-strong)]"
                data-document={document.document}
              >
                <p className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono font-medium">{document.document}</span>
                  <StatusChip status={document.status} label={humanize(document.status)} />
                </p>
                {DOCUMENT_STATUS_HINT[document.status] ? (
                  <p className="mt-1 text-sm text-[var(--ink-muted)]">
                    {DOCUMENT_STATUS_HINT[document.status]}
                  </p>
                ) : null}
                <dl className="mt-2 mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
                  <div>
                    <dt className="inline text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                      Left{" "}
                    </dt>
                    <dd className="inline font-medium">
                      <Money value={document.left_amount} currency={d.currency} />
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                      Right{" "}
                    </dt>
                    <dd className="inline font-medium">
                      <Money value={document.right_amount} currency={d.currency} />
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                      Difference{" "}
                    </dt>
                    <dd className="inline font-medium">
                      <Money value={document.difference} currency={d.currency} />
                    </dd>
                  </div>
                </dl>
                <RecordsTable
                  caption="Left side records"
                  records={document.left_records}
                  {...tableProps}
                />
                <RecordsTable
                  caption="Right side records"
                  records={document.right_records}
                  {...tableProps}
                />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {d.basis === "accounts" ? (
        <>
          <Section
            title="Control balances"
            description="The legacy system's own balances for these accounts. A control report is an aggregate, so Relay cannot match it row by row — it compares the totals and then shows what could move them."
            actions={<ProvenanceBadge kind="canonical" />}
          >
            <EvidenceHint />
            <RecordsTable
              caption={`Accounts ${d.accounts.join(", ")}`}
              records={d.control_balances}
              {...tableProps}
            />
            <p className="text-sm">
              Detail: {d.detail_line_count} lines totalling{" "}
              <Money value={d.detail_total} currency={d.currency} /> by entry date.
            </p>
          </Section>
          <Section
            title="Lines where entry date and posting period disagree"
            description="Each line below carries an entry date in one period and a posting period in another, so the control report and Relay's detail count the same money in different periods. That is the usual reason an account ties overall but not period by period."
          >
            <RecordsTable
              caption="Likely timing contributors"
              records={d.date_period_disagreements}
              {...tableProps}
            />
          </Section>
        </>
      ) : null}

      {d.basis === "reconciling_items" ? (
        <Section
          title="Reconciling items"
          description="Each part of the difference, attributed to the records that explain it. A difference is only explained when a named record accounts for it — an explained item is still an item someone has to accept."
          actions={<ProvenanceBadge kind="derived" />}
        >
          <EvidenceHint />
          <ul className="space-y-2">
            {d.items.map((item, index) => (
              <li
                key={`${item.classification}-${index}`}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm"
              >
                <p>
                  <span className="font-medium">{humanize(item.classification)}</span>{" "}
                  <Money value={item.amount} currency={d.currency} />: {item.message}
                </p>
                {CLASSIFICATION_HINT[item.classification] ? (
                  <p className="mt-0.5 mb-2 text-sm text-[var(--ink-muted)]">
                    {CLASSIFICATION_HINT[item.classification]}
                  </p>
                ) : null}
                <RecordsTable caption="Records" records={item.records} {...tableProps} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {d.quarantined_rows.length > 0 ? (
        <Section
          title="Rows that could not be read"
          description="Lines of the export Relay could not parse, so nothing from them reached the staged detail. They are kept exactly as received, and they may account for part of the difference above."
          actions={<ProvenanceBadge kind="source" />}
        >
          <ul className="list-inside list-disc text-sm">
            {d.quarantined_rows.map((row) => (
              <li key={`${row.import_id}-${row.line_start}`}>
                <Link
                  href={`/migrations/${migrationId}/data/imports/${row.import_id}#quarantine`}
                  className="underline"
                >
                  lines {row.line_start}–{row.line_end}
                </Link>{" "}
                ({humanize(row.reason)})
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
