import { BUTTON_STYLES, Callout, EmptyState, PageHeader, Panel } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { selectUser } from "./actions";

export const dynamic = "force-dynamic";

/** What each role is allowed to do, so the switch is a deliberate choice rather than a name pick. */
const ROLE_HINT: Record<string, string> = {
  implementation_specialist: "Uploads exports, proposes mappings and fixes, requests runs",
  implementation_lead: "Everything a specialist may do, plus reviewing change requests",
  customer_controller: "Reviews the accounting: approves change requests, works issues",
  admin: "Manages the workspace; cannot approve accounting changes",
  viewer: "Read-only: evidence, audit log and readiness",
};

export default async function SelectUserPage(props: PageProps<"/select-user">) {
  const returnTo = param((await props.searchParams).returnTo) ?? "/migrations";
  const users = await apiGet<Schemas["UserOut"][]>("/api/v1/dev/users");
  return (
    <main className="mx-auto max-w-xl p-6">
      <PageHeader
        title="Choose a user"
        description="Relay checks what the acting person is allowed to do — who may propose a change and who may approve it. Pick the person you want to act as."
      />
      <Callout tone="warning" title="Not authentication">
        Development identity for local use only. Roles decide what each person may do.
      </Callout>
      {users.length === 0 ? (
        <div className="mt-4">
          <EmptyState title="No users exist yet" hint="Run `make demo-seed` to load the demo." />
        </div>
      ) : (
        <Panel className="mt-4 divide-y divide-[var(--border)]">
          {users.map((user) => (
            <form
              key={user.id}
              action={selectUser}
              className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5"
            >
              <input type="hidden" name="email" value={user.email} />
              <input type="hidden" name="returnTo" value={returnTo} />
              <span className="min-w-0 text-sm">
                <span className="font-medium text-[var(--ink)]">{user.display_name}</span>
                <span className="block text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
                  {humanize(user.role)}
                </span>
                <span className="block text-xs text-[var(--ink-muted)]">
                  {ROLE_HINT[user.role] ?? user.email}
                </span>
              </span>
              <button
                type="submit"
                className={BUTTON_STYLES.secondary}
                aria-label={`Act as ${user.display_name}`}
              >
                Act as
              </button>
            </form>
          ))}
        </Panel>
      )}
    </main>
  );
}
