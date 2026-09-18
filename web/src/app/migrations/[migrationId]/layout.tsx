import { BusinessDate } from "@/components/dates";
import { MigrationNav } from "@/components/migration-nav";
import { apiGet, type Schemas } from "@/lib/api/client";

export default async function MigrationLayout(props: LayoutProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const migration = await apiGet<Schemas["MigrationOut"]>(`/api/v1/migrations/${migrationId}`);
  return (
    <div className="flex min-h-[calc(100vh-41px)]">
      <div className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--surface-sunken)] p-3">
        <div className="mb-4 px-2">
          <p className="text-sm font-semibold leading-tight text-[var(--ink)]">
            {migration.company_name}
          </p>
          <p className="text-xs text-[var(--ink-muted)]">{migration.name}</p>
          <dl className="mt-2 space-y-0.5 text-[11px] text-[var(--ink-subtle)]">
            <div className="flex justify-between gap-2">
              <dt>Cutover</dt>
              <dd className="tabular-nums">
                <BusinessDate value={migration.cutover_date} />
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Go-live</dt>
              <dd className="tabular-nums">
                <BusinessDate value={migration.go_live_date} />
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Books</dt>
              <dd>{migration.functional_currency}</dd>
            </div>
          </dl>
        </div>
        <MigrationNav migrationId={migrationId} />
      </div>
      <main className="min-w-0 flex-1 bg-[var(--surface)] p-5">{props.children}</main>
    </div>
  );
}
