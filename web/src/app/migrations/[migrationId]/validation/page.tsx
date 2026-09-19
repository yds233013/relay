import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { Money } from "@/components/money";
import { StatusChip } from "@/components/status-chip";
import { RunContext } from "@/components/run-context";
import { Callout, PageHeader, Panel, ProvenanceBadge, Section } from "@/components/ui";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ValidationPage(
  props: PageProps<"/migrations/[migrationId]/validation">,
) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const base = `/migrations/${migrationId}`;
  const readiness = await apiGet<Schemas["ReadinessOut"]>(
    `/api/v1/migrations/${migrationId}/readiness`,
  );
  const runId = param(search.run) ?? readiness.run_id;
  if (!runId) {
    return <PageHeader title="Accounting checks" description="No successful run yet." />;
  }
  const rule = param(search.rule);
  const cursor = param(search.cursor);
  const [rules, exceptions] = await Promise.all([
    apiGet<Schemas["RuleRunOut"][]>(`/api/v1/pipeline-runs/${runId}/rules`),
    apiGet<Schemas["Page_ExceptionOut_"]>(`/api/v1/pipeline-runs/${runId}/exceptions`, {
      rule_id: rule,
      cursor,
      limit: 100,
    }),
  ]);
  const errored = rules.filter((r) => r.status === "errored");
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Accounting checks"
        description="Every rule the engine ran, and the findings it produced."
        status={
          <RunContext
            base={base}
            runId={String(runId)}
            sequence={readiness.run_sequence}
            isCurrent={readiness.run_is_current}
          />
        }
      />
      <Section
        title="Rules"
        description="A rule that errored produced no verdict. It fails readiness rather than passing quietly."
        actions={<ProvenanceBadge kind="derived" />}
      >
        {errored.length > 0 ? (
          <div className="mb-3">
            <Callout tone="critical" title={`${errored.length} rules errored on this run`}>
              An errored rule is not a passing rule: its findings are unknown until it runs clean.
            </Callout>
          </div>
        ) : null}
        <Panel className="p-3">
          <DataTable<Schemas["RuleRunOut"]>
            caption={`${rules.length} rules`}
            rows={rules}
            rowKey={(r) => r.rule_id}
            empty="This run evaluated no rules."
            columns={[
              {
                header: "Rule",
                cell: (r) => (
                  <span className="font-mono text-xs whitespace-nowrap text-[var(--ink)]">
                    {r.rule_id}
                  </span>
                ),
              },
              {
                header: "Title",
                cell: (r) => <span className="text-[var(--ink)]">{r.title}</span>,
              },
              {
                header: "Status",
                cell: (r) => (
                  <>
                    <StatusChip status={r.status} label={r.status.replace("_", " ")} />
                    {r.error ? (
                      <p className="mt-1 max-w-md rounded border border-[var(--critical)]/30 bg-[var(--critical-soft)] px-2 py-1 text-xs text-[var(--critical)]">
                        {r.error}
                      </p>
                    ) : null}
                  </>
                ),
              },
              {
                header: "Findings",
                align: "right",
                cell: (r) =>
                  r.exception_count > 0 ? (
                    <Link
                      href={buildPath(`${base}/validation`, { run: runId, rule: r.rule_id })}
                      className="font-medium tabular-nums"
                      aria-current={r.rule_id === rule ? "true" : undefined}
                    >
                      {r.exception_count}
                    </Link>
                  ) : (
                    <span className="tabular-nums text-[var(--ink-subtle)]">0</span>
                  ),
              },
            ]}
          />
        </Panel>
      </Section>
      <Section
        title={rule ? `Findings for ${rule}` : "All findings"}
        description={
          rule
            ? "One rule's findings on this run. Each links to the issue that tracks it across runs."
            : "Every finding of this run. Each links to the issue that tracks it across runs."
        }
      >
        <Panel className="p-3">
          <DataTable<Schemas["ExceptionOut"]>
            caption={`${exceptions.items.length} findings on this page`}
            rows={exceptions.items}
            rowKey={(e) => e.id}
            empty="No findings on this run."
            nextHref={
              exceptions.next_cursor
                ? buildPath(`${base}/validation`, {
                    run: runId,
                    rule,
                    cursor: exceptions.next_cursor,
                  })
                : null
            }
            columns={[
              { header: "Severity", cell: (e) => <StatusChip status={e.severity} /> },
              {
                header: "Rule",
                cell: (e) => (
                  <span className="font-mono text-xs whitespace-nowrap text-[var(--ink-muted)]">
                    {e.rule_id}
                  </span>
                ),
              },
              {
                header: "Message",
                cell: (e) => <span className="text-[var(--ink)]">{e.message}</span>,
              },
              {
                header: "Amount at risk",
                align: "right",
                cell: (e) => <Money value={e.amount_at_risk} currency={e.currency} />,
              },
              {
                header: "Issue",
                cell: (e) => (
                  <Link
                    href={buildPath(`${base}/issues`, { fingerprint: e.fingerprint })}
                    className="whitespace-nowrap"
                  >
                    Open issue
                  </Link>
                ),
              },
            ]}
          />
        </Panel>
      </Section>
    </div>
  );
}
