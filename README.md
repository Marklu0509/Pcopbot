# Pcopbot

An **event-driven processing system** that consumes a high-throughput public data stream, replicates actions through a downstream API under a configurable policy engine, and manages the full lifecycle of each resulting entity — built to practice fault-tolerant streaming, idempotent processing, and production observability on real-world data.

It runs 24/7 on a DigitalOcean droplet with automated CI/CD and full metrics-based monitoring.

![CI/CD](https://github.com/Marklu0509/Pcopbot/actions/workflows/deploy.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Tests](https://img.shields.io/badge/tests-85%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Why this project

[Polymarket](https://polymarket.com) exposes a **public, real-time, append-only event stream** (every action by every account) plus an order-placement API and an on-chain settlement layer. That combination makes it an ideal substrate for building and stress-testing a production data pipeline against messy, high-volume real-world data — fragmented events, API rate limits, floating-point precision constraints, eventual consistency, and failures that happen at 3 a.m. whether you're watching or not.

The domain (mirroring selected accounts' actions on prediction markets) is secondary; the focus is the **engineering**: ingesting an event stream exactly once, shaping outputs through a constraint engine, reconciling state against an external source of truth, and keeping the whole thing observable and self-deploying.

## What it does

The system tracks a set of accounts, polls a public API for their new actions, and replicates each one through an order API under per-account sizing and constraint policies. It then drives each resulting entity through its lifecycle — entry, conditional exit, and on-chain settlement once the underlying event resolves — and reconciles outcomes back into a dashboard.

```
Public event stream  ──poll──▶  Constraint engine (cap → reject)  ──▶  Order execution API
                                          │                                   │
                                  Event aggregation                   Entity lifecycle
                                  (sliding window)              (conditional exit, settlement)
                                          │                                   │
                                          └──────────▶  SQLite/Postgres  ◀─────┘
                                                              │
                                       Streamlit dashboard + Prometheus metrics
```

## Tech stack

| Layer | Technologies |
|-------|--------------|
| **Core** | Python 3.11, SQLAlchemy 2.0 (ORM), Web3.py |
| **Data** | SQLite (dev) / PostgreSQL (prod) |
| **Frontend** | Streamlit, Plotly |
| **Infra** | Docker Compose, Nginx (reverse proxy, TLS, rate limiting), Let's Encrypt |
| **CI/CD** | GitHub Actions (test → auto-deploy via SSH) |
| **Observability** | Prometheus, Grafana |
| **Testing** | pytest (85 tests) |

## Engineering highlights

The design decisions worth talking through in an interview:

- **Exactly-once stream processing** — a per-account timestamp *watermark* advances only after an event is fully processed, so no event is duplicated or lost across restarts. The system deliberately chooses *at-most-once* over *at-least-once* semantics, because in this domain a duplicated action is more expensive to recover from than a skipped one — a classic delivery-guarantee trade-off made explicit.

- **Policy-based constraint engine** — rather than a binary pass/fail filter, `cap_and_check()` first *shapes* each output to fit five exposure limits (per-action, cumulative, per-market, per-outcome, net-position), and only rejects when it still violates a price filter or a hard minimum. Shaping-before-rejecting keeps far more events actionable while staying within configured bounds.

- **Sliding-window event aggregation** — upstream actions arrive fragmented into many sub-events. `FillBuffer` accumulates them in a time-bounded window and emits a single aggregated output once their combined magnitude crosses a threshold, using volume-weighted averaging — collapsing dozens of tiny downstream calls into one.

- **Deterministic numeric handling** — the downstream API rejects values exceeding 2 decimal places. Output sizing uses integer truncation (`floor(x * 100) / 100`) instead of `round()` to satisfy the constraint deterministically. *Root-caused in production by instrumenting the failing path with structured logging* rather than guessing.

- **Zero-touch deployment** — every push to `main` runs the full test suite on GitHub Actions and, if green, SSHes into the droplet to pull and rebuild containers. No manual deploy steps, no drift between repo and server.

- **Production observability** — the daemon exports Prometheus metrics (throughput by outcome, poll-latency histograms, a liveness timestamp) rendered in a Grafana dashboard, so "is it actually healthy right now?" is answerable at a glance instead of by tailing logs.

## Quick start

```bash
# Local development (dry-run mode by default — no live actions are sent)
git clone https://github.com/Marklu0509/Pcopbot.git
cd Pcopbot
pip install -r requirements.txt
cp .env.example .env          # add your API credentials
python -m bot.main            # start the daemon
streamlit run dashboard/app.py  # dashboard, separate terminal

# Run the test suite
python -m pytest tests/ -v
```

```bash
# Production (Docker Compose: daemon + dashboard + nginx + prometheus + grafana)
docker compose up -d --build
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full technical deep-dive, and the
[Configuration](#configuration) section below for all tunable parameters.

## Project structure

```
bot/             Core processing logic
  main.py          Daemon poll loop, state reconciliation, lifecycle transitions
  tracker.py       Ingests events & entity state from the public API
  executor.py      Output execution, conditional exits, tiered exit rules
  risk.py          Cap-then-reject constraint engine (exposure caps + filters)
  fill_buffer.py   Sliding-window aggregation for fragmented events
  redeemer.py      On-chain settlement + reconciliation of out-of-band actions
  watermark.py     Per-account watermark (exactly-once processing)
  metrics.py       Prometheus metrics

config/          Environment-based settings loader
db/              SQLAlchemy models + session factory
dashboard/       Streamlit multi-page UI (password-gated)
scripts/         Maintenance utilities (run as python -m scripts.<name>)
nginx/           Reverse proxy: TLS, rate limiting, security headers
grafana/         Pre-built monitoring dashboard
tests/           pytest suite (85 tests)
```

## Configuration

Configured through environment variables (credentials, infra) and per-account settings
adjustable live from the dashboard (sizing, constraint limits, exit rules).

<details>
<summary><strong>Key environment variables</strong></summary>

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POLYMARKET_PRIVATE_KEY` | Yes | — | Wallet key for signing order-API requests |
| `POLYMARKET_API_KEY` / `_SECRET` / `_PASSPHRASE` | Yes | — | Order API credentials |
| `POLYMARKET_FUNDER_ADDRESS` | Yes | — | Address holding funds and tokens |
| `DATABASE_URL` | No | `sqlite:///./data/pcopbot.db` | SQLAlchemy database URL |
| `POLL_INTERVAL_SECONDS` | No | `15` | Seconds between poll cycles |
| `DRY_RUN` | No | `true` | Global dry-run override — `false` to send live actions |
| `DASHBOARD_PASSWORD` | No | — | Dashboard login password |
| `DOMAIN` | No | — | Domain for nginx TLS certificate |
| `GRAFANA_PASSWORD` | No | `changeme` | Grafana admin password |

Full list in [config/settings.py](config/settings.py).

</details>

<details>
<summary><strong>Per-account constraint & sizing settings</strong></summary>

Each tracked account has independent settings: sizing mode (fixed / proportional),
per-action and cumulative caps, per-market / per-outcome / net-position limits, value bands,
tolerance thresholds, tiered exit rules (`[{"max_entry": 0.30, "target": 0.80}]`),
event-aggregation windows, and a per-account dry-run toggle. Defined on the `Trader` model in
[db/models.py](db/models.py) and editable from the dashboard.

</details>

## License

MIT
