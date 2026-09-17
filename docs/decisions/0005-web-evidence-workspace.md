# 0005: Web evidence workspace (M4)

Status: **Accepted** (autonomous Tier 1 and Tier 2 decisions, 2026-09-17).

| # | Decision | Why |
|---|---|---|
| W-01 | **Pages are Server Components that call the API on the server.** The API URL and the development identity header never reach the browser, and there is no CORS configuration. TanStack Query is not used. | Keeps decision D-14 (API read server-side only). Every view is a request-time render of current data, which suits an evidence tool with no client-side editing yet. Client-side state management can be added when M5 introduces interactive editing. |
| W-02 | **Development identity is an HTTP-only cookie set by a Server Function** (`/select-user`). The server forwards it as `X-Relay-User`. The return path only accepts same-site relative paths. | Next.js 16 allows setting cookies only in Server Functions and Route Handlers. The browser never sees or sends the header itself. |
| W-03 | **Filters and pagination live in the URL** (GET forms, cursor links). Tables are server-rendered pages of at most 500 rows, not virtualized. | Every view is linkable and works without JavaScript. The API bounds page size, so virtualization adds complexity without a measured need. |
| W-04 | **The record inspector is a page** (`/migrations/{id}/records/{run}/{natural key}`), not a side panel. | Linkable, simple and accessible. A panel can be layered on later with intercepting routes. |
| W-05 | **The server computes every summary figure.** New API endpoints: `GET /migrations/{id}/overview` (banner, blockers with typed evidence links, exposure, open issue amounts by nature, largest open issues, queue, stages, recent activity), a portfolio summary on `GET /migrations`, typed gate evidence links on readiness, `order=amount`/`nature`/`fingerprint` filters on issues, `GET /pipeline-runs/{a}/diff/{b}`, and typed drill-down and profile responses. | FC-15: the browser formats server-provided strings and never adds, compares or rounds amounts. A test scans `web/src` for numeric parsing and rounding functions. |
| W-06 | **API types are generated** with `openapi-typescript` from the committed OpenAPI document into `web/src/lib/api/schema.d.ts`. A web test regenerates them and fails on drift; a backend test does the same for `openapi.json`. No response type is hand-written. | architecture.md §6.1. |
| W-07 | **Gate evidence is stored up to 1,000 references per gate** (previously 50). | The overview offered "all evidence" while silently holding 50 of 56 blocking findings. The observed count was always correct; the evidence list now is too. |
| W-08 | **End-to-end tests use the locally installed Chrome** (`channel: "chrome"`), so no browser binaries are downloaded. `@axe-core/playwright` fails a test on any serious or critical WCAG 2 A/AA violation. | The acceptance criteria ask for Lighthouse accessibility of at least 90. Lighthouse was measured separately (see progress.md); axe keeps accessibility checked on every E2E run. |
| W-09 | **The root path redirects to the portfolio.** The M0 status page moved to `/status`, which the smoke test and the web container healthcheck now use. | The status page stays a dependency-light health view. |

## Found while building M4

- The overview's R5 view defaulted to "discrepancy" lines, showing an empty table for a reconciliation that ties with explained items. It now defaults to discrepancies only when some exist.
- The record inspector listed source columns in JSONB key order. The API now returns the import header, and the inspector shows columns in file order.
- Lighthouse flagged a data table on the Overview without header cells. It now has a header row.
