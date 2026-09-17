import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { PageHeader } from "@/components/page-header";
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
  const overrides = await apiGet<Schemas["RecordOverrideOut"][]>(
    `/api/v1/migrations/${migrationId}/record-overrides`,
  );
  return (
    <div className="max-w-7xl">
      <PageHeader
        title="Overrides"
        description="Approved corrections applied on top of immutable source rows. Reverting one is another change request."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm" data-testid="overrides">
          <caption className="mb-2 text-left text-sm font-semibold text-gray-900">
            {overrides.length} overrides
          </caption>
          <thead>
            <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
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
              <tr key={o.id} className="border-b border-gray-100 align-top">
                <td className="px-2 py-1.5">
                  <span className="font-mono text-xs">{o.natural_key}</span>
                  <span className="block text-xs text-gray-700">
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
                      <input type="hidden" name="overrideId" value={o.id} />
                      <input type="hidden" name="naturalKey" value={o.natural_key} />
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
    </div>
  );
}
