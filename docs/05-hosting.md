# 05 — Hosting

> **Prices are indicative and were current to the best of my knowledge in
> mid-2026. Verify each one at the provider before committing.** The *ordering*
> is stable and is what the decision rests on; the absolute numbers drift.

## 1. What has to be hosted

One container (FastAPI + Uvicorn), one PostgreSQL database, one domain with TLS.
Long-lived SSE connections, so the platform must not kill idle HTTP streams —
that rules out plain serverless function hosts with short timeouts.

**Load profile:** effectively zero for 28 days a month; 20–300 concurrent phones
for a 2-hour window a few nights a month; database under 100 MB for the
foreseeable future. This is a *tiny* workload with a *spiky, unforgiving*
availability requirement.

The binding constraint is not capacity. It is that the thing must be up at 21:40
on a Saturday, and that the votes must still exist on Sunday.

## 2. Options

| Option | App | Database | Total / month | Ops burden |
|---|---|---|---|---|
| **Fly.io** *(recommended)* | ~$3 (shared-cpu-1x, 512 MB, Warsaw) | $0 — SQLite on a 1 GB volume (~$0.15) + Litestream to R2 (free tier) | **≈ $3** | Low |
| Hetzner CX22 | €3.79 (2 vCPU, 4 GB, Falkenstein) — app + PG + Caddy on one box | included | **≈ €4** | You patch it |
| Cloudflare Workers + D1 | $5 Workers Paid (needed for Durable Objects) | D1 free tier | **≈ $0–5** | Very low |
| Railway | ~$5 Hobby, usage-based | included | **≈ $5–10** | Very low |
| Render | $7 web service | $7 Postgres | **≈ $14** | Very low |
| **Azure** Container Apps + PG Flexible | ≈ $0 (monthly free grant covers this) | ~$13–18 (B1ms burstable + storage) | **≈ $15–20** | Low |
| **AWS** App Runner + RDS | ~$5–15 | ~$14–16 (db.t4g.micro + gp3) | **≈ $25–35** | Medium |

Plus a domain, ~€10–15/year, on any option.

## 3. Recommendation: Fly.io, Warsaw region

```
  fly.toml
  ├── app      jukebox-live    shared-cpu-1x, 512 MB, min_machines_running = 1
  ├── volume   jukebox_data    1 GB, holds jukebox.db
  ├── sidecar  litestream      streams the WAL to Cloudflare R2, continuously
  └── region   waw (Warsaw)    ~250 km from Ostrava
```

*(Amended 2026-09-23: SQLite replaced PostgreSQL. See
[04-target-architecture.md](04-target-architecture.md), amendment at the end.)*

Why this one:

- **It is a Docker image.** Nothing about the app knows it is on Fly. If Fly's
  pricing or reliability disappoints, `docker run` moves it to Hetzner in an
  afternoon. That reversibility is worth more than the ~$2/month it costs over
  the cheapest option.
- **Long-lived SSE connections are a first-class case**, not something to work
  around.
- **`min_machines_running = 1`.** Do *not* scale to zero. A cold start is
  seconds, and seconds are fine on a Tuesday and unacceptable when the singer
  has just told 200 people to open the link. The whole saving from scale-to-zero
  is about $2/month; it is not worth thinking about again.
- Managed TLS, a real deploy history, and `fly deploy --strategy immediate`
  rollbacks.

**Set the app to `min_machines_running = 1` on day one and never revisit it.**

### The alternative worth taking seriously

**Hetzner CX22 at €3.79/month** is the best raw value in this table and puts the
database on the same box as the app, which removes a network hop and a bill.
Take it if you would enjoy owning the box; you already run infrastructure for
other work. The cost is that OS patching, Postgres upgrades, TLS renewal, and
backup verification become yours, and a gig is a bad time to discover that
unattended-upgrades rebooted the machine.

### Why not AWS or Azure

Both are 4–8× the price for a workload that uses a rounding error of their
capability, and both charge that premium mainly for elasticity this app will
never use. AWS is the worst of the set here: RDS alone costs more than the
entire recommended stack, and App Runner's minimum provisioned-memory charge
applies during the 28 days a month nobody is voting.

Azure is the better of the two — Container Apps' monthly free grant genuinely
covers this app's compute, so the whole bill is the managed Postgres. If there
is an external reason to be on Azure (an existing account, someone else paying,
a client requirement), Azure Container Apps + PostgreSQL Flexible Server is a
perfectly sound build and the architecture in [04](04-target-architecture.md)
ports to it unchanged. Absent such a reason, it is $15–20/month for nothing.

### Why not Cloudflare, given you already use it

It is the cheapest credible option and Durable Objects are the best real-time
primitive available for this exact problem. It costs a TypeScript rewrite and
real lock-in. See [04-target-architecture.md §2](04-target-architecture.md).

## 4. Backups — the part that actually matters

[F1](03-findings.md) is the reason for this whole project. The new system must
make vote loss structurally impossible, not merely unlikely.

| Layer | Mechanism | Retention |
|---|---|---|
| **Continuous** | **Litestream ships the SQLite WAL to R2 every 10 s** | 72 h of restore points |
| Daily | Litestream snapshot | 72 h |
| Per event | CSV export on `event.closed`, plus `app.cli backup` | forever |
| Quarterly | A restore that is actually performed | — |

The continuous layer is the one that matters. The worst case for a total
machine loss is ten seconds of votes, with nobody having had to press
anything — which is the direct, structural answer to F1.

The per-event hook is the direct replacement for the "Backup now" button. It
fires on a state transition, not on someone remembering. The CSV lands somewhere
the band can read without a database client.

**A backup nobody has restored is a hope, not a backup.** Put a calendar
reminder on the quarterly restore drill and actually do it.

## 5. Domain, DNS and entry

- Register a short, sayable domain (a `.cz` is ~€8–12/year). It has to work
  spoken into a microphone in a loud room.
- DNS on Cloudflare — you already have an account, it is free, and it gives
  proxying and analytics.
- The attendee entry point is a **QR code per event**, generated in the admin
  console and printed for the tables. Nobody types a URL in the dark.
- Keep the Streamlit deployment reachable for one gig after cutover, then take
  it down.

## 6. Secrets

Everything from the environment, nothing in the repository:

```
DATABASE_URL           provider-issued
SESSION_SECRET         32 random bytes
BAND_LINK_SECRET       32 random bytes, signs /band/{token}
BACKUP_S3_*            object-storage credentials
```

`GITHUB_TOKEN` disappears entirely — nothing writes to a repository at runtime
any more. **Revoke it the day the Streamlit app is retired.** It is the token
with write access to `eMKa091/Jukebox_LIVE` — confirmed 2026-09-23, despite
`gh_utils.py:7` naming `az-fkaw` ([F2](03-findings.md)).

## 7. GDPR

The system collects a display name and a device cookie, and nothing else — no
email, no phone, no account. Keep the database in the EU (every recommended
option above is EU-hosted) and the compliance story stays a one-page notice:
what is collected, why, how long, and that it is deleted with the event. Add a
retention job that drops `voters` rows 90 days after an event closes; the
aggregate tallies the band cares about survive it.
