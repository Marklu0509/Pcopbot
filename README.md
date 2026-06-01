# Pcopbot

**A real-time automation service built on the [Polymarket](https://polymarket.com) public API.** It watches a configurable set of accounts, mirrors their activity through the exchange API under a rules engine, and manages each resulting item through its full lifecycle — all observable from a web dashboard.

Ships as a self-contained Docker Compose stack: bot, dashboard, reverse proxy, and a metrics/monitoring layer. Runs on any host with a Docker runtime.

![CI/CD](https://github.com/Marklu0509/Pcopbot/actions/workflows/deploy.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Tests](https://img.shields.io/badge/tests-85%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How it works

```
Polymarket public feed  ──poll──▶  Rules engine (cap → reject)  ──▶  Exchange API
                                          │                               │
                                   Event aggregation               Item lifecycle
                                   (sliding window)           (auto-exit, on-chain settle)
                                          │                               │
                                          └──────────▶  SQLite / Postgres  ◀┘
                                                              │
                                       Streamlit dashboard + Prometheus metrics
```

1. **Track** — register any number of accounts to follow, each with its own rules.
2. **Poll** — read the public feed continuously (multiple times a second) for new activity.
3. **Filter & size** — pass each candidate through a rules engine that resizes it to fit your configured limits, or skips it.
4. **Act** — submit the request through the exchange (CLOB) API.
5. **Manage** — apply rule-based exits and trigger on-chain settlement once a market resolves.
6. **Monitor** — review everything from a password-protected dashboard, with live metrics in Grafana.

> Runs in **dry-run mode** by default: it logs exactly what it *would* do without sending anything live, so you can watch the full pipeline work safely first.

## Why this project

I wanted a real, always-on system to practice production engineering on — not a tutorial app. Polymarket fits well because it exposes a **public, real-time feed of every action**, a live API, and an on-chain settlement layer. That combination surfaces the messy problems a real backend has to survive: fragmented data, API rate limits, floating-point precision rules, eventual consistency, and failures that happen at 3 a.m. whether you're watching or not.

The domain is really just the test case. The work went into the engineering underneath — consuming a live feed exactly once, shaping output through a rules engine, reconciling state against an external source of truth, and keeping the whole thing observable and self-deploying.

## Features

- **Multi-account tracking** with independent per-account rules
- **Rules engine** that resizes requests to fit configured limits instead of dropping them
- **Event aggregation** that batches fragmented sub-events into one
- **Automated lifecycle management** — rule-based exits and on-chain settlement
- **Web dashboard** for live monitoring and runtime configuration (no redeploys)
- **Metrics, monitoring & alerting** via Prometheus + Grafana (with Discord alerts), all provisioned as code
- **Containerized** — one command to bring up the whole stack
- **CI/CD** — tests run and the service redeploys itself on every push

## Tech stack

| Layer | Technologies |
|-------|--------------|
| **Core** | Python 3.11, SQLAlchemy 2.0 (ORM), Web3.py |
| **Data** | SQLite (dev) / PostgreSQL (prod) |
| **Frontend** | Streamlit, Plotly |
| **Infra** | Docker Compose, Nginx (reverse proxy, TLS, rate limiting), Let's Encrypt |
| **CI/CD** | GitHub Actions (test → auto-deploy via SSH) |
| **Observability** | Prometheus, Grafana (dashboards + alerting, provisioned as code) |
| **Testing** | pytest (85 tests) |

## Getting started

**Requirements:** Python 3.11+ (local) or Docker (full stack).

### Run locally

```bash
git clone https://github.com/Marklu0509/Pcopbot.git
cd Pcopbot
pip install -r requirements.txt

cp .env.example .env            # fill in your API credentials
python -m bot.main              # start the bot
streamlit run dashboard/app.py  # open the dashboard (separate terminal)
```

Open the dashboard, register an account to follow, and watch the log fill with what the
bot *would* do. It stays in dry-run mode until you set `DRY_RUN=false`.

```bash
python -m pytest tests/ -v      # run the test suite
```

### Run the full stack (Docker)

Brings up everything — bot, dashboard, Nginx, Prometheus, Grafana — in one command:

```bash
cp .env.example .env            # configure credentials and settings
docker compose up -d --build
```

| Service | URL (default) |
|---------|---------------|
| Dashboard | `http://localhost/` |
| Grafana | `http://localhost/grafana/` |

## Deployment

The stack is host-agnostic — it runs anywhere with a Docker runtime (a small 1 GB VPS is
enough). To deploy:

1. Install Docker + Docker Compose on the host.
2. Clone the repo and add a `.env` file with your credentials.
3. Set `DOMAIN` to enable automatic HTTPS (Let's Encrypt via the bundled Nginx + Certbot).
4. `docker compose up -d --build`.

A GitHub Actions workflow ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml))
automates this: on every push to `main` it runs the test suite and, if green, connects to the
deployment host over SSH to pull and rebuild. Host address and SSH key are stored as
repository secrets — nothing sensitive lives in the repo.

## Configuration

Infrastructure and credentials are set via environment variables; per-account behavior
(sizing, limits, exit rules) is editable live from the dashboard — no restart needed.

<details>
<summary><strong>Key environment variables</strong></summary>

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POLYMARKET_PRIVATE_KEY` | Yes | — | Key for signing API requests |
| `POLYMARKET_API_KEY` / `_SECRET` / `_PASSPHRASE` | Yes | — | Exchange API credentials |
| `POLYMARKET_FUNDER_ADDRESS` | Yes | — | Address holding funds and tokens |
| `DATABASE_URL` | No | `sqlite:///./data/pcopbot.db` | SQLAlchemy database URL |
| `POLL_INTERVAL_SECONDS` | No | `0.5` | Seconds between poll cycles |
| `DRY_RUN` | No | `true` | Global dry-run switch — `false` to act live |
| `DASHBOARD_PASSWORD` | No | — | Dashboard login password |
| `DOMAIN` | No | — | Domain for Nginx TLS certificate |
| `GRAFANA_PASSWORD` | No | `changeme` | Grafana admin password |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook for liveness alerts |

Full list in [config/settings.py](config/settings.py).

</details>

<details>
<summary><strong>Per-account settings</strong></summary>

Each tracked account has independent settings: sizing mode (fixed / proportional),
per-action and cumulative caps, per-market / per-outcome / net limits, value bands,
tolerance thresholds, tiered exit rules (`[{"max_entry": 0.30, "target": 0.80}]`),
aggregation windows, and a per-account dry-run toggle. Defined on the `Trader` model in
[db/models.py](db/models.py) and editable from the dashboard.

</details>

## Engineering highlights

A few of the more interesting problems this project solves:

- **Processing each event exactly once** — a per-account timestamp *watermark* only advances after an event is fully processed, so nothing is duplicated or lost when the service restarts. It intentionally favors *skipping* over *double-processing*, because a duplicated action is far more painful to unwind than a missed one — a deliberate trade-off, not an accident.

- **Resizing instead of rejecting** — the rules engine (`cap_and_check()`) doesn't just pass or fail an item. It first *shrinks* it to fit five limits (per-action, cumulative, per-market, per-outcome, net), and only rejects it if it still breaks a value filter or falls below a hard minimum. Shaping-before-rejecting keeps far more items usable while staying within the bounds you set.

- **Batching fragmented events** — a single upstream action often arrives split into dozens of tiny sub-events. `FillBuffer` collects them in a short time window and combines them into one weighted-average request once they cross a threshold — turning dozens of tiny API calls into one.

- **A precision bug, debugged properly** — the API silently rejected any amount with more than 2 decimal places. The fix was switching from `round()` to integer truncation (`floor(x * 100) / 100`), but the real lesson was *finding* it: I added structured logging to the failing path and let the data show the root cause, instead of guessing.

- **Push-to-deploy** — every push to `main` runs the full test suite on GitHub Actions; if it passes, it connects to the host, pulls the new code, and rebuilds the containers. No manual steps, no "works on my machine" drift.

- **Knowing it's healthy without watching it** — the service exports its own metrics (throughput by outcome, poll-latency histograms, a last-seen-alive timestamp) to Prometheus and Grafana, so one dashboard answers "is it running right now?" — no log-tailing required. A Grafana alert pings a Discord channel if the service goes quiet, so a stall surfaces on its own instead of being noticed hours later.

- **Monitoring defined as code** — the Grafana data source, dashboard, alert rules, and notification routing all live in version-controlled config files under `grafana/provisioning/`. A fresh deploy rebuilds the entire monitoring setup automatically — no clicking through a UI to wire it back up.

## Project structure

```
bot/             Core processing logic
  main.py          Daemon poll loop, state reconciliation, lifecycle transitions
  tracker.py       Ingests events & state from the public API
  executor.py      Action execution, rule-based exits, tiered exit rules
  risk.py          Cap-then-reject rules engine (limits + filters)
  fill_buffer.py   Sliding-window aggregation for fragmented events
  redeemer.py      On-chain settlement + reconciliation of out-of-band actions
  watermark.py     Per-account watermark (exactly-once processing)
  metrics.py       Prometheus metrics

config/          Environment-based settings loader
db/              SQLAlchemy models + session factory
dashboard/       Streamlit multi-page UI (password-gated)
scripts/         Maintenance utilities (run as python -m scripts.<name>)
nginx/           Reverse proxy: TLS, rate limiting, security headers
grafana/         Dashboard, data source, and alert rules — all provisioned as code
tests/           pytest suite (85 tests)
```

## License

MIT
