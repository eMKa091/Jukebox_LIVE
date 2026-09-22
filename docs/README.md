# Jukebox LIVE — documentation

Written 2026-09-22 against commit `4d31a0f`, by reading every source file and
querying the shipped production database.

| Doc | What it answers |
|---|---|
| [01-as-built.md](01-as-built.md) | What the system does today, precisely |
| [02-data-model.md](02-data-model.md) | The schema as built, and the schema proposed |
| [03-findings.md](03-findings.md) | 17 defects and risks, ranked by what happens at a gig |
| [04-target-architecture.md](04-target-architecture.md) | The stack, the state machine, the request surface |
| [05-hosting.md](05-hosting.md) | Where to run it and what it costs |
| [06-migration-plan.md](06-migration-plan.md) | Ten phases with gates, ~13–16 days |

## The short version

Jukebox LIVE lets concert attendees vote, from their phones, on what the band
plays next. It has run eight real events since November 2025. It works — and it
has two structural problems that a rewrite has to fix rather than patch:

1. **Votes are only saved when an admin remembers to press a button.** The
   database is a SQLite file on an ephemeral container, pushed to GitHub by hand.
   Five of eight production events hold zero votes and there is no log that can
   tell us whether they were never run or whether the data was lost.
2. **Live state is five columns on one table, written from six places, with two
   round counters that drift.** This is why the multi-round feature has never
   been trusted in production.

Everything else in [03-findings.md](03-findings.md) is downstream of those two,
or is ordinary bit-rot.

**Recommendation:** rebuild as a single FastAPI container with HTMX and
Server-Sent Events over PostgreSQL, on Fly.io in Warsaw, for about $5/month.
AWS and Azure cost four to eight times that for a workload of 30,000 rows a
year. See [05-hosting.md](05-hosting.md) for the numbers and
[04-target-architecture.md](04-target-architecture.md) for the reasoning.
