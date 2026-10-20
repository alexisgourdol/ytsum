"""Tests for the digest's LLM backends (api / subscription) and their run-log rows"""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from youtube_summarizer.digest import llm

CLAUDE_JSON = {
    "type": "result", "subtype": "success", "is_error": False, "result": "hello",
    "duration_ms": 1200,
    "usage": {"input_tokens": 10, "cache_read_input_tokens": 5000,
              "cache_creation_input_tokens": 200, "output_tokens": 300},
}


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id")]
    finally:
        conn.close()


def _completed(stdout, returncode=0, stderr=""):
    return MagicMock(stdout=stdout, returncode=returncode, stderr=stderr)


def test_subscription_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    env = llm.subscription_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["YTSUM_DIGEST_CHILD"] == "1"


def test_subscription_never_uses_bare():
    cmd = llm.subscription_command("claude-haiku-5-5", "sys")
    assert "--bare" not in cmd
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--system-prompt") + 1] == "sys"
    assert cmd[cmd.index("--output-format") + 1] == "json"


def test_subscription_parses_json_and_logs(mocker, isolated_run_log, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    run = mocker.patch("subprocess.run", return_value=_completed(json.dumps(CLAUDE_JSON)))

    r = llm.complete("sys", "user text", model="claude-haiku-5-5", mode="subscription",
                     kind="summary", video_id="vid", title="T")

    assert r.text == "hello"
    assert r.input_tokens == 5210
    assert r.output_tokens == 300
    assert r.log_model == "claude-code:claude-haiku-5-5"
    kwargs = run.call_args.kwargs
    assert kwargs["input"] == "user text"
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    rows = _rows(isolated_run_log)
    assert len(rows) == 1
    row = rows[0]
    assert (row["model"], row["kind"], row["status"]) == ("claude-code:claude-haiku-5-5", "summary", "ok")
    assert (row["input_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]) == (5210, 5000, 200)
    assert row["video_id"] == "vid" and row["topic"] == "digest"
    assert row["est_cost_usd"] is not None


def test_subscription_error_logged(mocker, isolated_run_log):
    mocker.patch("subprocess.run", return_value=_completed(json.dumps({**CLAUDE_JSON, "is_error": True, "result": "rate limited"})))
    with pytest.raises(llm.LlmError, match="rate limited"):
        llm.complete("s", "u", model="claude-haiku-5-5", mode="subscription", kind="judge")
    assert _rows(isolated_run_log)[0]["status"] == "error"


def test_subscription_nonzero_exit_is_error(mocker, isolated_run_log):
    mocker.patch("subprocess.run", return_value=_completed("", returncode=1, stderr="not logged in"))
    with pytest.raises(llm.LlmError, match="not logged in"):
        llm.complete("s", "u", model="claude-haiku-5-5", mode="subscription", kind="judge")


def test_api_backend_logs_anthropic_model(mocker, isolated_run_log):
    usage = MagicMock(input_tokens=1000, output_tokens=100, cache_read_tokens=0, cache_write_tokens=0, requests=1)
    sr = mocker.patch("youtube_summarizer.summarizer.summarize_run",
                      return_value=MagicMock(output="sum", usage=usage, duration_s=1.5))

    r = llm.complete("sys", "user", model="claude-haiku-5-5", mode="api", kind="summary")

    assert r.text == "sum"
    sr.assert_called_once_with("user", model="anthropic:claude-haiku-5-5", system_prompt="sys", user_prefix="")
    row = _rows(isolated_run_log)[0]
    assert (row["model"], row["kind"], row["input_tokens"]) == ("anthropic:claude-haiku-5-5", "summary", 1000)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        llm.complete("s", "u", model="m", mode="cloud", kind="judge")
