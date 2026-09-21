/** GET filter forms keep filters in the URL, so every view is linkable and works without JS. */
export function FilterForm({ children }: { children: React.ReactNode }) {
  return (
    <form method="get" className="mb-3 flex flex-wrap items-end gap-3 text-sm">
      {children}
      <button
        type="submit"
        className="rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 font-medium text-[var(--ink)] transition-colors hover:border-[var(--ink-muted)] hover:bg-[var(--surface-sunken)]"
      >
        Apply
      </button>
    </form>
  );
}

export function SelectFilter({
  name,
  label,
  value,
  options,
}: {
  name: string;
  label: string;
  value: string | undefined;
  options: readonly (readonly [string, string])[];
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
        {label}
      </span>
      <select
        name={name}
        defaultValue={value ?? ""}
        className="rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 transition-colors hover:border-[var(--ink-muted)]"
      >
        <option value="">Any</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}
