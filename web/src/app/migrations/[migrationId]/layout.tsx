import { BusinessDate } from "@/components/dates";
import { MigrationNav } from "@/components/migration-nav";
import { apiGet, type Schemas } from "@/lib/api/client";

/**
 * The implementation workspace: who this is for on the left, what you are doing to the right.
 *
 * The rail keeps the implementation's identity and its two fixed dates on screen at all times,
 * because every judgement made in here — whether a difference matters, whether a waiver is
 * defensible — is made against a cutover and a go-live that are already set.
 *
 * Below `lg` the rail becomes a band above the workspace rather than a drawer: an operator on a
 * narrow screen still needs the dates, and a queue of fourteen destinations is easier to reach as
 * wrapped pills than behind a toggle.
 */
export default async function MigrationLayout(props: LayoutProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const migration = await apiGet<Schemas["MigrationOut"]>(`/api/v1/migrations/${migrationId}`);
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <div className="w-full shrink-0 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 lg:w-60 lg:border-b-0 lg:border-r lg:py-3">
        <div className="mb-2.5 px-2.5 lg:mb-5">
          <p className="text-sm font-semibold leading-tight tracking-tight text-[var(--ink)]">
            {migration.company_name}
          </p>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">{migration.name}</p>
          <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-[var(--ink-subtle)] lg:block lg:space-y-1">
            <div className="flex gap-2 lg:justify-between">
              <dt>Cutover</dt>
              <dd className="tabular-nums text-[var(--ink-muted)]">
                <BusinessDate value={migration.cutover_date} />
              </dd>
            </div>
            <div className="flex gap-2 lg:justify-between">
              <dt>Go-live</dt>
              <dd className="tabular-nums text-[var(--ink-muted)]">
                <BusinessDate value={migration.go_live_date} />
              </dd>
            </div>
            <div className="flex gap-2 lg:justify-between">
              <dt>Books</dt>
              <dd className="text-[var(--ink-muted)]">{migration.functional_currency}</dd>
            </div>
          </dl>
        </div>
        <MigrationNav migrationId={migrationId} />
      </div>
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6">
        <div className="mx-auto w-full max-w-[1440px]">{props.children}</div>
      </main>
    </div>
  );
}
