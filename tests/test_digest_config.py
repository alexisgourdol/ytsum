"""Tests for digest config, data dir, env file loading and CLI dispatch"""

import sys

import pytest

from youtube_summarizer.digest.config import Config, data_dir, load_config, load_env_file


def test_load_config_defaults(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg == Config()
    assert cfg.daily_cap == 10
    assert cfg.mode == "api"
    assert cfg.deep_dive_model == "claude-sonnet-5-5"
    assert cfg.summary_model == "claude-haiku-5-5"
    assert cfg.per_channel_cap == 2
    assert cfg.deep_dive_cap == 3


def test_load_config_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('daily_cap = 5\nmode = "subscription"\nvault_dir = "~/vault"\n')
    cfg = load_config(path)
    assert cfg.daily_cap == 5
    assert cfg.mode == "subscription"
    assert str(cfg.vault_dir).endswith("/vault") and "~" not in str(cfg.vault_dir)


def test_load_config_unknown_key(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("dialy_cap = 5\n")
    with pytest.raises(ValueError, match="dialy_cap"):
        load_config(path)


def test_load_config_ignores_retired_refresh_days(tmp_path):
    """refresh_days set the channel auto-refresh, removed in SCP-78."""
    path = tmp_path / "config.toml"
    path.write_text("refresh_days = 30\ndaily_cap = 5\n")
    cfg = load_config(path)
    assert cfg.daily_cap == 5 and not hasattr(cfg, "refresh_days")


def test_load_config_reads_data_dir_by_default(isolated_run_log):
    (isolated_run_log.parent / "digest").mkdir()
    (isolated_run_log.parent / "digest" / "config.toml").write_text("daily_cap = 7\n")
    assert load_config().daily_cap == 7


def test_data_dir_follows_runs_db(isolated_run_log):
    assert data_dir() == isolated_run_log.parent / "digest"
    assert data_dir().is_dir()


def test_load_env_file_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / "secrets.env"
    env.write_text('# comment\n\nYT_TEST_A="quoted"\nYT_TEST_B=new\n')
    monkeypatch.delenv("YT_TEST_A", raising=False)
    monkeypatch.setenv("YT_TEST_B", "kept")
    load_env_file(env)
    import os
    assert os.environ["YT_TEST_A"] == "quoted"
    assert os.environ["YT_TEST_B"] == "kept"


def test_load_env_file_missing_is_noop(tmp_path):
    load_env_file(tmp_path / "nope.env")


def test_cli_dispatches_digest(mocker, monkeypatch):
    from youtube_summarizer import cli

    digest_main = mocker.patch("youtube_summarizer.digest.cli.main", return_value=0)
    monkeypatch.setattr(sys, "argv", ["youtube-summarizer", "digest", "--once-per-day"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    digest_main.assert_called_once_with(["--once-per-day"])


def test_load_config_delay_bounds(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("feed_delay_s = [1, 2]\n")
    cfg = load_config(path)
    assert cfg.feed_delay_s == (1, 2) and cfg.transcript_delay_s == (40, 70)
    path.write_text("feed_delay_s = [9, 2]\n")
    with pytest.raises(ValueError, match="feed_delay_s"):
        load_config(path)
