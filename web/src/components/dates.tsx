import { LocalTime } from "@/components/local-time";

/** A business date: shown exactly as stored, never shifted by a time zone. */
export function BusinessDate({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="text-[var(--ink-subtle)]">—</span>;
  }
  return (
    <time dateTime={value} className="whitespace-nowrap tabular-nums">
      {value}
    </time>
  );
}

/** A system timestamp: viewer's local time, with UTC available on hover. */
export function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="text-[var(--ink-subtle)]">—</span>;
  }
  return <LocalTime value={value} />;
}
