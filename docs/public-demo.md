# The public demo

How Relay is served to someone who has only a link: what they can do, what stops them doing
anything else, and how to run it. Everything below was exercised against the demo stack on
2026-09-20; the numbers and responses are what came back.

Files: [`docker-compose.demo.yml`](../docker-compose.demo.yml),
[`.env.demo.example`](../.env.demo.example), `relay.api.demo_policy`, `relay-demo public-demo`.

Putting this on the internet — the single-node topology, the Caddy edge, DNS, backups and the
fresh-server runbook — is [public-deployment.md](public-deployment.md).

---

## 1. The three modes

Relay has three deployment modes, as separate values of `RELAY_ENV` rather than flags, so a public
deployment cannot be one forgotten boolean away from a development one.

| | **local** / test | **demo** | **production** |
|---|---|---|---|
| Who is acting | whoever `X-Relay-User` names | always the seeded `demo_visitor`; the header is **ignored** | nobody — no authentication exists yet |
| Signing in | pick a seeded person | not required, not offered | impossible |
| Mutations | all, subject to role and approval | refused by `demo_policy` except starting an investigation | every authenticated route answers 401 |
| AI providers allowed | any | **`demo` or `disabled` only** — refused at startup otherwise | any |
| `ANTHROPIC_API_KEY` | optional | never passed in; would change nothing if it were | required only for `anthropic` |
| Database password | development default is fine | must be real | must be real |
| Log format | anything | json | json |
| `/api/v1/docs`, `/api/v1/openapi.json` | served | **404** | **404** |
| `/api/v1/dev/users` | served | **404** | **404** |
| Suitable for real data | no | **no** | not until authentication exists |

`local` is unchanged by any of this, and `production` is unchanged: it still refuses everyone,
because real authentication is post-MVP (see [deployment.md §1](deployment.md)).

---

## 2. What a visitor can do

Open the link and Relay is there — no account, no sign-in, no 401. They can read everything: the
command centre, the Brightwater overview, the work queue and its filters, imported data down to
individual source rows and the quarantined line, both kinds of mapping, every verification run, the
37 accounting checks, all ten reconciliations with drill-downs into the record inspector, the 65
issues, duplicate parties with their match features, readiness with all twelve gates and their
evidence, every change request with its approvals, and the hash-chained audit log.

They can also **click Investigate** and watch a real investigation run. That is the one thing they
can change, and §4 explains why it is safe.

## 3. What a visitor cannot do

Everything else. Twenty of the API's twenty-one non-GET routes are refused before routing, with
`403 demo.read_only`:

> **View-only in public demo.** This is a public read-only demo of Relay. Exploring is
> unrestricted, and the AI investigation can be run, but changes that would alter the shared demo —
> uploads, mappings, corrections, approvals, policy, waivers and sign-off — are refused here. Every
> one of them works in a real deployment.

That covers creating migrations, uploading files, column and account mapping sets, creating,
editing, submitting, approving, rejecting or withdrawing change requests (which is how mappings,
record overrides, entity decisions, dispositions, policy versions, waivers and sign-off are *all*
applied), requesting pipeline runs, creating or editing issues and comments, and accepting,
dismissing or promoting AI findings.

Two independent controls enforce it:

1. **`relay.api.demo_policy`** — raw ASGI middleware, outside the router. Deny by default: anything
   that is not GET/HEAD/OPTIONS is refused unless its exact method and path shape are on a
   one-entry allowlist. A route added tomorrow is refused until someone deliberately adds it.
2. **The role table** — the visitor is `demo_visitor`, holding `READ` and `REQUEST_INVESTIGATION`
   and nothing else, checked by the same `require(...)` dependency every other request goes through.

The web app also hides what the API would refuse, so a visitor meets a short explanation rather
than a failed action. That is presentation, not protection, and is never counted as a control.

## 4. Investigate: genuinely interactive, honestly labelled

Clicking Investigate really runs the investigator against this database. The tools execute, the
evidence is current, and provenance verification runs as always. What is replayed is the
*reasoning*: the `demo` provider follows an authored transcript instead of calling a model, and the
UI says so in the investigation's own words — *"Scripted demonstration — not a model. This
investigation replayed an authored transcript. The tools below really ran against this migration,
so every piece of evidence is genuine, but the reasoning was written in advance rather than
produced by a model."*

