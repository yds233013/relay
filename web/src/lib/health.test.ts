import { describe, expect, it } from "vitest";

import { fetchBackendStatus, isReadinessBody } from "./health";

const BASE = new URL("http://api:8000/");

const HEALTH = { status: "ok", service: "relay-api", version: "0.1.0" };
const READY = {
  status: "ok",
  database: {
    reachable: true,
    migrations: "at_head",
    current_revision: "0001_baseline",
    head_revision: "0001_baseline",
  },
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function fakeFetch(routes: Record<string, () => Promise<Response>>) {
  const calls: string[] = [];
  const impl = async (input: URL): Promise<Response> => {
    calls.push(input.href);
    const handler = routes[input.pathname];
    if (!handler) {
      throw new TypeError("fetch failed");
    }
    return handler();
  };
  return { impl, calls };
}

describe("fetchBackendStatus", () => {
  it("reports up when both endpoints succeed", async () => {
    const { impl, calls } = fakeFetch({
      "/health": async () => json(HEALTH),
      "/health/ready": async () => json(READY),
    });
    const status = await fetchBackendStatus(BASE, impl);
    expect(status.liveness).toEqual({ state: "up", httpStatus: 200, body: HEALTH });
    expect(status.readiness).toEqual({ state: "up", httpStatus: 200, body: READY });
    expect(calls.sort()).toEqual(["http://api:8000/health", "http://api:8000/health/ready"]);
  });

  it("keeps a base path prefix when building URLs", async () => {
    const { impl, calls } = fakeFetch({});
    await fetchBackendStatus(new URL("http://proxy/relay/"), impl);
    expect(calls.sort()).toEqual(["http://proxy/relay/health", "http://proxy/relay/health/ready"]);
  });

  it("reports a 503 readiness response as down while keeping its body", async () => {
    const notReady = {
      status: "unavailable",
      database: {
        reachable: false,
        migrations: "unknown",
        current_revision: null,
        head_revision: "0001_baseline",
      },
    };
    const { impl } = fakeFetch({
      "/health": async () => json(HEALTH),
      "/health/ready": async () => json(notReady, 503),
    });
    const status = await fetchBackendStatus(BASE, impl);
    expect(status.liveness.state).toBe("up");
    expect(status.readiness).toEqual({
      state: "down",
      reason: "http_error",
      httpStatus: 503,
      body: notReady,
    });
  });

  it("reports unreachable backends", async () => {
    const { impl } = fakeFetch({});
    const status = await fetchBackendStatus(BASE, impl);
    expect(status.liveness).toEqual({
      state: "down",
      reason: "unreachable",
      httpStatus: null,
      body: null,
    });
  });

  it("reports timeouts", async () => {
    const hang = (_input: URL, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    const status = await fetchBackendStatus(BASE, hang, 20);
    expect(status.liveness).toMatchObject({ state: "down", reason: "timeout" });
    expect(status.readiness).toMatchObject({ state: "down", reason: "timeout" });
  });

  it("rejects 200 responses with an unexpected shape", async () => {
    const { impl } = fakeFetch({
      "/health": async () => json({ status: "ok" }),
      "/health/ready": async () => new Response("<html>proxy error page</html>", { status: 200 }),
    });
    const status = await fetchBackendStatus(BASE, impl);
    expect(status.liveness).toMatchObject({ state: "down", reason: "invalid_response" });
    expect(status.readiness).toMatchObject({ state: "down", reason: "invalid_response" });
  });
});

describe("isReadinessBody", () => {
  it.each([
    null,
    [],
    { status: "ok" },
    { status: "weird", database: READY.database },
    { status: "ok", database: { ...READY.database, reachable: "yes" } },
    { status: "ok", database: { ...READY.database, migrations: "ahead" } },
  ])("rejects %j", (value) => {
    expect(isReadinessBody(value)).toBe(false);
  });
});
