# Deploying Relay as a public web application

How the public demo becomes an HTTPS URL somebody can open: the single-node topology, the edge,
the runbook for a fresh server, and the two operational procedures that matter afterwards — reset
and backup.

Everything below was exercised locally against the real topology on 2026-09-21, with Caddy issuing
its own certificate because a local machine has no public DNS. The numbers quoted are what came
back. What could not be exercised locally — Let's Encrypt issuing a certificate for a real name —
is called out where it appears.

Files: [`docker-compose.public.yml`](../docker-compose.public.yml),
[`deploy/Caddyfile`](../deploy/Caddyfile), [`.env.public.example`](../.env.public.example),
[`deploy/public-demo-reset.sh`](../deploy/public-demo-reset.sh),
[`deploy/verify-demo-state.sh`](../deploy/verify-demo-state.sh),
[`deploy/public-backup.sh`](../deploy/public-backup.sh).

Read [public-demo.md](public-demo.md) first: it explains what the demo *is* and why a visitor
cannot damage it. This document is only about getting that onto the internet.

---

## 1. What is being deployed

The public demo, unchanged, with a TLS edge in front of it. `RELAY_ENV=demo`,
`RELAY_AI_PROVIDER=demo`, one fictional company, every mutation refused except starting an
investigation. It is **not** production: Relay has no authentication, and this deployment does not
add any. It holds no real data and must never be pointed at any.

## 2. Why one machine

Relay's blob store is a content-addressed directory on a POSIX filesystem, and the API and the
worker must see the same one. Splitting them across machines means writing an object-storage
adapter, which is a real piece of work for a demo that serves one fictional company. One VM with a
shared Docker volume is the honest shape for what this is, and it is the shape the whole test suite
already exercises. Scale is not the constraint here; the constraint is that everything about this
deployment should be inspectable in an afternoon.

## 3. Topology

```
                         internet
                             │
                    ┌────────┴────────┐          the only listening ports
                    │   :80    :443   │          on the machine
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │      caddy      │  TLS, ACME, HTTP→HTTPS, host validation
                    └────────┬────────┘
   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─  private compose network
                    ┌────────▼────────┐
                    │   web  :3000    │  Next.js. Renders on the server; the browser
                    └────────┬────────┘  never talks to the API.
                             │
                    ┌────────▼────────┐
                    │   api  :8000    │  FastAPI. No published port.
                    └───┬────────┬────┘
                        │        │
         ┌──────────────▼──┐  ┌──▼──────────────┐
         │  postgres :5432 │  │  worker (none)  │  jobs; no inbound port at all
         └────────┬────────┘  └────────┬────────┘
                  │                    │
          relay-postgres-data      relay-blobs  ← one volume, mounted by api and worker
```

Four facts this rests on, each checked against the code rather than assumed:

- **The browser never calls the API.** `web/src/lib/api/client.ts` is `import "server-only"`, and
  no `NEXT_PUBLIC_*` variable exists anywhere in the web tier, so the API URL cannot reach a
  browser bundle. Every API call happens in a Server Component or Server Function.
- **The API needs no published port.** It is reached as `http://api:8000` over the compose
  network. `docker-compose.public.yml` leaves it unpublished, as it already was in the demo overlay.
- **The worker needs no inbound port.** It polls PostgreSQL for jobs (`SKIP LOCKED`) and holds no
  listener. Its health check writes a heartbeat file.
- **api and worker share one blob volume.** Both mount the named volume `relay-blobs` at
  `/data/blobs`; `docker inspect` on a running pair shows the same volume object in each.

## 4. The edge

[`deploy/Caddyfile`](../deploy/Caddyfile), stock `caddy:2-alpine`. No plugin and no custom build —
`make public-config` runs `caddy validate` against the official image, which fails on any directive
that is not in it.

