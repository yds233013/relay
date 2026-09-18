import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ButtonLink, EmptyState, MetricCard, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

/** Days to go-live is the only countdown on this page; near and past due read differently. */
function GoLiveCountdown({ days }: { days: number }) {
  const tone =
    days < 0
      ? "text-[var(--critical)]"
      : days <= 14
        ? "text-[var(--warning)]"
        : "text-[var(--ink)]";
  const suffix = days < 0 ? "days past" : days === 1 ? "day left" : "days left";
  return (
    <>
      {/* No Math.* anywhere in the web app (FC-15 guard): negate rather than call abs. */}
      <span className={`font-medium tabular-nums ${tone}`}>{days < 0 ? -days : days}</span>{" "}
      <span className="text-xs text-[var(--ink-subtle)]">{suffix}</span>
    </>
  );
}

export default async function PortfolioPage() {
  const migrations = await apiGet<Schemas["MigrationSummaryOut"][]>("/api/v1/migrations");
  const ready = migrations.filter((m) => m.overall === "ready").length;
  const stale = migrations.filter((m) => m.overall === "stale").length;
  const blocked = migrations.length - ready - stale;

  return (
    <main className="mx-auto max-w-6xl p-5">
      <PageHeader
        title="Portfolio"
        description="Every migration Relay is running. Readiness is the verdict of each migration's latest run; stale means the inputs changed after that run and nothing has been re-evaluated since."
      >
        <ButtonLink href="/migrations/new" variant="primary">
          New migration
        </ButtonLink>
      </PageHeader>

      {migrations.length === 0 ? (
        <EmptyState
          title="No migrations yet"
          hint="A migration holds the source systems, datasets, runs and governed changes for one company's cutover. Start one to load its first export."
        />
      ) : (
        <>
          <dl className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <MetricCard
              label="Migrations"
              value={migrations.length}
              hint="Tracked end to end, from first import to sign-off"
            />
            <MetricCard
              label="Not ready"
              value={blocked}
              hint="At least one readiness gate is failing"
              tone={blocked > 0 ? "critical" : "neutral"}
            />
            <MetricCard
              label="Results stale"
              value={stale}
              hint="Inputs changed; re-run to evaluate"
              tone={stale > 0 ? "warning" : "neutral"}
            />
          </dl>

          <Section
            title="Migrations"
            description="Exposure is the unresolved amount at risk on the latest run, counted once per amount."
          >
            <Panel className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">Migrations</caption>
                <thead>
                  <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Migration
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Readiness
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Failing gates
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Unresolved exposure
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Go-live
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Days to go-live
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {migrations.map((m) => (
                    <tr
                      key={m.id}
                      className="border-b border-[var(--border)]/60 last:border-0 hover:bg-[var(--surface-sunken)]"
                    >
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <Link href={`/migrations/${m.id}`} className="font-medium">
                          {m.company_name}
                        </Link>
                        <span className="block text-xs text-[var(--ink-subtle)]">{m.name}</span>
                      </th>
                      <td className="px-3 py-2">
                        <StatusChip status={m.overall} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {m.failing_gate_count === null ? (
                          <span className="text-[var(--ink-subtle)]">—</span>
                        ) : m.failing_gate_count === 0 ? (
                          <span className="text-[var(--ink-subtle)]">
                            0 of {m.gate_count ?? "—"}
                          </span>
                        ) : (
                          <>
                            <span className="font-medium text-[var(--critical)]">
                              {m.failing_gate_count}
                            </span>
                            <span className="text-[var(--ink-subtle)]">
                              {" "}
                              of {m.gate_count ?? "—"}
                            </span>
                          </>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        <Money value={m.unresolved_exposure} currency={m.functional_currency} />
                      </td>
                      <td className="px-3 py-2 text-[var(--ink-muted)]">
                        <BusinessDate value={m.go_live_date} />
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <GoLiveCountdown days={m.days_to_go_live} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </Section>
        </>
      )}
    </main>
  );
}
