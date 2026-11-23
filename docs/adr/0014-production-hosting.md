# ADR 0014: Where AirSight runs in production

- **Status:** Accepted
- **Date:** 2026-11-23
- **Issue:** #163

## Context

Until now AirSight has run only for its developer. A public project needs a public HTTPS address
that a reader can open, and a way to ship new versions to it from GitHub.

What the host has to carry, measured on 2026-11-21 with `docker stats` on the full stack:

| Service | Memory |
|---|---|
| MLflow | 1.6 GB |
| Grafana | 367 MB |
| Celery worker | 334 MB |
| Celery beat, exporter, API, database | 180 to 215 MB each |
| Prometheus, Alertmanager, Redis | under 100 MB each |
| **Total** | **about 3.2 GB** |

The database volume is 175 MB. CPU use is under 3% at rest; the jobs run every 3 hours or once a
day. The jobs need outbound access to PurpleAir, AirNow and Open-Meteo, and the PurpleAir points
budget (ADR 0006) allows only one place to ingest.

The budget is $0, with no payment card available.

## Options

1. **A small paid VM** (about $5 to $8 a month). The best fit, ruled out by the budget.
2. **Oracle Cloud Always Free** (2 OCPUs and 12 GB on Arm since June 2026). Tried on 2026-11-21
   to 2026-11-23: the signup requires card verification and rejected every card tried.
3. **Free plans on hosting platforms** (Render, Fly.io, Railway and similar). Free services sleep
   when idle or have no always-on background workers, free databases are small or expire, and
   none runs our TimescaleDB and PostGIS image with Celery for free.
4. **Cloudflare Quick Tunnels** from the laptop. No account needed, but the hostname changes on
   every start and Cloudflare documents them as for testing only. A named Cloudflare Tunnel needs
   a domain.
5. **The laptop as the server, published with Tailscale Funnel.** Tailscale's free Personal plan
   needs no card. Funnel gives the machine a fixed public HTTPS name,
   `https://airsight.tailbcc5c4.ts.net`, terminates TLS with a certificate it manages, and needs
   no open router ports. The cost: the site is down whenever the laptop sleeps or is off, Funnel
   has bandwidth limits Tailscale does not publish, and it is meant for modest traffic.

## Decision

**Option 5.** The MacBook (Apple Silicon, 16 GB) runs the production stack, and Tailscale Funnel
publishes it. The setup is kept portable: the same images and compose files run on any Linux VM,
so moving to a paid or free VM later is a deployment, not a redesign.

**Exposure.** Funnel forwards public HTTPS on port 443 to one local port, served by Caddy on
127.0.0.1. Caddy serves the built web app and proxies `/v1` to the API (#165). Nothing else is
reachable from outside: Grafana, Prometheus, Alertmanager, MLflow, the database and Redis stay on
127.0.0.1, and `/metrics` is not proxied. The router has no ports open.

**Production stack.** A production compose override (#164) runs the services from images, with
restart policies and memory limits, secrets in a `.env` file outside git, and the web app built
into the Caddy image. Docker Desktop and Tailscale start at login, and the Mac does not sleep on
power.

**Shipping.** GitHub Actions builds the images on every merge to `main` and pushes them to GitHub
Container Registry. A release tag deploys: the workflow joins the tailnet with a short-lived,
tagged credential, connects to the Mac over SSH inside the tailnet, pulls that version, runs the
migrations and restarts the services (#166). Nobody deploys by hand.

**Backups.** A nightly `pg_dump` is written to iCloud Drive, so a copy leaves the machine, with a
retention rule and a restore tested into a clean database (#167).

**Uptime.** A free external monitor checks the public health endpoint every few minutes and
publishes the history, so the README can state real uptime rather than a promise.

**Ingestion.** Nothing moves: the laptop already ingests, so the PurpleAir budget is unchanged.
Development happens on the same machine, so local development must not stop the production
stack; the override runs under its own compose project name.

## Consequences

- $0, and still the parts that make it a real deployment: a public HTTPS address, a reverse proxy
  that hides internal tools, CI/CD, backups with a tested restore, and external uptime monitoring.
- Availability depends on one laptop. Sleep, travel and macOS updates cause downtime. The site
  says it is hosted on a home server, and the uptime monitor shows how often it is down.
- Production and development share one machine. Running tests or experiments uses the same CPU
  and memory, and a careless `docker compose down` stops production; the separate project name
  and the deployment guide (#168) guard against that.
- Funnel's traffic limits are unpublished. If the project ever gets real traffic, that is the
  signal to move to a VM, which the deployment guide is written to make routine.
- The tailnet name `tailbcc5c4` is random. A domain can replace it later without other changes.
