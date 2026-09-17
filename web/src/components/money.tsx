import { formatAmount } from "@/lib/format";

/** A server-provided amount string with its currency. Never computed in the browser (FC-15). */
export function Money({
  value,
  currency,
  showCurrency = true,
}: {
  value: string | null | undefined;
  currency: string;
  showCurrency?: boolean;
}) {
  if (value === null || value === undefined) {
    return <span className="text-gray-600">—</span>;
  }
  const { text, negative } = formatAmount(value);
  return (
    <span
      className={`whitespace-nowrap tabular-nums ${negative ? "text-red-900" : ""}`}
      data-amount={value}
      aria-label={`${negative ? "negative " : ""}${text.replace(/[()]/g, "")} ${currency}`}
    >
      {text}
      {showCurrency ? <span className="ml-1 text-xs text-gray-600">{currency}</span> : null}
    </span>
  );
}
