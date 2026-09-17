/**
 * Backend health probe used by the M0 development page.
 *
 * Response shapes mirror relay.api.routers.health. They are validated at runtime because the
 * generated OpenAPI client does not exist until M3.
 */

export interface HealthBody {
  readonly status: "ok";
  readonly service: string;
  readonly version: string;
}

export interface ReadinessBody {
  readonly status: "ok" | "unavailable";
  readonly database: {
    readonly reachable: boolean;
    readonly migrations: "at_head" | "not_at_head" | "unknown";
    readonly current_revision: string | null;
    readonly head_revision: string | null;
  };
}

export type CheckResult<T> =
  | { readonly state: "up"; readonly httpStatus: number; readonly body: T }
  | {
      readonly state: "down";
      readonly reason: "unreachable" | "timeout" | "http_error" | "invalid_response";
      readonly httpStatus: number | null;
      readonly body: T | null;
    };

export interface BackendStatus {
  readonly liveness: CheckResult<HealthBody>;
  readonly readiness: CheckResult<ReadinessBody>;
}

type FetchLike = (input: URL, init: RequestInit) => Promise<Response>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isHealthBody(value: unknown): value is HealthBody {
  return (
    isRecord(value) &&
    value.status === "ok" &&
    typeof value.service === "string" &&
    typeof value.version === "string"
  );
}

export function isReadinessBody(value: unknown): value is ReadinessBody {
  if (!isRecord(value) || (value.status !== "ok" && value.status !== "unavailable")) {
    return false;
  }
  const database = value.database;
  return (
    isRecord(database) &&
    typeof database.reachable === "boolean" &&
    (database.migrations === "at_head" ||
      database.migrations === "not_at_head" ||
      database.migrations === "unknown") &&
    (database.current_revision === null || typeof database.current_revision === "string") &&
    (database.head_revision === null || typeof database.head_revision === "string")
  );
}

async function check<T>(
  url: URL,
  guard: (value: unknown) => value is T,
  fetchImpl: FetchLike,
  timeoutMs: number,
): Promise<CheckResult<T>> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    return {
      state: "down",
      reason: timedOut ? "timeout" : "unreachable",
      httpStatus: null,
      body: null,
    };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const parsed = guard(body) ? body : null;

  if (response.ok && parsed !== null) {
    return { state: "up", httpStatus: response.status, body: parsed };
  }
  return {
    state: "down",
    reason: response.ok ? "invalid_response" : "http_error",
    httpStatus: response.status,
    body: parsed,
  };
}

export async function fetchBackendStatus(
  apiBaseUrl: URL,
  fetchImpl: FetchLike = fetch,
  timeoutMs = 2000,
): Promise<BackendStatus> {
  const [liveness, readiness] = await Promise.all([
    check(new URL("health", apiBaseUrl), isHealthBody, fetchImpl, timeoutMs),
    check(new URL("health/ready", apiBaseUrl), isReadinessBody, fetchImpl, timeoutMs),
  ]);
  return { liveness, readiness };
}