| | |
|---|---|
| **HTTPS** | Automatic. Caddy obtains a certificate for `RELAY_PUBLIC_HOST` over ACME HTTP-01 on port 80 and renews it without being asked. |
| **HTTP → HTTPS** | Automatic: `308 Permanent Redirect`. Caddy installs it because the site address is a hostname; there is no redirect block to get wrong. |
| **Host validation** | A request whose Host is not `RELAY_PUBLIC_HOST` matches no site, so Caddy answers an empty `200` with `Content-Length: 0` and **never proxies to the application**. Over the internet a client must complete TLS first, and an unknown SNI has no certificate, so the handshake fails outright. |
| **HSTS** | `Strict-Transport-Security: max-age=31536000; includeSubDomains`, set here because this is where TLS terminates. No `preload`: that is a one-way commitment on the whole domain. `RELAY_HSTS_MAX_AGE` lowers it for a cautious first day. |
| **Other security headers** | Deliberately *not* set here. `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and the nonce-based CSP come from the application (`web/next.config.ts`, `web/src/proxy.ts`). Two sources for one header is how they drift apart. |
| **Body limit** | `request_body max_size 1MB`. The demo accepts no uploads; the one permitted write is a small form post. |
| **Compression** | `encode zstd gzip`. |
| **Logs** | JSON to stdout, rotated by the Docker json-file driver (10 MB × 5). |

Observed on the local run, through the edge:

```
HTTP/1.1 308 Permanent Redirect      http://…/migrations  → https://…/migrations
HTTP/2 200                           https://…/migrations
  strict-transport-security: max-age=31536000; includeSubDomains
  content-security-policy: default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic'; …
  referrer-policy: no-referrer
  x-content-type-options: nosniff
  x-frame-options: DENY
```

No path under `/api/` is reachable through the edge: the web application has no such route and
answers 404, and Caddy has no route to the API at all.

## 5. Abuse protection

**Stock Caddy has no rate limiting.** The `caddy-ratelimit` module is a third-party plugin that
requires building a custom Caddy with `xcaddy`, and a custom edge binary is a poor trade for a
portfolio demo — it has to be rebuilt and re-verified on every Caddy release.

What actually protects this deployment, in order of how much work it does:

1. **The demo refuses almost everything, before routing.** `relay.api.demo_policy` is a
   deny-by-default ASGI middleware: every method outside `GET`/`HEAD`/`OPTIONS` is refused with
   `403 demo.read_only` unless it matches one allowlisted route, and the refusal happens before
   dependencies run or any body is read. There is nothing expensive to abuse.
2. **The one permitted write is bounded twice, in the application.** Starting an investigation
   first looks for an existing investigation of the same issue against the same run and returns it
   if there is one (`reuse_existing`, set only in demo) — so for a fixed set of findings and one
   current run, the *entire internet* can create at most one investigation per finding, and every
   click after that is a `SELECT`. Behind that sits a limit of 20 new investigations per person per
   hour; in the demo every visitor is the same `demo_visitor`, so it is a global limit of 20 per
   hour. Both are in `relay.investigations.service`.
3. **Reads are cheap and bounded.** Every list endpoint is cursor-paginated at no more than 500
   rows, and the pages a visitor can reach are server-rendered from a database that fits in memory.
4. **The edge bounds request bodies** at 1 MB and terminates slow connections with Caddy's
   defaults.

**What still needs configuring externally, after the host is chosen** — none of it is in this
repository because all of it depends on where the machine lives:

- **Volumetric / L3-L4 protection** is the hosting provider's. Most VPS providers (Hetzner, DO,
  Vultr, Linode) include basic DDoS filtering at the network edge and a firewall; none of them do
  L7 rate limiting.
- **L7 rate limiting**, if it turns out to be wanted, is one rule on a CDN in front. Cloudflare's
  free tier can do it. Note the interaction: with Cloudflare proxying, port 80 no longer reaches
  the VM, so ACME HTTP-01 stops working — you would switch Caddy to a Cloudflare Origin CA
  certificate, or leave the record DNS-only until the first certificate is issued and then turn the
  proxy on. Do not do this until there is evidence it is needed.
- **`fail2ban` over Caddy's JSON access log** is the no-new-dependency option if a single source
  starts scraping. It is a per-host decision and is not worth pre-configuring.

## 6. Compose services

Three files, layered. The third does not repeat the second — duplicating the demo's guarantees
would create a second place for them to drift.

```
docker-compose.yml          what the services are
docker-compose.demo.yml     what Relay IS in public: RELAY_ENV=demo, read-only visitor,
                            deny-by-default policy, RELAY_AI_PROVIDER=demo, no key
docker-compose.public.yml   how it is EXPOSED: Caddy is added and is the only published
                            service; the web tier stops being published at all
