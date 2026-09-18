import Link from "next/link";

import { SubmitButton, TextArea } from "@/components/forms";
import { Notice } from "@/components/notice";
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
  // The comparison is the evidence: say which fields actually disagree rather than making the
  // reader diff two columns by eye.
  const differs = (field: string) =>
    new Set(detail.parties.map((party) => show(party.data[field]))).size > 1;
  const differing = FIELDS.filter((field) => differs(field));
  return (
    <div className="max-w-6xl">
      <PageHeader
        title={`${humanize(candidate.party_type)} ${candidate.left_code} and ${candidate.right_code}`}
        breadcrumbs={[
          { label: "Entities", href: `/migrations/${migrationId}/entities` },
          { label: `${candidate.left_code} and ${candidate.right_code}` },
        ]}
        status={<StatusChip status={candidate.status} />}
        description="Two records the matcher believes may name one party. They are merged only by an approved decision."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Panel className="mb-6 p-3">
        <MetaList
          columns={3}
          items={[
            {
              label: "Match score",
              value: <span className="tabular-nums font-medium">{candidate.score}</span>,
            },
            {
              label: "Strength",
              value: candidate.strong ? (
                <span className="text-[var(--warning)]">strong — blocks gate G10</span>
              ) : (
                <span className="text-[var(--ink-muted)]">possible — does not block G10</span>
              ),
            },
            {
              label: "Fields that differ",
              value: (
                <span className="tabular-nums">
                  {differing.length} of {FIELDS.length}
                </span>
              ),
            },
          ]}
        />
      </Panel>
      <Section
        title="Parties"
        description="Identical values are muted; the fields marked differ are the ones to judge."
        actions={<ProvenanceBadge kind="canonical" />}
      >
        <Panel className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm" data-testid="parties">
            <caption className="sr-only">The two parties side by side</caption>
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                <th scope="col" className="px-3 py-2 font-medium">
                  Field
                </th>
                {detail.parties.map((party) => (
                  <th key={party.code} scope="col" className="px-3 py-2 font-medium">
                    {party.code}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FIELDS.map((field) => {
                const different = differs(field);
                return (
                  <tr
                    key={field}
                    className={`border-b border-[var(--border)]/60 ${
                      different ? "bg-[var(--warning-soft)]" : ""
                    }`}
                  >
                    <th
                      scope="row"
                      className="whitespace-nowrap px-3 py-1.5 text-left font-normal text-[var(--ink-muted)]"
                    >
                      {humanize(field)}
                      {different ? (
                        <span className="ml-2 rounded border border-[var(--warning)]/40 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--warning)]">
                          differs
                        </span>
                      ) : null}
                    </th>
                    {detail.parties.map((party) => (
                      <td
                        key={party.code}
                        className={`px-3 py-1.5 ${
                          different ? "font-medium text-[var(--ink)]" : "text-[var(--ink-subtle)]"
                        }`}
                      >
                        {show(party.data[field])}
                      </td>
                    ))}
                  </tr>
                );
              })}
              <tr className="border-t border-[var(--border)]">
                <th
                  scope="row"
                  className="whitespace-nowrap px-3 py-1.5 text-left font-normal text-[var(--ink-muted)]"
                >
                  Documents in run
                </th>
                {detail.parties.map((party) => (
                  <td key={party.code} className="px-3 py-1.5 tabular-nums text-[var(--ink)]">
                    {party.open_documents}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </Panel>
      </Section>
      <Section title="Features">
        <details className="rounded-md border border-[var(--border)] bg-[var(--surface-raised)]">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
            Raw match features
          </summary>
          <pre className="overflow-x-auto border-t border-[var(--border)] bg-[var(--surface-sunken)] p-3 text-xs text-[var(--ink-muted)]">
            {JSON.stringify(candidate.features, null, 2)}
          </pre>
        </details>
      </Section>
      <Section title="Open issues naming these parties">
        {related.length === 0 ? (
          <EmptyState
            title="No open issue names either party."
            hint="A decision here can still be proposed on its own evidence."
          />
        ) : (
          <Panel>
            <ul className="divide-y divide-[var(--border)]">
              {related.map((i) => (
                <li key={i.id} className="px-3 py-2 text-sm">
                  <Link
                    href={`/migrations/${migrationId}/issues/${i.id}`}
                    className="font-medium whitespace-nowrap"
                  >
                    {i.key}
                  </Link>
                  <span className="text-[var(--ink-muted)]">: {i.title}</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </Section>
      <Section
        title="Decision"
        description="A decision is a governed change: it is proposed here and takes effect only once approved."
      >
        {active.length > 0 ? (
          <Callout tone="accent" title="An active decision already covers this pair">
            <p data-testid="active-decision">
              Active decision:{" "}
              {active.map((d) => `${humanize(d.decision)} (${d.members.join(", ")})`).join("; ")}.
              Revert it on the Overrides page before deciding again.
            </p>
          </Callout>
        ) : (
          <Panel className="p-4">
            <form action={proposeEntityDecision} className="flex max-w-2xl flex-col gap-4">
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
              <fieldset className="flex flex-col gap-1.5 text-sm">
                <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
                  These parties are
                </legend>
                <label className="flex items-center gap-2">
                  <input type="radio" name="decision" value="same_entity" defaultChecked /> the same
                  entity
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" name="decision" value="distinct" /> distinct entities
                </label>
              </fieldset>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-xs font-medium text-[var(--ink-muted)]">
                  Surviving record (same entity only)
                </span>
                <select
                  name="survivor"
                  className="rounded border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)] sm:max-w-xs"
                >
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
          </Panel>
        )}
      </Section>
    </div>
  );
}
