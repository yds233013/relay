/**
 * Display formatting for values the server provides as strings. Pure string manipulation: the web
 * app never parses money into numbers, adds, compares or rounds amounts (FC-15).
 */

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Group the integer digits of a decimal string: "1234567.50" -> "1,234,567.50". */
function groupDigits(integer: string): string {
  let result = "";
  for (let index = 0; index < integer.length; index += 1) {
    const remaining = integer.length - index;
    result += integer.charAt(index);
    if (remaining > 1 && remaining % 3 === 1) {
      result += ",";
    }
  }
  return result;
}

export interface MoneyParts {
  readonly text: string;
  readonly negative: boolean;
}

/** Negative amounts are shown in parentheses; the currency is shown by the caller. */
export function formatAmount(value: string): MoneyParts {
  const match = DECIMAL.exec(value.trim());
  if (match === null) {
    return { text: value, negative: false };
  }
  const [, sign, integer = "0", fraction] = match;
  const grouped = groupDigits(integer) + (fraction === undefined ? "" : `.${fraction}`);
  const negative = sign === "-" && /[1-9]/.test(integer + (fraction ?? ""));
  return { text: negative ? `(${grouped})` : grouped, negative };
}

/** "legacy_coa" -> "Legacy coa"; used for enum-like labels. */
export function humanize(value: string): string {
  const spaced = value.replaceAll("_", " ").replaceAll(".", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A single-value search parameter, ignoring repeated keys. */
export function param(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