```

| service | published | container port | persistence | health check | restart |
|---|---|---|---|---|---|
| `caddy` | **80, 443** | 80, 443 | `caddy-data`, `caddy-config` | admin API on loopback | `unless-stopped` |
| `web` | no | 3000 | none | `GET /status` (Dockerfile) | `unless-stopped` |
| `api` | no | 8000 | `relay-blobs` | `GET /health` (Dockerfile) | `unless-stopped` |
| `worker` | no | none | `relay-blobs` | heartbeat file freshness | `unless-stopped` |
| `db` | no | 5432 | `relay-db` | `pg_isready` | `unless-stopped` |
| `migrate` | no | none | none | n/a (one-shot) | `no` |

`migrate` runs `alembic upgrade head` and exits; `api` and `worker` both declare
`depends_on: migrate: service_completed_successfully`, so nothing that touches the schema starts
before it is at head.

No Docker socket is mounted anywhere. No container is privileged, none uses host networking, and
both application images run as a non-root `relay` user.

## 7. Volumes

| volume | holds | if lost |
|---|---|---|
| `relay-db` | the whole Relay database: the demo migration, its runs, findings, change requests, audit chain, and whatever visitors did | re-seed; the canonical state comes back exactly, visitor state does not |
| `relay-blobs` | the content-addressed source files the seed imported | re-seed |
| `caddy-data` | the ACME account key and the issued certificate | Caddy re-issues on next start — not fatal, but it spends Let's Encrypt rate limit |
| `caddy-config` | Caddy's autosaved JSON config | regenerated from the Caddyfile |

`make public-down` stops the stack and **keeps** all four. Only `docker compose … down -v` removes
them, and no Makefile target does that for this project.

## 8. First run

```bash
make public-config    # renders the stack and validates the Caddyfile; starts nothing
make public-init      # build, migrate, seed Brightwater, enable governed demo AI, start, verify
```

`public-init` ends by running `deploy/verify-demo-state.sh`, which fails loudly if the deployment
is not serving the canonical state. Measured locally, excluding the image build: **56 seconds**.

```
  company_prefix           Brightwater Provisions   ok
  gates                    12                       ok
  failing_gates            9                        ok
  unresolved_exposure      217212.85                ok
  currency                 USD                      ok
  run_sequence             17                       ok
  run_is_current           True                     ok
  work_queue_decisions     20                       ok
  investigations           0                        ok
  applied_change_requests  18                       ok
  largest_queue_amount     38400.00                 ok
  canonical demo state verified
```

Those numbers are a *deployment expectation*, not application behaviour. Nothing in `relay.*` or in
the web tier knows them — they are what the deterministic engine produces from the committed
fixtures. Runtime code that branched on them would be exactly the scenario-specific special-casing
`CLAUDE.md` forbids.

`make public-up` is the idempotent version for later: it starts the database, runs migrations, and
brings everything up without touching data.

## 9. Resetting the demo

```bash
make public-demo-reset            # prompts; type "reset"
deploy/public-demo-reset.sh --yes # no prompt, for automation
```

It prints what it is about to destroy before doing anything:

```
  THIS WILL DELETE PUBLIC DEMO INTERACTION STATE
    - every investigation visitors have started
    - the audit events those produced
    - every blob written since the last reset
    - the whole Relay database, which is then recreated and re-seeded
```

**Destroyed:** the Relay database (dropped and recreated), the blob volume's contents, every
investigation and every audit event produced since the last reset.

**Preserved:** the images (nothing is rebuilt), Caddy's certificates and configuration (its
container is never stopped, so no certificate is re-issued and no Let's Encrypt rate limit is
spent), PostgreSQL's container and volume, and the compose network.

Measured locally: **77 seconds end to end, of which 64 seconds returned `502`** — Caddy stays up
and answers throughout, so a visitor sees a proper error page rather than a dead connection. The
old approach, `down -v` followed by a rebuild, cost a certificate and several minutes for state
that `DROP DATABASE` clears in about a second.

## 10. Backup and restore

Deliberately two files and a cron line. The demo holds fictional data that can be regenerated from
this repository in minutes; the point of a backup is to avoid re-seeding and to keep whatever
visitors did.

```bash
make public-backup            # writes ./backups/relay-db-<stamp>.dump and relay-blobs-<stamp>.tar.gz
```

**The order is database first, blobs second, and it only works in that direction.** Blobs are
content-addressed and append-only, and the database holds the references to them. Dumping the
database first means anything written in between lands in the blob archive without being referenced
— an orphan, which is harmless. The other order would put a reference in the dump whose blob is
missing from the archive, and that is a broken restore.

Restore onto a fresh machine:

```bash
# 1. bring up an empty stack (build, database, migrations — but do not seed)
make public-build
docker compose -p relay-public --env-file .env.public \
  -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml up -d --wait db

