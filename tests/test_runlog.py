"""Tests for runlog module"""

import sqlite3

from youtube_summarizer.runlog import (
    db_path,
    format_usage_line,
    record_run,
    render_stats,
)


def _row(**overrides):
    row = {
        "video_id": "dQw4w9WgXcQ",
        "title": "My note",
        "topic": "LLM",
        "model": "anthropic:claude-haiku-5-5",
        "input_tokens": 1_000,
        "output_tokens": 100,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "requests": 1,
        "est_cost_usd": 0.00015,
        "duration_s": 2.0,
        "transcript_chars": 5_000,
        "summary_chars": 400,
        "status": "ok",
        "error": None,
    }
    row.update(overrides)
    return row


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id")]
    finally:
        conn.close()


class TestDbPath:
    """Tests for db_path function"""

    def test_env_override(self, isolated_run_log):
        """YTSUM_RUNS_DB overrides the default location"""
        assert db_path() == isolated_run_log

    def test_default_under_xdg_data_home(self, tmp_path, monkeypatch):
        """Without an override, the DB lives in $XDG_DATA_HOME/ytsum/runs.db"""
        monkeypatch.delenv("YTSUM_RUNS_DB")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert db_path() == tmp_path / "ytsum" / "runs.db"


class TestRecordRun:
    """Tests for record_run function"""

    def test_writes_row_with_all_fields(self, isolated_run_log):
        """A recorded run can be read back with a timestamp and version"""
        record_run(_row())

        rows = _rows(isolated_run_log)
        assert len(rows) == 1
        row = rows[0]
        assert row["video_id"] == "dQw4w9WgXcQ"
        assert row["model"] == "anthropic:claude-haiku-5-5"
        assert row["input_tokens"] == 1_000
        assert row["output_tokens"] == 100
        assert row["status"] == "ok"
        assert row["timestamp"].endswith("+00:00")
        assert row["ytsum_version"]

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        """The DB's folder is created on first write"""
        path = tmp_path / "nested" / "dir" / "runs.db"
        monkeypatch.setenv("YTSUM_RUNS_DB", str(path))
        record_run(_row())
        assert path.exists()

    def test_disabled_by_env_writes_nothing(self, isolated_run_log, monkeypatch):
        """YTSUM_NO_RUN_LOG=1 turns the log off"""
        monkeypatch.setenv("YTSUM_NO_RUN_LOG", "1")
        record_run(_row())
        assert not isolated_run_log.exists()

    def test_unwritable_path_only_warns(self, tmp_path, monkeypatch, capsys):
        """A DB that can't be written prints a warning instead of raising"""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setenv("YTSUM_RUNS_DB", str(blocker / "runs.db"))

        record_run(_row())

        assert "Warning: could not write run log" in capsys.readouterr().err


class TestFormatUsageLine:
    """Tests for format_usage_line function"""

    def test_with_cost(self):
        line = format_usage_line(12_345, 678, 0.0123, 4.21)
        assert line == "Tokens: 12,345 in / 678 out · ~$0.0123 · 4.2s"

    def test_unknown_cost(self):
        line = format_usage_line(10, 5, None, 1.0)
        assert line == "Tokens: 10 in / 5 out · cost unknown · 1.0s"


class TestRenderStats:
    """Tests for render_stats function"""

    def test_no_runs_yet(self):
        assert "No runs recorded yet" in render_stats()

    def test_aggregates_by_model(self):
        """Per-model lines count ok runs and errors, and total the cost"""
        record_run(_row(est_cost_usd=0.01))
        record_run(_row(est_cost_usd=0.03))
        record_run(_row(status="error", error="boom", input_tokens=None, output_tokens=None, est_cost_usd=None))
        record_run(_row(model="anthropic:claude-sonnet-5-5", est_cost_usd=0.50))

        out = render_stats()
        haiku = next(l for l in out.splitlines() if l.startswith("anthropic:claude-haiku-5-5"))
        sonnet = next(l for l in out.splitlines() if l.startswith("anthropic:claude-sonnet-5-5"))
        # runs, errors, ..., avg cost, total cost
        assert haiku.split()[1:3] == ["2", "1"]
        assert "$0.0200" in haiku and "$0.0400" in haiku
        assert "$0.5000" in sonnet

    def test_lists_recent_runs(self):
        """The 10 most recent runs are listed, newest first"""
        for i in range(12):
            record_run(_row(title=f"note-{i}"))

        recent = render_stats().split("Recent runs")[1]
        titles = [w for w in recent.split() if w.startswith("note-")]
        assert titles == [f"note-{i}" for i in range(11, 1, -1)]
