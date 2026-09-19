import Link from "next/link";

import { FilterForm, SelectFilter } from "@/components/filters";
import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, Panel } from "@/components/ui";
import { SignalChips } from "@/components/signal-chips";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeAccountMapping } from "../governance-actions";

export const dynamic = "force-dynamic";

type Row = Schemas["AccountMappingRowOut"];

function doubtful(row: Row): boolean {
  const signals = row.signals;
  return (
    row.target_account_code === null ||
    row.proposal !== null ||
    (signals !== null &&
      (!signals.target_exists ||
        signals.type_compatible === false ||
        signals.subtype_compatible === false))
  );
}

export default async function MappingsPage(props: PageProps<"/migrations/[migrationId]/mappings">) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const show = param(query.show) ?? "doubtful";
  const [mapping, datasets] = await Promise.all([
    apiGet<Schemas["AccountMappingOverviewOut"]>(
      `/api/v1/migrations/${migrationId}/account-mapping`,
    ),
    apiGet<Schemas["DatasetOut"][]>(`/api/v1/migrations/${migrationId}/datasets`),
  ]);
  const rows = show === "all" ? mapping.rows : mapping.rows.filter(doubtful);
  const pending = mapping.sets.filter((s) => s.status === "pending_approval");
  // Arriving from the work queue: the account that decision is about, so the row is unmistakable.
  const focus = param(query.account);
  const focused = focus ? mapping.rows.find((r) => r.legacy_account_code === focus) : undefined;
  return (
    <div className="max-w-7xl">
      <PageHeader
        title="Mappings"
        description="Account and column mappings. Changes take effect only through approved change requests."
      />
      <Notice error={param(query.error)} notice={param(query.notice)} />
      {focused ? (
        <div className="mb-4">
          <Callout
            tone="critical"
            title={`Reviewing legacy account ${focused.legacy_account_code}`}
          >
            {focused.legacy_name ?? "This account"}
            {focused.legacy_subtype
              ? ` is a ${humanize(focused.legacy_subtype).toLowerCase()}`
              : ""}
            {focused.target_account_code
              ? ` currently mapped to ${focused.target_account_code} ${focused.target_name ?? ""}`
              : " and is not mapped to any target account"}
            . Enter the account it should map to in the row below, say why, and propose the change —
            nothing moves until the implementation lead and the customer controller both approve.
            {focused.proposal ? (
              <>
                {" "}
                Relay suggests{" "}
                <span className="font-mono font-medium text-[var(--ink)]">
                  {focused.proposal.target}
                </span>{" "}
                ({humanize(focused.proposal.basis).toLowerCase()}), which you are free to overrule.
              </>
            ) : null}
          </Callout>
        </div>
      ) : null}
      <Section
        title="Account mapping"
        description="Every legacy account and where it lands in the new chart of accounts. Type and subtype compatibility is checked for each pair."
      >
        <p className="mb-2 text-sm">
          In effect:{" "}
          {mapping.approved_set
            ? `approved version ${mapping.approved_set.version} (${mapping.approved_set.entry_count} accounts)`
            : "the account mapping file (not yet approved; gate G3 fails until it is)"}
          .
          {pending.map((s) => (
            <span key={s.id}>
              {" "}
              Version {s.version} is{" "}
              {s.change_request_id ? (
                <Link
                  href={`/migrations/${migrationId}/change-requests/${s.change_request_id}`}
                  className="underline"
                >
                  waiting for approval
                </Link>
              ) : (
                "waiting for approval"
              )}
              .
            </span>
          ))}
        </p>
        <FilterForm>
          <SelectFilter
            name="show"
            label="Accounts"
            value={show}
            options={[
              ["doubtful", "Needing attention"],
              ["all", "All accounts"],
            ]}
          />
        </FilterForm>
        <form action={proposeAccountMapping}>
          <input type="hidden" name="migrationId" value={migrationId} />
          <input type="hidden" name="base" value={mapping.approved_set ? "approved" : "import"} />
          <Panel className="overflow-x-auto p-3">
            <table
              className="w-full border-collapse text-left text-sm"
              data-testid="account-mapping"
            >
              <caption className="mb-2 text-left text-sm text-[var(--ink-muted)]">
                Showing <span className="font-semibold text-[var(--ink)]">{rows.length}</span> of{" "}
                {mapping.rows.length} legacy accounts
                {show === "doubtful" ? " that need attention" : ""}
              </caption>
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--surface-sunken)] text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                  <th scope="col" className="px-2 py-1.5">
                    Legacy account
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Current target
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Compatibility
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Suggestion
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    New target
                  </th>
                  <th scope="col" className="px-2 py-1.5">
                    Rationale
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.legacy_account_code}
                    id={`account-${row.legacy_account_code}`}
                    className={`border-b border-[var(--border)]/60 align-top last:border-0 ${
                      row.legacy_account_code === focus
                        ? "bg-[var(--critical-soft)] shadow-[inset_3px_0_0_var(--critical)]"
                        : ""
                    }`}
                    data-legacy={row.legacy_account_code}
                  >
                    <td className="px-2 py-1.5">
                      <span className="font-mono">{row.legacy_account_code}</span>{" "}
                      {row.legacy_name ?? "not in legacy chart"}
                      <span className="block text-xs text-[var(--ink-subtle)]">
                        {row.legacy_subtype ? humanize(row.legacy_subtype) : ""}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className="font-mono">{row.target_account_code ?? "unmapped"}</span>{" "}
                      {row.target_name ?? ""}
                      <span className="block text-xs text-[var(--ink-subtle)]">
                        {row.target_subtype ? humanize(row.target_subtype) : ""}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <SignalChips signals={row.signals} />
                    </td>
                    <td className="px-2 py-1.5">
                      {row.proposal ? (
                        <>
                          <span className="font-mono">{row.proposal.target}</span>{" "}
                          <span className="text-xs text-[var(--ink-muted)]">
                            {humanize(row.proposal.basis)}
                            {row.proposal.score ? ` ${row.proposal.score}` : ""}
                          </span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <label className="sr-only" htmlFor={`target-${row.legacy_account_code}`}>
                        New target for {row.legacy_account_code}
                      </label>
                      <input
                        id={`target-${row.legacy_account_code}`}
                        name={`target:${row.legacy_account_code}`}
                        placeholder={row.proposal?.target ?? ""}
                        className="w-24 rounded border border-[var(--border-strong)] px-2 py-1 font-mono"
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <label className="sr-only" htmlFor={`rationale-${row.legacy_account_code}`}>
                        Rationale for {row.legacy_account_code}
                      </label>
                      <input
                        id={`rationale-${row.legacy_account_code}`}
                        name={`rationale:${row.legacy_account_code}`}
                        className="w-56 rounded border border-[var(--border-strong)] px-2 py-1"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <div className="mt-4 max-w-2xl rounded-md border border-[var(--border)] bg-[var(--surface-sunken)] p-3">
            <p className="mb-2 text-sm font-medium text-[var(--ink)]">
              Propose a change to this mapping
            </p>
            <p className="mb-2 text-xs text-[var(--ink-muted)]">
              Fill in a new target above for the accounts you are changing. Nothing moves until the
              implementation lead and the customer controller both approve.
            </p>
            <div className="flex flex-col gap-2">
              <TextField
                name="title"
                label="Title"
                required
                defaultValue="Account mapping change"
              />
              <TextArea name="justification" label="Justification" required />
              <span>
                <SubmitButton>Propose mapping change</SubmitButton>
              </span>
            </div>
          </div>
        </form>
      </Section>
      <Section
        title="Column mappings"
        description="How each export's columns are read into canonical fields. One approved set per dataset."
      >
        <ul className="list-inside list-disc text-sm">
          {datasets.map((dataset) => (
            <li key={dataset.id}>
              <Link
                href={`/migrations/${migrationId}/mappings/columns/${dataset.id}`}
                className="underline"
              >
                {dataset.name}
              </Link>{" "}
              <span className="text-[var(--ink-muted)]">({humanize(dataset.dataset_type)})</span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Account mapping versions">
        <ul className="space-y-1 text-sm">
          {mapping.sets.map((s) => (
            <li key={s.id} className="flex items-center gap-2">
              Version {s.version} <StatusChip status={s.status} /> {s.entry_count} accounts
              {s.change_request_id ? (
                <Link
                  href={`/migrations/${migrationId}/change-requests/${s.change_request_id}`}
                  className="underline"
                >
                  change request
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
