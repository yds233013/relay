import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, Panel, ProvenanceBadge } from "@/components/ui";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeRevert } from "../governance-actions";

export const dynamic = "force-dynamic";

function show(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

const HEAD =
  "border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]";

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
  const active = [...overrides, ...decisions, ...dispositions].filter(
    (row) => row.status === "active",
  ).length;
  return (
    <div className="max-w-7xl">
      <PageHeader
        title="Applied corrections"
        description="Every correction in force on this migration, and the approved change request that put it there."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <div className="mb-5">
        <Callout title="Corrections sit on top of the legacy data, never inside it">
          The imported rows are never edited or deleted. What you see here is a layer of approved
          decisions applied over them, which every run re-applies from scratch. That is why each row
          names the change request that authorised it, and why undoing one is not an edit either: it
          is another change request, needing the same approvals.{" "}
          {active > 0 ? `${active} corrections are currently in force.` : null}
        </Callout>
      </div>

      <Section
        title="Record overrides"
        description="One staged record corrected. The source line keeps its original text permanently; the override is applied on top of it each time the pipeline runs."
        actions={<ProvenanceBadge kind="canonical" />}
      >
        <Panel className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm" data-testid="overrides">
            <caption className="mb-2 px-2 pt-2 text-left text-sm font-semibold text-[var(--ink)]">
              {overrides.length} record overrides
            </caption>
            <thead>
              <tr className={HEAD}>
                <th scope="col" className="px-2 py-1.5 font-medium">
                  Record
                </th>
                <th scope="col" className="px-2 py-1.5 font-medium">
                  Correction applied
                </th>
                <th scope="col" className="px-2 py-1.5 font-medium">
                  Reason and authority
                </th>
                <th scope="col" className="px-2 py-1.5 font-medium">
                  Status
                </th>
                <th scope="col" className="px-2 py-1.5 font-medium">
                  Revert
                </th>
              </tr>
            </thead>
            <tbody>
              {overrides.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-2 py-3 text-[var(--ink-muted)]">
                    None yet. A record override appears here only once a change request proposing it
                    has been approved and applied.
                  </td>
                </tr>
              ) : null}
              {overrides.map((o) => (
                <tr key={o.id} className="border-b border-[var(--border)]/60 align-top">
                  <td className="px-2 py-1.5">
                    <span className="font-mono text-xs">{o.natural_key}</span>
                    <span className="block text-xs text-[var(--ink-muted)]">
                      {humanize(o.target)} · applied <LocalTime value={o.created_at} />
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">
                    {o.field
                      ? `${o.field}: ${show(o.expected_current_value)} → ${show(o.new_value)}`
                      : "row repaired"}
                  </td>
                  <td className="px-2 py-1.5">
                    {o.reason}{" "}
                    <span className="block text-xs text-[var(--ink-subtle)]">
                      authorised by{" "}
                      <Link
                        href={`/migrations/${migrationId}/change-requests/${o.change_request_id}`}
                        className="underline"
                      >
                        approval
                      </Link>
                    </span>
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
        </Panel>
      </Section>

      <Section
        title="Entity decisions"
        description="Merges and keep-distinct decisions about parties the engine flagged as possible duplicates. The legacy customers and vendors are never rewritten; the decision sits on top of them."
        actions={<ProvenanceBadge kind="canonical" />}
      >
        <OverlayTable
          migrationId={migrationId}
          target="entity_decision"
          testId="entity-decisions"
          caption="entity decisions"
          rows={decisions.map((d) => ({
            id: d.id,
            label: `${d.decision.replaceAll("_", " ")} decision on ${d.members.join(", ")}`,
            description: `${humanize(d.decision)}: ${d.members.join(", ")}${d.survivor ? ` (survivor ${d.survivor})` : ""}`,
            createdAt: d.created_at,
            reason: d.reason,
            status: d.status,
            changeRequestId: d.change_request_id,
            revertedBy: d.reverted_by_cr_id,
          }))}
        />
      </Section>
      <Section
        title="Dispositions"
        description="Real misstatements in the legacy books, accepted with a documented reason and follow-up rather than silently corrected in migration history."
        actions={<ProvenanceBadge kind="canonical" />}
      >
        <OverlayTable
          migrationId={migrationId}
          target="disposition"
          testId="dispositions"
          caption="dispositions"
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
            createdAt: d.created_at,
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
  createdAt: string;
  reason: string;
  status: string;
  changeRequestId: string;
  revertedBy: string | null;
}

function OverlayTable({
  migrationId,
  target,
  testId,
  caption,
  rows,
}: {
  migrationId: string;
  target: string;
  testId: string;
  caption: string;
  rows: OverlayRow[];
}) {
  return (
    <Panel className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" data-testid={testId}>
        <caption className="mb-2 px-2 pt-2 text-left text-sm font-semibold text-[var(--ink)]">
          {rows.length} {caption}
        </caption>
        <thead>
          <tr className={HEAD}>
            <th scope="col" className="px-2 py-1.5 font-medium">
              Decision
            </th>
            <th scope="col" className="px-2 py-1.5 font-medium">
              Reason and authority
            </th>
            <th scope="col" className="px-2 py-1.5 font-medium">
              Status
            </th>
            <th scope="col" className="px-2 py-1.5 font-medium">
              Revert
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="px-2 py-3 text-[var(--ink-muted)]">
                None yet. These appear here only once a change request proposing one has been
                approved and applied.
              </td>
            </tr>
          ) : null}
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-[var(--border)]/60 align-top">
              <td className="px-2 py-1.5">
                {row.description}
                <span className="block text-xs text-[var(--ink-muted)]">
                  applied <LocalTime value={row.createdAt} />
                </span>
              </td>
              <td className="px-2 py-1.5">
                {row.reason}{" "}
                <span className="block text-xs text-[var(--ink-subtle)]">
                  authorised by{" "}
                  <Link
                    href={`/migrations/${migrationId}/change-requests/${row.changeRequestId}`}
                    className="underline"
                  >
                    approval
                  </Link>
                </span>
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
    </Panel>
  );
}
