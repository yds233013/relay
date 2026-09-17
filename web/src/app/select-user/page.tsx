import { apiGet, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

import { selectUser } from "./actions";

export const dynamic = "force-dynamic";

export default async function SelectUserPage(props: PageProps<"/select-user">) {
  const returnTo = param((await props.searchParams).returnTo) ?? "/migrations";
  const users = await apiGet<Schemas["UserOut"][]>("/api/v1/dev/users");
  return (
    <main className="mx-auto max-w-lg p-6">
      <h1 className="mb-1 text-lg font-semibold">Choose a user</h1>
      <p className="mb-4 text-sm text-gray-700">
        Development identity for local use only. Roles decide what each person may do.
      </p>
      {users.length === 0 ? (
        <p className="text-sm">No users exist yet. Run `make demo-seed` to load the demo.</p>
      ) : (
        <ul className="divide-y divide-gray-200 rounded border border-gray-300">
          {users.map((user) => (
            <li key={user.id}>
              <form action={selectUser} className="flex items-center justify-between gap-3 p-3">
                <input type="hidden" name="email" value={user.email} />
                <input type="hidden" name="returnTo" value={returnTo} />
                <span className="text-sm">
                  <span className="font-medium">{user.display_name}</span>
                  <span className="block text-gray-700">{user.role.replaceAll("_", " ")}</span>
                </span>
                <button
                  type="submit"
                  className="rounded border border-gray-400 px-3 py-1 text-sm font-medium hover:bg-gray-100"
                  aria-label={`Act as ${user.display_name}`}
                >
                  Act as
                </button>
              </form>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
