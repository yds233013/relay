"use client";

import { useSyncExternalStore } from "react";

function subscribe(): () => void {
  return () => undefined;
}

/** Renders UTC on the server and the viewer's local time after hydration. */
export function LocalTime({ value }: { value: string }) {
  const local = useSyncExternalStore(
    subscribe,
    () => new Date(value).toLocaleString(),
    () => `${value.replace("T", " ").replace(/\.\d+Z$/, "Z")}`,
  );
  return (
    <time dateTime={value} title={`${value} (UTC)`} className="whitespace-nowrap tabular-nums">
      {local}
    </time>
  );
}
