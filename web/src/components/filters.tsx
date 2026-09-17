/** GET filter forms keep filters in the URL, so every view is linkable and works without JS. */
export function FilterForm({ children }: { children: React.ReactNode }) {
  return (
    <form method="get" className="mb-3 flex flex-wrap items-end gap-3 text-sm">
      {children}
      <button
        type="submit"
        className="rounded border border-gray-400 bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100"
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
      <span className="text-xs font-medium text-gray-700">{label}</span>
      <select
        name={name}
        defaultValue={value ?? ""}
        className="rounded border border-gray-400 bg-white px-2 py-1"
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
