import { StatusChip } from "@/components/status-chip";

/** Compatibility of a legacy → target account pair, as computed by the server. */
export function SignalChips({ signals }: { signals: unknown }) {
  if (!signals || typeof signals !== "object") {
    return <span className="text-[var(--ink-subtle)]">—</span>;
  }
  const values = signals as Record<string, boolean | null>;
  const labels: [string, string][] = [
    ["target_exists", "target exists"],
    ["type_compatible", "type"],
    ["subtype_compatible", "subtype"],
  ];
  return (
    <span className="flex flex-wrap gap-1">
      {labels.map(([key, label]) => {
        const value = values[key];
        const status = value === true ? "pass" : value === false ? "fail" : "unknown";
        const text = value === null ? `${label} unknown` : `${label} ${value ? "ok" : "conflict"}`;
        return <StatusChip key={key} status={status} label={text} />;
      })}
    </span>
  );
}