# 2. restore the database into the empty one
docker compose -p relay-public --env-file .env.public \
  -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml \
  exec -T db pg_restore -U "$RELAY_DB_USER" -d "$RELAY_DB_NAME" --clean --if-exists < backups/relay-db-<stamp>.dump

# 3. restore the blobs
docker compose -p relay-public --env-file .env.public \
  -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.public.yml \
  run --rm --no-deps -T --entrypoint tar api -xzf - -C /data < backups/relay-blobs-<stamp>.tar.gz

# 4. start everything and check
make public-up && make public-verify
```

**If the VM dies entirely**, what matters is: this repository (which is in git and needs no
backup), `.env.public` (which is *not* in git — keep the database password in a password manager,
not only on the machine), and the two backup files. Everything else is rebuilt: images from the
Dockerfiles, the certificate from ACME, the demo data from the fixtures. Caddy's certificate state
is worth restoring only to avoid re-issuance; it is not worth engineering around.

With no backups at all, a dead VM costs one `make public-init` on a new one — about a minute once
Docker is installed — and loses only visitor investigations.

## 11. VM sizing

Measured on the real topology, all five services running:

| | |
|---|---|
| idle, whole stack | **308 MiB** (api 90, db 70, web 68, worker 64, caddy 16) |
| peak during a reset (the heaviest thing it does) | **614 MiB** summed across all containers, including the transient seed container at 153 MiB |
| images on disk | ~1.45 GB (`relay-backend` 522 MB, `relay-web` 434 MB, `postgres` 411 MB, `caddy` 85 MB) |
| volumes after seeding | ~120 MB (database 117 MB, blobs 2 MB, Caddy 72 KB) |

**Minimum: 2 vCPU, 2 GB RAM, 20 GB disk.** The stack fits, but `next build` is the memory-hungry
step and 2 GB is uncomfortable for it — add 2 GB of swap, or build the images elsewhere and pull
them.

**Recommended: 2 vCPU, 4 GB RAM, 40 GB disk.** Builds comfortably on the box, leaves room for the
Docker build cache (which grows), backups, and logs, and stays responsive while a visitor browses,
an investigation replays and the worker polls. The difference is a few dollars a month; running out
of memory during a build on a live server is not worth saving them.

The test suite is not run on this machine and does not need to be.

## 12. Firewall

Inbound, exactly three:

| port | why |
|---|---|
| 22 | SSH. Restrict by source IP if your address is static — `ufw allow from <ip> to any port 22`. If it is not, leave it open to all and rely on key-only authentication (`PasswordAuthentication no`), because locking yourself out of a demo server is a worse outcome than the marginal risk. |
| 80 | ACME HTTP-01 renewal and the HTTP→HTTPS redirect. **Not optional**: closing it breaks certificate renewal about 60 days later, silently. |
| 443 | the site |

Everything else is denied. The compose stack publishes nothing else — that is a property of the
rendered configuration, not a promise:

```
$ docker compose … config | grep -B2 published
  caddy:
    ports:
      - target: 80
        published: "80"
      - target: 443
        published: "443"
```

There is no other `ports:` block in the rendered file. Verified on the running stack: only `caddy`
had a host publisher; `api`, `db`, `web` and `worker` showed none.

Port 443/UDP (HTTP/3) is deliberately **not** published. Caddy advertises `Alt-Svc: h3` but the
mapping does not exist, so clients fall back to HTTP/2. Publish it and open the UDP port if you
want HTTP/3.

Outbound the machine needs: DNS (53), HTTP/HTTPS to Let's Encrypt for ACME, and HTTPS to the
registries used at build time (Docker Hub, PyPI, npm). Nothing in the running application makes an
outbound call — the demo AI provider replays a transcript from disk, so there is no model endpoint
to reach.

## 13. Fresh-server runbook

For a clean Ubuntu 24.04 LTS (or Debian 12) VM. Usable by someone who did not build Relay.

```bash
# 1–3. create the VM at your provider, note its public IPv4 (and IPv6 if it has one), then:
ssh root@<SERVER_IP>

