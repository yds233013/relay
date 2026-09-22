# Deploying the public demo on Railway

The same public demo as [public-deployment.md](public-deployment.md), on Railway instead of a VM:
no server to administer, a Railway-provided HTTPS URL on day one, and a custom domain later if
wanted. Nothing about what Relay *is* in public changes — `RELAY_ENV=demo`,
`RELAY_AI_PROVIDER=demo`, no Anthropic key, one fictional company, every mutation refused except
starting an investigation. Only the shape of the hosting changes.

Files: [`deploy/railway/backend.Dockerfile`](../deploy/railway/backend.Dockerfile),
[`deploy/railway/backend-start.sh`](../deploy/railway/backend-start.sh). The web tier builds from the
unchanged [`web/Dockerfile`](../web/Dockerfile).

---

## 1. Services

```
            internet
               │  HTTPS (Railway edge: TLS, *.up.railway.app, host routing)
        ┌──────▼──────┐
        │     web     │   public — the only service with a domain
        └──────┬──────┘
   ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─   Railway private network (*.railway.internal)
        ┌──────▼──────┐
        │   backend   │   private — API (uvicorn :8000) + job worker, one container
        │  /data/blobs│ ← Railway volume
        └──────┬──────┘
        ┌──────▼──────┐
        │  Postgres   │   private — Railway PostgreSQL template, its own volume
        └─────────────┘
```

| service | built from | public | persistence |
|---|---|---|---|
| `web` | `web/Dockerfile`, root dir `web` | **yes** — Railway domain | none |
| `backend` | `deploy/railway/backend.Dockerfile`, repo root | no domain | volume at `/data/blobs` |
| `Postgres` | Railway PostgreSQL template | no public access | template volume |

Caddy is not deployed. On the VM it existed to terminate TLS, obtain certificates, redirect HTTP
and refuse unknown hosts; Railway's edge does all four for the service that has a domain, and the
backend and database have no domain at all, so nothing reaches them from the internet.

## 2. Why the API and the worker share a container

Relay's blob store is a content-addressed POSIX directory. The API writes it; the worker reads it
(every job handler receives the blob store, and pipeline runs load their inputs from it). They must
see the same files.

[Railway volumes](https://docs.railway.com/reference/volumes) attach to exactly one service and
cannot be shared, and [Render disks](https://render.com/docs/disks) have the same rule. The choices
were: write an object-storage `BlobStore` (application code), or run both processes where the
volume is. This deployment does the second. `backend-start.sh` runs `relay worker` and `uvicorn`
side by side and exits when either stops, so Railway's restart policy restarts both — one
process never runs on without the other.

Nothing about the security model moves: both processes were already private, run the same code
with the same environment, and still hold no public port.

## 3. What the backend image adds over `backend/Dockerfile`

- **The demo transcripts and seed fixtures**, copied in. Compose bind-mounts them; Railway runs no
  compose file.
- **A start script that owns first boot.** It migrates, then asks the database what it still needs:
  an empty database is seeded and prepared; one that was seeded but never prepared (an earlier
  boot died halfway) is prepared; anything else just starts. Neither step may run twice —
  `relay-demo seed` would create a second Brightwater, and the AI-consent half of
  `relay-demo public-demo` files a policy change Relay refuses once consent exists.
- **Root for one command only.** Railway mounts volumes root-owned, so the container starts as
  root, hands `/data/blobs` to the `relay` user, and re-execs itself through `setpriv` as uid
  10001. The worker, the API, migrations and the seed all run unprivileged. Railway's suggested
  workaround, `RAILWAY_RUN_UID=0`, would run all of Relay as root; this does not.

The Python layers mirror `backend/Dockerfile` with the same pinned digests; change them together.

## 4. Variables

`backend` — the database URL is assembled from the Postgres service's own reference variables, so
the password Railway generated is never typed, copied or printed:

```
RELAY_ENV=demo
RELAY_AI_PROVIDER=demo
RELAY_LOG_FORMAT=json
PORT=8000
RELAY_DATABASE_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
```

`web`:

```
RELAY_API_URL=http://backend.railway.internal:8000
RELAY_PUBLIC_DEMO=1
```

No `ANTHROPIC_API_KEY` is set anywhere. `RELAY_ENV=demo` refuses the paid provider at startup even
if one were.

## 5. What differs from the VM deployment, honestly

| | VM (Caddy) | Railway |
|---|---|---|
| TLS, certificate renewal, HTTP → HTTPS | Caddy | Railway edge |
| Unknown Host refused | Caddy | Railway edge routes only configured domains |
| `Strict-Transport-Security` | set by Caddy | **not set** — Railway's edge does not add it and the app does not either. A custom `.dev` domain later gets HSTS from the TLD's browser preload list |
| CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` | from the app | from the app — unchanged |
| 1 MB edge body cap | Caddy | none at the edge; the demo policy still refuses every mutation but one before reading a body |
| API and worker | two containers, one volume | one container, one volume |
| Reset | `make public-demo-reset` | delete the backend volume and the Postgres data, redeploy; the start script seeds an empty database |

## 6. Verified locally

The Railway shape was run locally before anything was created on Railway: Postgres, the backend
image built from a clean `git archive` of the repository, and the web image, each in its own
container on a private network, with the blob volume root-owned as Railway mounts it.

- first boot on an empty database: migrated, seeded, prepared, healthy in ~33 s
- every process — start script, worker, API — running as uid 10001; `/data/blobs` owned by `relay`
- canonical state: 12 gates / 9 failing / 217,212.85 USD / run #17 / 20 decisions / 18 applied
  change requests / top item 38,400.00
- 22 of 22 demo-policy probes correct from inside the private network
- a scripted investigation through the web tier: succeeded, labelled "Scripted demonstration — not
  a model", 0 tokens, provider `demo`
- redeploy onto that database: "already seeded and prepared", no reseed, investigation and all 16
  blobs kept, healthy in ~8 s
- interrupted first boot (seeded, never prepared): detected and prepared on the next boot
- SIGTERM: both processes stopped in ~1 s
- the web container's environment holds only `RELAY_API_URL` and `RELAY_PUBLIC_DEMO` — no
  database URL, no key
