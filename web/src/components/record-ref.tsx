import Link from "next/link";

/** A link to the record inspector for one staged record of a run. */
export function RecordRef({
  migrationId,
  runId,
  naturalKey,
  children,
}: {
  migrationId: string;
  runId: string;
  naturalKey: string;
  children?: React.ReactNode;
}) {
  return (
    <Link
      href={`/migrations/${migrationId}/records/${runId}/${encodeURIComponent(naturalKey)}`}
      className="font-mono text-xs text-blue-800 underline decoration-dotted underline-offset-2 hover:decoration-solid"
    >
      {children ?? naturalKey}
    </Link>
  );
}
