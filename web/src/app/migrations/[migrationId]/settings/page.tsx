import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { apiGet, type Schemas } from "@/lib/api/client";
import { isPublicDemo } from "@/lib/demo";
import { humanize, param } from "@/lib/format";

import { proposePolicyChange } from "../workflow-actions";

export const dynamic = "force-dynamic";

export default async function SettingsPage(props: PageProps<"/migrations/[migrationId]/settings">) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const policy = await apiGet<Schemas["PolicyOut"]>(`/api/v1/migrations/${migrationId}/policy`);
  const scalar = Object.entries(policy.policy).filter(([, value]) => typeof value !== "object");
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Policy"
        description={
          <>
            Policy version {policy.version}, since <LocalTime value={policy.created_at} />
            {policy.change_request_id ? (
              <>
                {" "}
                (
                <Link
                  href={`/migrations/${migrationId}/change-requests/${policy.change_request_id}`}
                  className="underline"
                >
                  approval
                </Link>
                )
              </>
            ) : null}
            . Changing the policy is a change request approved by the lead and the controller, and
            it invalidates any sign-off.
          </>
        }
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Policy">
        <table className="w-full border-collapse text-left text-sm" data-testid="policy">
          <caption className="sr-only">Policy values</caption>
          <thead>
            <tr className="border-b border-[var(--border)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
              <th scope="col" className="px-2 py-1.5">
                Setting
              </th>
              <th scope="col" className="px-2 py-1.5">
                Value
              </th>
            </tr>
          </thead>
          <tbody>
            {scalar.map(([key, value]) => (
              <tr key={key} className="border-b border-[var(--border)]/60">
                <th scope="row" className="px-2 py-1.5 font-normal">
                  {humanize(key)}
                </th>
                <td className="px-2 py-1.5 font-mono">{String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Propose a policy change">
        {isPublicDemo() ? (
          <DemoUnavailable what="Changing a policy threshold is a governed change request that the implementation lead and the customer controller both approve, and it invalidates any sign-off." />
        ) : (
          <form action={proposePolicyChange} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-[var(--ink-muted)]">Setting</span>
              <select
                name="key"
                className="rounded border border-[var(--border-strong)] bg-white px-2 py-1"
              >
                {scalar.map(([key]) => (
                  <option key={key} value={key}>
                    {humanize(key)}
                  </option>
                ))}
              </select>
            </label>
            <TextField name="value" label="New value" required />
            <TextArea name="justification" label="Justification" required />
            <span>
              <SubmitButton>Propose policy change</SubmitButton>
            </span>
          </form>
        )}
      </Section>
    </div>
  );
}