# 4. updates and a non-root user
apt-get update && apt-get -y upgrade
adduser --disabled-password --gecos "" relay && usermod -aG sudo relay
rsync --archive --chown=relay:relay ~/.ssh /home/relay/
# harden SSH: set `PasswordAuthentication no` in /etc/ssh/sshd_config, then
systemctl restart ssh

# 5–6. Docker Engine and the Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sh
usermod -aG docker relay
docker compose version        # must print v2.x

# 7. firewall
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw enable && ufw status verbose

# 8. the repository, as the relay user from here on
su - relay
git clone <REPOSITORY_URL> relay && cd relay

# 9–11. environment
cp .env.public.example .env.public
openssl rand -base64 32          # generate the database password ON THE SERVER
$EDITOR .env.public              # paste it into RELAY_DB_PASSWORD; set RELAY_PUBLIC_HOST
                                 # and RELAY_ACME_EMAIL. Never paste this file into a chat window.
chmod 600 .env.public

# 12. DNS — see §14. Do this BEFORE the next step and wait for it to propagate.
dig +short <YOUR_HOSTNAME>       # must return this server's IP

# 13. validate before starting anything
make public-config

# 14–17. build, initialise, start
make public-init                 # ends with the canonical-state check

# 18. health
make public-ps                   # every service healthy; only caddy publishes anything
make public-logs                 # ctrl-C to stop following

# 19–20. public verification, from your own machine
curl -sSI http://<YOUR_HOSTNAME>/migrations | head -1     # 308 to https
curl -sSI https://<YOUR_HOSTNAME>/migrations | head -1    # 200, valid certificate
make public-verify                                        # canonical state, on the server

# 21–22. investigation end to end, then back to pristine
#   open https://<YOUR_HOSTNAME>/migrations in a browser, open the implementation,
#   open the work queue, click Investigate on the leading item, watch it complete
make public-demo-reset           # type "reset"; ~77s, ~64s of 502

# 23. final smoke test
make public-verify && curl -sSI https://<YOUR_HOSTNAME>/migrations | head -1
```

Never commit `.env.public`. Never paste the database password, the server's SSH key, or the
contents of `.env.public` into a chat window — none of it is needed to help you.

## 14. DNS

Relay does not care what the name is; Caddy needs it to resolve to this machine **before** it
starts, because ACME HTTP-01 works by Let's Encrypt fetching a file from `http://<name>/` .

| record | value | TTL |
|---|---|---|
| `A` for `relay.<your-domain>` | the VM's public IPv4 | 300 while setting up, 3600 afterwards |
| `AAAA` for the same name | the VM's public IPv6, **only if** the VM has one and it is reachable | same |

Order of operations:

1. Create the record. Do **not** enable a CDN proxy (Cloudflare's orange cloud) for the first
   issuance — it intercepts port 80 and HTTP-01 fails.
2. Wait for it: `dig +short relay.<your-domain>` from somewhere other than the server must return
   the VM's address. A low TTL keeps a mistake cheap.
3. Then `make public-init`. Caddy requests the certificate within seconds of starting.
4. Watch it land: `make public-logs` shows `certificate obtained successfully`.

If the record is wrong when Caddy starts, nothing breaks permanently: Caddy retries with a backoff,
and the site answers on HTTP only in the meantime. Fix the record, then `docker compose … restart
caddy` to retry immediately. Let's Encrypt rate-limits *failed* validations too, so fix the DNS
before retrying in a loop.

To verify the finished result from outside: `curl -sSI https://relay.<your-domain>/migrations`
should return `HTTP/2 200` with `strict-transport-security` present, and a browser should show a
valid certificate issued by Let's Encrypt.

## 15. What is deliberately not here

- **No authentication.** Unchanged from [public-demo.md](public-demo.md): every visitor is the same
  read-only demo visitor. This deployment does not add auth and must not be read as production.
- **No separate database roles** (SEC-25). Still documented as unimplemented in
  [traceability.md](traceability.md).
- **No L7 rate limiting in the repository.** §5 explains what does the work instead and what to add
  externally if it turns out to be needed.
- **No secrets manager.** One password in one `chmod 600` file on one machine is the right size for
  this.
