import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { SignalChips } from "@/components/signal-chips";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { reviewChangeRequest, withdrawChangeRequest } from "../../governance-actions";

export const dynamic = "force-dynamic";

type Detail = Schemas["ChangeRequestDetailOut"];
type Json = Record<string, unknown>;

function str(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

function AccountMappingChanges({ detail }: { detail: Detail }) {
  const impact = (detail.impact ?? {}) as Json;
  const changes = (impact.changes ?? []) as Json[];
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" data-testid="mapping-diff">
        <caption className="mb-2 text-left text-sm text-gray-800">
          {str(impact.changed_count)} legacy accounts change
          {impact.changes_truncated ? " (first 500 shown)" : ""}.
        </caption>
        <thead>
          <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
            <th scope="col" className="px-2 py-1.5">
              Legacy account
            </th>
            <th scope="col" className="px-2 py-1.5">
              Before
            </th>
            <th scope="col" className="px-2 py-1.5">
              After
            </th>
            <th scope="col" className="px-2 py-1.5">
              Compatibility of new target
            </th>
            <th scope="col" className="px-2 py-1.5">
              Rationale
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => (
            <tr key={str(change.legacy)} className="border-b border-gray-100 align-top">
              <td className="px-2 py-1.5">
                <span className="font-mono">{str(change.legacy)}</span> {str(change.legacy_name)}
                <span className="block text-xs text-gray-700">{str(change.legacy_subtype)}</span>
              </td>
              <td className="px-2 py-1.5">
                <del className="font-mono">{str(change.before)}</del> {str(change.before_name)}
              </td>
              <td className="px-2 py-1.5">
                <ins className="font-mono no-underline">{str(change.after)}</ins>{" "}
                {str(change.after_name)}
                <span className="block text-xs text-gray-700">{str(change.after_subtype)}</span>
              </td>
              <td className="px-2 py-1.5">
                <SignalChips signals={change.signals} />
              </td>
              <td className="px-2 py-1.5">{str(change.rationale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BeforeAfter({ rows }: { rows: [string, unknown, unknown][] }) {
  return (
    <table className="w-full border-collapse text-left text-sm" data-testid="before-after">
      <caption className="sr-only">Before and after</caption>
      <thead>
        <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
          <th scope="col" className="px-2 py-1.5">
            Field
          </th>
          <th scope="col" className="px-2 py-1.5">
            Before
          </th>
          <th scope="col" className="px-2 py-1.5">
            After
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, before, after]) => (
          <tr key={label} className="border-b border-gray-100 align-top">
            <th scope="row" className="px-2 py-1.5 font-normal text-gray-700">
              {label}
            </th>
            <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">{str(before)}</td>
            <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">{str(after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Diff({ detail, migrationId }: { detail: Detail; migrationId: string }) {
  const before = (detail.before ?? {}) as Json;
  const after = (detail.after ?? {}) as Json;
  const impact = (detail.impact ?? {}) as Json;
  const kind = detail.change_request.kind;
  if (detail.before === null) {
    return <p className="text-sm text-gray-700">Before and after are computed when submitted.</p>;
  }
  if (kind === "account_mapping_set") {
    return (
      <>
        <p className="mb-2 text-sm">
          Replaces{" "}
          {before.approved_version
            ? `approved version ${str(before.approved_version)}`
            : "the account mapping file"}{" "}
          ({str(before.entries)} accounts) with version {str(after.version)} ({str(after.entries)}{" "}
          accounts).
        </p>
        <AccountMappingChanges detail={detail} />
      </>
    );
  }
  if (kind === "record_override") {
    const runId = typeof impact.run_id === "string" ? impact.run_id : null;
    const key = str(before.natural_key);
    return (
      <>
        <p className="mb-2 text-sm">
          Record{" "}
          {runId && !key.startsWith("quarantine:") ? (
            <Link
              href={`/migrations/${migrationId}/records/${runId}/${encodeURIComponent(key)}`}
              className="font-mono underline"
            >
              {key}
            </Link>
          ) : (
            <span className="font-mono">{key}</span>
          )}
          {impact.amount ? (
            <>
              {" "}
              · entry size <Money value={str(impact.amount)} currency={str(impact.currency)} />
            </>
          ) : null}
          {impact.restores_row ? " · restores a source line, including its amounts" : null}
        </p>
        {"raw_text" in before ? (
          <BeforeAfter rows={[["Source text", before.raw_text, after.replacement_text]]} />
        ) : (
          <BeforeAfter rows={[[str(before.field), before.value, after.value]]} />
        )}
      </>
    );
  }
  if (kind === "column_mapping_set") {
    const fields = (impact.changed_fields ?? []) as string[];
    const beforeFields = (before.fields ?? {}) as Json;
    const afterFields = (after.fields ?? {}) as Json;
    return (
      <>
        <p className="mb-2 text-sm">
          {str(impact.dataset_name)}: approved version {str(before.approved_version)} →{" "}
          {str(after.approved_version)}; {fields.length} fields change.
        </p>
        <BeforeAfter rows={fields.map((f) => [f, beforeFields[f], afterFields[f]])} />
      </>
    );
  }
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  return <BeforeAfter rows={keys.map((k) => [humanize(k), before[k], after[k]])} />;
}

export default async function ChangeRequestPage(
  props: PageProps<"/migrations/[migrationId]/change-requests/[changeId]">,
) {
  const { migrationId, changeId } = await props.params;
  const query = await props.searchParams;
  const detail = await apiGet<Detail>(`/api/v1/change-requests/${changeId}`);
  const change = detail.change_request;
  const open = ["draft", "submitted", "stale"].includes(change.status);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title={`${change.key}: ${change.title}`}
        description={`${humanize(change.kind)} · requested by ${change.requested_by_name}`}
      >
        <StatusChip status={change.status} />
      </PageHeader>
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Justification">
        <p className="text-sm whitespace-pre-wrap">{change.justification || "—"}</p>
      </Section>
      <Section title="Change">
        <Diff detail={detail} migrationId={migrationId} />
      </Section>
      <Section title="Approvals">
        <ul className="mb-3 space-y-1 text-sm" data-testid="requirements">
          {detail.requirements.map((requirement) => (
            <li key={requirement.index} className="flex items-center gap-2">
              <StatusChip
                status={requirement.satisfied_by ? "pass" : "pending"}
                label={requirement.satisfied_by ? "approved" : "waiting"}
              />
              {humanize(requirement.role)}
              {requirement.satisfied_by ? ` — ${requirement.satisfied_by}` : ""}
            </li>
          ))}
        </ul>
        {detail.approvals.length > 0 ? (
          <ul className="mb-3 space-y-1 text-sm">
            {detail.approvals.map((approval) => (
              <li key={approval.reviewer_user_id}>
                <LocalTime value={approval.decided_at} /> {approval.reviewer_name} (
                {humanize(approval.role)}) {approval.decision}d
                {approval.comment ? `: ${approval.comment}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
        {detail.viewer.can_review ? (
          <form action={reviewChangeRequest} className="flex max-w-xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="changeId" value={change.id} />
            <TextArea name="comment" label="Comment (required to reject)" rows={2} />
            <span className="flex gap-2">
              <SubmitButton name="decision" value="approve">
                Approve
              </SubmitButton>
              <SubmitButton name="decision" value="reject" tone="danger">
                Reject
              </SubmitButton>
            </span>
          </form>
        ) : (
          <p className="text-sm text-gray-700" data-testid="review-unavailable">
            You cannot review this change request: {detail.viewer.reason}.
          </p>
        )}
        {detail.viewer.is_requester && open ? (
          <form action={withdrawChangeRequest} className="mt-3 flex items-end gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="changeId" value={change.id} />
            <SubmitButton tone="secondary">Withdraw</SubmitButton>
          </form>
        ) : null}
      </Section>
      {detail.runs.length > 0 ? (
        <Section title="Pipeline runs requested by this change">
          <ul className="list-inside list-disc text-sm">
            {detail.runs.map((runId) => (
              <li key={runId}>
                <Link href={`/migrations/${migrationId}/runs/${runId}`} className="underline">
                  Run {runId}
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title="History">
        <ol className="space-y-1 text-sm" data-testid="history">
          {detail.history.map((event) => (
            <li key={event.id}>
              <LocalTime value={event.occurred_at} /> {humanize(event.action)}
              {event.reason ? ` — ${event.reason}` : ""}
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}
