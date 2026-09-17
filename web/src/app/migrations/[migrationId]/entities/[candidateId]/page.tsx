import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeEntityDecision } from "../../workflow-actions";

export const dynamic = "force-dynamic";

const FIELDS = ["name", "address_line1", "city", "region", "postal_code", "country", "email",
  "tax_id_last4", "default_currency", "payment_terms_days", "is_active", "created_on"] as const; // prettier-ignore

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

export default async function CandidatePage(
  props: PageProps<"/migrations/[migrationId]/entities/[candidateId]">,
) {
  const { migrationId, candidateId } = await props.params;
  const query = await props.searchParams;
  const detail = await apiGet<Schemas["CandidateDetailOut"]>(
    `/api/v1/entity-candidates/${candidateId}`,
  );
  const candidate = detail.candidate;
  const codes = [candidate.left_code, candidate.right_code];
  const partyKeys = codes.map((code) => `party:${candidate.party_type}:${code}`);
  const issues = await apiGet<Schemas["Page_IssueOut_"]>(
    `/api/v1/migrations/${migrationId}/issues`,
    { status: "open", limit: 500 },
  );
  const related = issues.items.filter((i) => i.subjects.some((s) => partyKeys.includes(s)));
  const active = detail.decisions.filter((d) => d.status === "active");
  return (
    <div className="max-w-6xl">
      <PageHeader
        title={`${humanize(candidate.party_type)} ${candidate.left_code} and ${candidate.right_code}`}
        description={
          <>
            Score {candidate.score} ({candidate.strong ? "strong" : "possible"}) ·{" "}
            <Link href={`/migrations/${migrationId}/entities`} className="underline">
              all candidates
            </Link>
          </>
        }
      >
        <StatusChip status={candidate.status} />
      </PageHeader>
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section title="Parties">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm" data-testid="parties">
            <caption className="sr-only">The two parties side by side</caption>
            <thead>
              <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
                <th scope="col" className="px-2 py-1.5">
                  Field
                </th>
                {detail.parties.map((party) => (
                  <th key={party.code} scope="col" className="px-2 py-1.5">
                    {party.code}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FIELDS.map((field) => (
                <tr key={field} className="border-b border-gray-100">
                  <th scope="row" className="px-2 py-1 font-normal text-gray-700">
                    {humanize(field)}
                  </th>
                  {detail.parties.map((party) => (
                    <td key={party.code} className="px-2 py-1">
                      {show(party.data[field])}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th scope="row" className="px-2 py-1 font-normal text-gray-700">
                  Documents in run
                </th>
                {detail.parties.map((party) => (
                  <td key={party.code} className="px-2 py-1 tabular-nums">
                    {party.open_documents}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Features">
        <pre className="overflow-x-auto rounded bg-gray-50 p-2 text-xs">
          {JSON.stringify(candidate.features, null, 2)}
        </pre>
      </Section>
      <Section title="Open issues naming these parties">
        {related.length === 0 ? (
          <p className="text-sm text-gray-700">None.</p>
        ) : (
          <ul className="list-inside list-disc text-sm">
            {related.map((i) => (
              <li key={i.id}>
                <Link href={`/migrations/${migrationId}/issues/${i.id}`} className="underline">
                  {i.key}: {i.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Decision">
        {active.length > 0 ? (
          <p className="text-sm" data-testid="active-decision">
            Active decision:{" "}
            {active.map((d) => `${humanize(d.decision)} (${d.members.join(", ")})`).join("; ")}.
            Revert it on the Overrides page before deciding again.
          </p>
        ) : (
          <form action={proposeEntityDecision} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <input type="hidden" name="runId" value={detail.run_id} />
            <input type="hidden" name="partyType" value={candidate.party_type} />
            <input
              type="hidden"
              name="returnTo"
              value={`/migrations/${migrationId}/entities/${candidateId}`}
            />
            {codes.map((code) => (
              <input key={code} type="hidden" name="member" value={code} />
            ))}
            {related.map((i) => (
              <input key={i.id} type="hidden" name="evidenceIssueId" value={i.id} />
            ))}
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="text-xs font-medium text-gray-700">These parties are</legend>
              <label className="flex items-center gap-2">
                <input type="radio" name="decision" value="same_entity" defaultChecked /> the same
                entity
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="decision" value="distinct" /> distinct entities
              </label>
            </fieldset>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-gray-700">
                Surviving record (same entity only)
              </span>
              <select name="survivor" className="rounded border border-gray-400 bg-white px-2 py-1">
                {codes.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <TextArea name="justification" label="Justification and evidence" required />
            <span>
              <SubmitButton>Propose decision</SubmitButton>
            </span>
          </form>
        )}
      </Section>
    </div>
  );
}
