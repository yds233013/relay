import { ConfigError, type ServerConfig, parseServerConfig } from "@/lib/config";
import { type BackendStatus, type CheckResult, fetchBackendStatus } from "@/lib/health";

// Rendered per request on the server: the status must be live, never baked in at build time.
export const dynamic = "force-dynamic";

function loadConfig(): ServerConfig | ConfigError {
  try {
    return parseServerConfig(process.env);
  } catch (error) {
    if (error instanceof ConfigError) {
      return error;
    }
    throw error;
  }
}

function StatusLabel({ result }: { result: CheckResult<unknown> }) {
  if (result.state === "up") {
    return <span className="font-medium text-green-800">UP (HTTP {result.httpStatus})</span>;
  }
  const http = result.httpStatus === null ? "" : ` (HTTP ${result.httpStatus})`;
  return (
    <span className="font-medium text-red-800">
      DOWN: {result.reason}
      {http}
    </span>
  );
}

function Row({
  label,
  children,
  testId,
}: {
  label: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <tr className="border-b border-gray-200 last:border-b-0">
      <th className="py-2 pr-4 font-normal text-gray-600">{label}</th>
      <td className="py-2" data-testid={testId}>
        {children}
      </td>
    </tr>
  );
}

function StatusTable({ status }: { status: BackendStatus }) {
  const { liveness, readiness } = status;
  const database = readiness.body?.database ?? null;
  const migrations =
    database === null
      ? "unknown"
      : `${database.migrations} (current ${database.current_revision ?? "none"}, head ${
          database.head_revision ?? "none"
        })`;

  return (
    <table className="w-full border-collapse text-left text-sm">
      <tbody>
        <Row label="API liveness" testId="liveness">
          <StatusLabel result={liveness} />
        </Row>
        <Row label="API version">{liveness.body?.version ?? "unknown"}</Row>
        <Row label="Readiness" testId="readiness">
          <StatusLabel result={readiness} />
        </Row>
        <Row label="Database reachable">
          {database === null ? "unknown" : String(database.reachable)}
        </Row>
        <Row label="Migrations">{migrations}</Row>
      </tbody>
    </table>
  );
}

export default async function DevelopmentStatusPage() {
  const config = loadConfig();
  const status = config instanceof ConfigError ? null : await fetchBackendStatus(config.apiBaseUrl);

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-xl font-semibold">Relay</h1>
      <p className="mb-6 text-sm text-gray-600">
        Development status page: backend liveness and database readiness.
      </p>
      {config instanceof ConfigError ? (
        <p className="text-sm text-red-800">Configuration error: {config.message}</p>
      ) : null}
      {status === null ? null : <StatusTable status={status} />}
    </main>
  );
}
