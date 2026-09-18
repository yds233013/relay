import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { EmptyState } from "@/components/ui";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeRevert } from "../governance-actions";

export const dynamic = "force-dynamic";

function show(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

export default async function OverridesPage(
  props: PageProps<"/migrations/[migrationId]/overrides">,
) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const [overrides, decisions, dispositions] = await Promise.all([
    apiGet<Schemas["RecordOverrideOut"][]>(`/api/v1/migrations/${migrationId}/record-overrides`),
    apiGet<Schemas["EntityDecisionOut"][]>(`/api/v1/migrations/${migrationId}/entity-decisions`),
    apiGet<Schemas["DispositionOut"][]>(`/api/v1/migrations/${migrationId}/dispositions`),
  ]);
  return (
    <div className="max-w-7xl">
      <PageHeader
        title="Overrides and decisions"
        description="Approved overrides, entity decisions and dispositions applied on top of immutable source rows. Reverting one is another change request with the same approvals."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm" data-testid="overrides">
          <caption className="mb-2 text-left text-sm font-semibold text-[var(--ink)]">
            {overrides.length} overrides
          </caption>
          <thead>
            <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
              <th scope="col" className="px-2 py-1.5">
                Record
              </th>
              <th scope="col" className="px-2 py-1.5">
                Change
              </th>
              <th scope="col" className="px-2 py-1.5">
                Reason
              </th>
              <th scope="col" className="px-2 py-1.5">
                Status
              </th>
              <th scope="col" className="px-2 py-1.5">
                Revert
              </th>
            </tr>
          </thead>
          <tbody>
            {overrides.map((o) => (
              <tr key={o.id} className="border-b border-[var(--border)]/60 align-top">
                <td className="px-2 py-1.5">
                  <span className="font-mono text-xs">{o.natural_key}</span>
                  <span className="block text-xs text-[var(--ink-muted)]">
                    {humanize(o.target)} · <LocalTime value={o.created_at} />
                  </span>
                </td>
                <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">
                  {o.field
                    ? `${o.field}: ${show(o.expected_current_value)} → ${show(o.new_value)}`
                    : "row repaired"}
                </td>
                <td className="px-2 py-1.5">
                  {o.reason}{" "}
                  <Link
                    href={`/migrations/${migrationId}/change-requests/${o.change_request_id}`}
                    className="underline"
                  >
                    approval
                  </Link>
                </td>
                <td className="px-2 py-1.5">
                  <StatusChip status={o.status} />
                </td>
                <td className="px-2 py-1.5">
                  {o.status === "active" ? (
                    <form action={proposeRevert} className="flex items-end gap-2">
                      <input type="hidden" name="migrationId" value={migrationId} />
                      <input type="hidden" name="targetId" value={o.id} />
                      <input type="hidden" name="target" value="record_override" />
                      <input type="hidden" name="label" value={`override on ${o.natural_key}`} />
                      <TextField name="justification" label="Why revert" required />
                      <SubmitButton tone="secondary">Propose revert</SubmitButton>
                    </form>
                  ) : o.reverted_by_cr_id ? (
                    <Link
                      href={`/migrations/${migrationId}/change-requests/${o.reverted_by_cr_id}`}
                      className="underline"
                    >
                      reverted
                    </Link>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Section
        title="Entity decisions"
        description="Merges and keep-distinct decisions. The legacy records are never rewritten; the decision sits on top of them."
      >
        <OverlayTable
          migrationId={migrationId}
          target="entity_decision"
          testId="entity-decisions"
          rows={decisions.map((d) => ({
            id: d.id,
            label: `${d.decision.replaceAll("_", " ")} decision on ${d.members.join(", ")}`,
            description: `${humanize(d.decision)}: ${d.members.join(", ")}${d.survivor ? ` (survivor ${d.survivor})` : ""}`,
            reason: d.reason,
            status: d.status,
            changeRequestId: d.change_request_id,
            revertedBy: d.reverted_by_cr_id,
          }))}
        />
      </Section>
      <Section
        title="Dispositions"
        description="Real legacy misstatements, accepted with a documented plan rather than silently corrected in migration history."
      >
        <OverlayTable
          migrationId={migrationId}
          target="disposition"
          testId="dispositions"
          rows={dispositions.map((d) => ({
            id: d.id,
            label: `disposition of ${d.issue_key}`,
            description: (
              <>
                <Link
                  href={`/migrations/${migrationId}/issues/${d.issue_id}`}
                  className="underline"
                >
                  {d.issue_key}
                </Link>{" "}
                {humanize(d.kind)}
                {d.amount && d.currency ? (
                  <>
                    {" "}
                    <Money value={d.amount} currency={d.currency} />
                  </>
                ) : null}
                {d.follow_up ? ` · follow-up: ${d.follow_up}` : ""}
              </>
            ),
            reason: d.reason,
            status: d.status,
            changeRequestId: d.change_request_id,
            revertedBy: d.reverted_by_cr_id,
          }))}
        />
      </Section>
    </div>
  );
}

interface OverlayRow {
  id: string;
  label: string;
  description: React.ReactNode;
  reason: string;
  status: string;
  changeRequestId: string;
  revertedBy: string | null;
}

function OverlayTable({
  migrationId,
  target,
  testId,
  rows,
}: {
  migrationId: string;
  target: string;
  testId: string;
  rows: OverlayRow[];
}) {
  if (rows.length === 0) {
    return (
      <EmptyState title="None yet." hint="Overlays appear here once a change request is applied." />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" data-testid={testId}>
        <caption className="sr-only">{testId.replaceAll("-", " ")}</caption>
        <thead>
          <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
            <th scope="col" className="px-2 py-1.5">
              Decision
            </th>
            <th scope="col" className="px-2 py-1.5">
              Reason
            </th>
            <th scope="col" className="px-2 py-1.5">
              Status
            </th>
            <th scope="col" className="px-2 py-1.5">
              Revert
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-[var(--border)]/60 align-top">
              <td className="px-2 py-1.5">{row.description}</td>
              <td className="px-2 py-1.5">
                {row.reason}{" "}
                <Link
                  href={`/migrations/${migrationId}/change-requests/${row.changeRequestId}`}
                  className="underline"
                >
                  approval
                </Link>
              </td>
              <td className="px-2 py-1.5">
                <StatusChip status={row.status} />
              </td>
              <td className="px-2 py-1.5">
                {row.status === "active" ? (
                  <form action={proposeRevert} className="flex items-end gap-2">
                    <input type="hidden" name="migrationId" value={migrationId} />
                    <input type="hidden" name="targetId" value={row.id} />
                    <input type="hidden" name="target" value={target} />
                    <input type="hidden" name="label" value={row.label} />
                    <TextField name="justification" label="Why revert" required />
                    <SubmitButton tone="secondary">Propose revert</SubmitButton>
                  </form>
                ) : row.revertedBy ? (
                  <Link
                    href={`/migrations/${migrationId}/change-requests/${row.revertedBy}`}
                    className="underline"
                  >
                    reverted
                  </Link>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
