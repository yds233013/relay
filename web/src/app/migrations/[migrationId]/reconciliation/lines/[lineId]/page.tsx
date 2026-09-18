import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, MetricCard, ProvenanceBadge } from "@/components/ui";
import { RecordRef } from "@/components/record-ref";
import { SourceLocation } from "@/components/source-location";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

type Record = Schemas["StagedRecordOut"];

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
    <table className="mb-3 w-full border-collapse text-left text-sm">
      <caption className="mb-1 text-left text-xs font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
        {caption}
      </caption>
      <thead>
        <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
          <th scope="col" className="px-2 py-1">
            Record
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
            Source
          </th>
        </tr>
      </thead>
      <tbody>
        {records.map((record) => (
          <tr key={record.natural_key} className="border-b border-[var(--border)]/60 last:border-0">
            <td className="px-2 py-1">
              <RecordRef migrationId={migrationId} runId={runId} naturalKey={record.natural_key} />
              {record.role ? (
                <span className="ml-1 text-xs text-[var(--ink-subtle)]">
                  ({humanize(record.role)})
                </span>
              ) : null}
            </td>
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
            Why this line differs, record by record, down to the file it came from.{" "}
            <Link href={`/migrations/${migrationId}/reconciliation?run=${d.run_id}`}>
              Back to reconciliation results
            </Link>
          </>
        }
        status={<StatusChip status={d.status} />}
      />
      <dl className="mb-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        {(
          [
            [d.left_label ?? "Left", d.left_amount, "neutral"],
            [d.right_label ?? "Right", d.right_amount, "neutral"],
            ["Difference", d.difference, "neutral"],
            [
              "Unexplained",
              d.unexplained_amount,
              // String inspection, never arithmetic: money is a server-provided decimal (FC-15).
              /[1-9]/.test(d.unexplained_amount) ? "critical" : "neutral",
            ],
          ] as const
        ).map(([label, value, tone]) => (
          <MetricCard
            key={label}
            label={label}
            tone={tone}
            value={<Money value={value} currency={d.currency} />}
          />
        ))}
      </dl>
      {d.limits ? (
        <div className="mb-4">
          <Callout>{d.limits}</Callout>
        </div>
      ) : null}

      {d.basis === "documents" ? (
        <Section
          title="Documents that differ"
          description="Documents present on one side and not the other, or carrying a different amount."
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
          <ul className="space-y-3" data-testid="drilldown-documents">
            {d.documents.map((document) => (
              <li
                key={document.document}
                className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3"
                data-document={document.document}
              >
                <p className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono font-medium">{document.document}</span>
                  <StatusChip status={document.status} label={humanize(document.status)} />
                  <span>
                    left <Money value={document.left_amount} currency={d.currency} /> right{" "}
                    <Money value={document.right_amount} currency={d.currency} /> difference{" "}
                    <Money value={document.difference} currency={d.currency} />
                  </span>
                </p>
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
          <Section title="Control balances" actions={<ProvenanceBadge kind="canonical" />}>
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
          <Section title="Lines where entry date and posting period disagree">
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
          description="Each part of the difference, attributed to the records that explain it."
          actions={<ProvenanceBadge kind="derived" />}
        >
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
                <RecordsTable caption="Records" records={item.records} {...tableProps} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {d.quarantined_rows.length > 0 ? (
        <Section
          title="Rows that could not be read"
          description="Quarantined source lines. They stay in the import exactly as received."
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