It is bounded three ways:

- **Reuse.** An investigation of the same finding against the same run is returned as it stands
  rather than queued again, so the hundredth visitor to click the same item gets the first
  visitor's result instantly. The page says so: *"In this public demo every visitor shares one
  copy, so a finding is investigated once and everyone sees that same result."* Because a typed
  question could not change that answer, the demo does not offer the question box.
- **Rate limit.** The existing per-person limit of 20 investigations an hour applies, and since
  every visitor is the same person it is a global ceiling on new work.
- **Nothing downstream moves.** An investigation writes only its own records. Verified live: after
  running one, readiness was still 12 gates / 9 failing and exposure still 217,212.85.

## 5. Zero AI cost, structurally

Not a policy — a configuration refusal. `RELAY_ENV=demo` accepts `ai_provider` of `demo` or
`disabled` only:

```
the public demo accepts only ai_provider=demo or disabled; 'anthropic' is refused
```

The process does not start otherwise, so no request path exists that could reach a paid provider.
`ANTHROPIC_API_KEY` is not passed into a demo container at all, and setting one would change
nothing. An investigation run in the demo reports **0 tokens**, because no model ran.

## 6. Abuse protection

Proportionate to a portfolio deployment, not enterprise infrastructure:

| Concern | What is in place |
|---|---|
| Dangerous mutations | deny-by-default policy above; 20 of 21 non-GET routes refused |
| Unbounded AI jobs | per-finding reuse plus the shared 20/hour limit |
| Unbounded pipeline jobs | requesting a run is refused entirely |
| Uploads | refused entirely; no bytes are accepted from a visitor |
| Impersonation | the identity header is ignored in demo |
| Schema disclosure | `/api/v1/openapi.json` and `/api/v1/docs` are 404 |
| Seeded-user disclosure | `/api/v1/dev/users` is 404 |
| Stack traces | problem+json only; details are suppressed outside `local` (SEC-14) |
| Security headers | `nosniff`, `no-referrer`, `frame-ancestors 'none'`, `default-src 'none'` on the API; nonce CSP on the web |
| CORS | none is sent, because the browser never calls the API directly (SEC-15) |
| Database exposure | not published; only the compose network reaches it |
| Secrets | none in a demo process beyond the database password |

Not solved here, and deliberately: **there is no network-level rate limit**. A stranger can issue
unlimited GETs. Put the demo behind a reverse proxy or CDN that can absorb that — see §8.

## 7. Run it locally

```bash
cp .env.demo.example .env.demo    # fill in RELAY_DB_PASSWORD
make demo-config                  # validate the overlay, start nothing
make demo-up                      # fresh database -> migrate -> seed -> prepare -> serve
```

`make demo-up` runs its own compose project (`relay-demo`) with its own volumes, so it never
touches the development stack. It ends by printing the URL; with the example file that is
**http://127.0.0.1:3000/migrations** (13001 if you changed the port as the local verification did).

`make demo-down` stops it and deletes its volumes.

The state it produces is the canonical demo: Brightwater **not ready**, **9 of 12** gates failing,
**217,212.85 USD** unresolved exposure, 65 findings grouped into **20 decisions**, with the
**$38,400** mapping decision at the top of the queue and no investigation yet run.

`relay-demo public-demo` is the preparation step, and it is idempotent: it creates the demo visitor
if missing and records AI consent as a **policy change approved by the seeded lead and controller**,
through the same approvals as any other change. There is no code path that sets consent directly.

## 8. Before this faces the internet

- Terminate TLS and put a reverse proxy or CDN in front; keep `RELAY_WEB_BIND=127.0.0.1`.
- Give that proxy a request-rate limit, since Relay has none for reads.
- Use a real database password and keep it out of the repository.
- Expect the demo to be reset occasionally: investigations accumulate, one per finding. `make
  demo-down && make demo-up` returns it to the canonical state in a few minutes.
- Never point this at real customer data. Everything in it is fictional, and the UI says so.
