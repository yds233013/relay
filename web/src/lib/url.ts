export type Query = Readonly<Record<string, string | number | undefined | null>>;

/** Append non-empty query parameters to a path, in insertion order. */
export function buildPath(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}
