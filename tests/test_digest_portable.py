"""ytsum works from a plain install: bundled template, pause and vault_dir enforced by the CLI (SCP-79)."""

from datetime import date, datetime, timedelta

import pytest

from youtube_summarizer.digest import cli, notes
from youtube_summarizer.digest import state as st
from youtube_summarizer.digest.config import Config, data_dir


def test_bundled_prompt_needs_no_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    text = notes.bundled_deep_dive_prompt()
    assert "Quick Reference" in text
    assert "ignore the fetch" not in text.lower()


@pytest.mark.parametrize("word", ["alexis", "general-kb", "obsidian", "workspace-external", "ytsum_save_dir"])
def test_bundled_prompt_is_generic(word):
    assert word not in notes.bundled_deep_dive_prompt().lower()


def test_paused_until(tmp_path):
    today = date(2026, 11, 8)
    assert st.paused_until(today) is None
    path = data_dir() / "paused_until"
    path.write_text("2026-11-09\n")
    assert st.paused_until(today) == date(2026, 11, 9)
    path.write_text("2026-11-08\n")
    assert st.paused_until(today) is None  # the date itself is a run day, as in the hook
    path.write_text("not a date\n")
    assert st.paused_until(today) is None


def test_digest_skips_while_paused(tmp_path, mocker, capsys):
    mocker.patch.object(cli, "load_config", return_value=Config(vault_dir=tmp_path))
    run = mocker.patch("youtube_summarizer.digest.pipeline.run_digest")
    until = datetime.now().date() + timedelta(days=3)
    (data_dir() / "paused_until").write_text(until.isoformat() + "\n")
    assert cli.main([]) == 0
    run.assert_not_called()
    out = capsys.readouterr().out
    assert f"paused until {until.isoformat()}" in out and "paused_until" in out


def test_digest_without_vault_dir_stops(mocker, capsys):
    mocker.patch.object(cli, "load_config", return_value=Config())
    run = mocker.patch("youtube_summarizer.digest.pipeline.run_digest")
    assert cli.main(["--once-per-day"]) == 1
    run.assert_not_called()
    assert "Set vault_dir in" in capsys.readouterr().out
