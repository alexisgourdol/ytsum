"""
Local run log: one row per summarization run in a SQLite database,
so token usage, cost and timing can be compared across models over time.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

COLUMNS = [
    "timestamp", "video_id", "title", "topic", "model",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "requests",
    "est_cost_usd", "duration_s", "transcript_chars", "summary_chars",
    "status", "error", "ytsum_version",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          TEXT NOT NULL,
    video_id           TEXT,
    title              TEXT,
    topic              TEXT,
    model              TEXT NOT NULL,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER,
    requests           INTEGER,
    est_cost_usd       REAL,
    duration_s         REAL,
    transcript_chars   INTEGER,
    summary_chars      INTEGER,
    status             TEXT NOT NULL,
    error              TEXT,
    ytsum_version      TEXT
)
"""

RECENT_RUNS = 10


def db_path() -> Path:
    """Location of the run log: $YTSUM_RUNS_DB, else $XDG_DATA_HOME/ytsum/runs.db."""
    override = os.environ.get("YTSUM_RUNS_DB")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "ytsum" / "runs.db"


def _ytsum_version() -> str:
    try:
        return version("youtube-summarizer")
    except PackageNotFoundError:
        return "unknown"


def record_run(row: dict) -> None:
    """
    Append one run to the log. Never raises: a failed write only prints a warning.

    Args:
        row: Values for COLUMNS; timestamp and ytsum_version are filled in.
             Missing keys are stored as NULL.
    """
    if os.environ.get("YTSUM_NO_RUN_LOG"):
        return

    values = {c: row.get(c) for c in COLUMNS}
    values["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    values["ytsum_version"] = _ytsum_version()

    path = db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            with conn:
                conn.execute(SCHEMA)
                conn.execute(
                    f"INSERT INTO runs ({', '.join(COLUMNS)}) "
                    f"VALUES ({', '.join(':' + c for c in COLUMNS)})",
                    values,
                )
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as e:
        print(f"Warning: could not write run log at {path}: {e}", file=sys.stderr)


def _cost(value: Optional[float]) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def format_usage_line(
    input_tokens: int,
    output_tokens: int,
    cost: Optional[float],
    duration_s: float,
) -> str:
    """One-line usage summary printed after each run."""
    cost_text = "cost unknown" if cost is None else f"~${cost:.4f}"
    return f"Tokens: {input_tokens:,} in / {output_tokens:,} out · {cost_text} · {duration_s:.1f}s"


def _num(value: Optional[float]) -> str:
    return "-" if value is None else f"{round(value):,}"


def _secs(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.1f}s"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    return ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in [header, *rows]]


def render_stats(path: Optional[Path] = None) -> str:
    """Per-model totals and the most recent runs, as plain text."""
    path = path or db_path()
    if not path.exists():
        return f"No runs recorded yet (run log: {path})"

    conn = sqlite3.connect(path)
    try:
        conn.execute(SCHEMA)
        by_model = conn.execute(
            """
            SELECT model,
                   SUM(status = 'ok'), SUM(status = 'error'),
                   AVG(CASE WHEN status = 'ok' THEN input_tokens END),
                   AVG(CASE WHEN status = 'ok' THEN output_tokens END),
                   AVG(CASE WHEN status = 'ok' THEN est_cost_usd END),
                   SUM(est_cost_usd),
                   AVG(CASE WHEN status = 'ok' THEN duration_s END),
                   MIN(timestamp), MAX(timestamp)
            FROM runs GROUP BY model ORDER BY MAX(timestamp) DESC
            """
        ).fetchall()
        recent = conn.execute(
            "SELECT timestamp, model, status, input_tokens, output_tokens, est_cost_usd, "
            "duration_s, video_id, title FROM runs ORDER BY id DESC LIMIT ?",
            (RECENT_RUNS,),
        ).fetchall()
    finally:
        conn.close()

    if not by_model:
        return f"No runs recorded yet (run log: {path})"

    lines = [f"Run log: {path}", ""]
    lines += _table(
        ["model", "runs", "errors", "avg in", "avg out", "avg cost", "total cost", "avg time", "first", "last"],
        [
            [model, str(ok), str(err), _num(avg_in), _num(avg_out), _cost(avg_cost),
             _cost(total_cost), _secs(avg_time), first[:10], last[:10]]
            for model, ok, err, avg_in, avg_out, avg_cost, total_cost, avg_time, first, last in by_model
        ],
    )
    lines += ["", f"Recent runs (last {RECENT_RUNS}, UTC)"]
    lines += _table(
        ["when", "model", "status", "in", "out", "cost", "time", "video", "title"],
        [
            [ts[:16].replace("T", " "), model, status, _num(tin), _num(tout), _cost(cost),
             _secs(secs), video_id or "-", title or "-"]
            for ts, model, status, tin, tout, cost, secs, video_id, title in recent
        ],
    )
    return "\n".join(lines)
