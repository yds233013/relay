import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import {
  BUTTON_STYLES,
  ButtonLink,
  Callout,
  EmptyState,
  MetricCard,
  Panel,
  Section,
} from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

type Summary = Schemas["MigrationSummaryOut"];

/**
 * The portfolio payload reports `stale` both for an implementation whose inputs moved after its
 * last run and for one that has never produced a verdict at all. Only the second has no stored
 * gates, so the absence of a gate count — not a separate field — is what tells them apart.
 */
function isUnverified(migration: Summary): boolean {
  return migration.gate_count === null;
}

/** Days to go-live is the only countdown on this page; near and past due read differently. */
function GoLiveCountdown({ days }: { days: number }) {
  const tone =
    days < 0
      ? "text-[var(--critical)]"
      : days <= 14
        ? "text-[var(--warning)]"
        : "text-[var(--ink)]";
  const suffix = days < 0 ? "days past target" : days === 1 ? "day left" : "days left";
  return (
    <>
      {/* No Math.* anywhere in the web app (FC-15 guard): negate rather than call abs. */}
      <span className={`font-medium tabular-nums ${tone}`}>{days < 0 ? -days : days}</span>{" "}
      <span className="text-xs text-[var(--ink-subtle)]">{suffix}</span>
    </>
  );
}

/** The verdict of the latest run, or the honest absence of one. */
function ReadinessCell({ migration }: { migration: Summary }) {
  if (isUnverified(migration)) {
    return (
      <>
        <StatusChip status="not_verified" label="not yet verified" />
        <span className="mt-1 block text-xs text-[var(--ink-subtle)]">No run has completed</span>
      </>
    );
  }
  return (
    <>
      <StatusChip status={migration.overall} />
      {migration.overall === "stale" ? (
        <span className="mt-1 block text-xs text-[var(--ink-subtle)]">
          Inputs changed; re-run to evaluate
        </span>
      ) : null}
    </>
  );
}

/** Failing gates out of the gates the latest run evaluated. */
function GatesCell({ migration }: { migration: Summary }) {
  if (migration.failing_gate_count === null) {
    return <span className="text-[var(--ink-subtle)]">—</span>;
  }
  if (migration.failing_gate_count === 0) {
    return <span className="text-[var(--ink-subtle)]">0 of {migration.gate_count ?? "—"}</span>;
  }
  return (
    <>
      <span className="font-medium text-[var(--critical)]">{migration.failing_gate_count}</span>
      <span className="text-[var(--ink-subtle)]"> of {migration.gate_count ?? "—"}</span>
    </>
  );
}

export default async function PortfolioPage() {
  const migrations = await apiGet<Summary[]>("/api/v1/migrations");
  const ready = migrations.filter((m) => m.overall === "ready").length;
  const blocked = migrations.filter((m) => m.overall === "not_ready").length;
  const stale = migrations.filter((m) => m.overall === "stale").length;

  // Amounts are never combined in the browser (FC-15), and the API reports exposure per
  // implementation only — so the portfolio states which currency the column speaks, not a total.
  const currencies = Array.from(new Set(migrations.map((m) => m.functional_currency))).sort();
  const singleCurrency = currencies.length === 1 ? currencies[0] : null;

  const attention = [
    blocked > 0 ? `${blocked} blocked by failing readiness gates` : null,
    stale > 0 ? `${stale} waiting on a run` : null,
  ].filter((phrase) => phrase !== null);

  return (
    <main className="mx-auto max-w-6xl p-5">
      <PageHeader
        title="Implementation command center"
        description="Every ERP implementation Relay is running, tracked from legacy data to verified go-live. Readiness is the verdict of each implementation's latest run; stale means the inputs changed after that run and nothing has been re-evaluated since."
        status={
          migrations.length > 0 && attention.length === 0 ? (
            <StatusChip status="ready" label="all implementations ready" />
          ) : null
        }
      >
        <ButtonLink href="/migrations/new" variant="primary">
          New migration
        </ButtonLink>
      </PageHeader>

      {migrations.length === 0 ? (
        <EmptyState
          title="No implementations yet"
          hint="Each implementation tracked here holds one company's cutover — its legacy exports, column and account mappings, runs, governed changes and readiness gates — and shows whether that company can go live. Start the first one with “New migration” above."
        />
      ) : (
        <>
          <dl className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Implementations"
              value={migrations.length}
              hint="Tracked end to end, from first import to sign-off"
            />
            <MetricCard
              label="Ready for go-live"
              value={ready}
              hint="Every readiness gate passing on the current inputs"
              tone={ready > 0 ? "positive" : "neutral"}
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
              hint="Inputs changed since the last run, or no run yet"
              tone={stale > 0 ? "warning" : "neutral"}
            />
          </dl>

          {attention.length > 0 ? (
            <div className="mb-5">
              <Callout tone={blocked > 0 ? "critical" : "warning"} title="Needs attention today">
                {attention.join(" · ")}. Open an implementation to see which gates fail, the
                exposure behind them and the evidence for every number.
              </Callout>
            </div>
          ) : null}

          <Section
            title="Implementations"
            description={
              singleCurrency === null
                ? "Unresolved exposure is the amount at risk on each implementation's latest run, counted once per amount. These books are kept in different currencies, so exposure is shown per implementation and never combined."
                : `Unresolved exposure is the amount at risk on each implementation's latest run, counted once per amount. Every implementation here keeps its books in ${singleCurrency}; Relay still reports exposure per implementation rather than one portfolio total.`
            }
          >
            <Panel className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">
                  Implementations, with readiness, failing gates, unresolved exposure and go-live
                </caption>
                <thead>
                  <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Implementation
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
                    <th scope="col" className="px-3 py-2 font-medium">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {migrations.map((m) => (
                    <tr
                      key={m.id}
                      className="border-b border-[var(--border)]/60 align-top last:border-0 hover:bg-[var(--surface-sunken)]"
                    >
                      <th scope="row" className="px-3 py-3 text-left font-normal">
                        <Link href={`/migrations/${m.id}`} className="font-medium">
                          {m.company_name}
                        </Link>
                        <span className="block text-xs text-[var(--ink-subtle)]">{m.name}</span>
                        <span className="mt-1 block text-xs text-[var(--ink-subtle)]">
                          {humanize(m.status)} · books in {m.functional_currency} · cutover{" "}
                          <BusinessDate value={m.cutover_date} />
                        </span>
                      </th>
                      <td className="px-3 py-3">
                        <ReadinessCell migration={m} />
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        <GatesCell migration={m} />
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        <Money value={m.unresolved_exposure} currency={m.functional_currency} />
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-[var(--ink-muted)]">
                        <BusinessDate value={m.go_live_date} />
                        <span className="mt-1 block">
                          <GoLiveCountdown days={m.days_to_go_live} />
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right">
                        <Link
                          href={`/migrations/${m.id}`}
                          aria-label={`Open implementation: ${m.company_name}`}
                          className={`${BUTTON_STYLES.secondary} no-underline whitespace-nowrap`}
                        >
                          Open implementation
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            {migrations.length === 1 && migrations[0] !== undefined ? (
              <p className="mt-2 text-xs text-[var(--ink-subtle)]">
                {migrations[0].company_name} is the only implementation in this workspace — nothing
                here is filtered or hidden. Every implementation started with “New migration” joins
                this table with the same readiness verdict, exposure and go-live countdown.
              </p>
            ) : null}
          </Section>
        </>
      )}
    </main>
  );
}
