"""Prometheus metrics for the Pcopbot trading daemon."""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Total copy trades executed, labelled by side and final status.
trades_total = Counter(
    "pcopbot_trades_total",
    "Total copy trades processed",
    ["side", "status"],
)

# How long each full poll cycle takes (seconds).
poll_duration_seconds = Histogram(
    "pcopbot_poll_duration_seconds",
    "Time spent executing one poll cycle",
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

# Number of active traders currently being tracked.
active_traders = Gauge(
    "pcopbot_active_traders",
    "Number of active traders being polled",
)

# Unix timestamp of the last successful poll cycle.
last_poll_timestamp = Gauge(
    "pcopbot_last_poll_timestamp_seconds",
    "Unix timestamp of the last completed poll cycle",
)

# Current size of the in-memory fill aggregation buffer.
fill_buffer_size = Gauge(
    "pcopbot_fill_buffer_size",
    "Number of token slots currently buffering fills",
)


def start_metrics_server(port: int = 8000) -> None:
    """Expose metrics on http://0.0.0.0:<port>/metrics."""
    start_http_server(port)
