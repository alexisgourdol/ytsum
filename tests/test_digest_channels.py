"""Tests for the channel list file"""

from datetime import datetime, timedelta, timezone

import pytest

from youtube_summarizer.digest import channels as ch
from youtube_summarizer.digest.config import Config, data_dir
from youtube_summarizer.digest.state import State
from youtube_summarizer.digest.youtube import FeedEntry

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def test_channels_roundtrip():
    chs = [
        ch.Channel("UC1", 'Nate Herk | AI "Automation"', "vault"),
        ch.Channel("UC2", "Back\\slash", "discovery"),
    ]
    ch.save_channels(chs)
    assert ch.load_channels() == chs


def test_load_channels_missing_is_empty():
    assert ch.load_channels() == []


def test_load_channels_reads_old_pinned_flag():
    """channels.toml files written before SCP-78 carry pinned = true/false."""
    (data_dir() / "channels.toml").write_text(
        '# Set pinned = true to keep a channel through monthly refreshes.\n\n'
        '[[channel]]\nchannel_id = "UC1"\nname = "One"\nbucket = "discovery"\npinned = true\n')
    assert ch.load_channels() == [ch.Channel("UC1", "One", "discovery")]
    ch.save_channels(ch.load_channels())
    text = (data_dir() / "channels.toml").read_text()
    assert "pinned" not in text and "refresh" not in text


def _feed(cid, days_ago):
    return [FeedEntry(f"{cid}-v", cid, cid, "t", (NOW - timedelta(days=days_ago)).isoformat(), "")]


def test_stale_lines_flag_channels_quiet_for_90_days():
    chs = [ch.Channel("UCfresh", "Fresh", "vault"), ch.Channel("UCold", "Old", "discovery"),
           ch.Channel("UCempty", "Empty", "news"), ch.Channel("UCunread", "Unread", "labs")]
    feeds = {"UCfresh": _feed("UCfresh", 89), "UCold": _feed("UCold", 91), "UCempty": []}
    assert ch.stale_lines(chs, feeds, NOW) == [
        "? Old (discovery): no uploads for 90 days — consider replacing it",
        "? Empty (news): no uploads for 90 days — consider replacing it",
    ]  # an unreadable feed is already listed under Failures


def test_stale_check_is_monthly():
    assert ch.stale_check_due(State(), NOW)
    assert not ch.stale_check_due(State(last_stale_check="2026-09-22"), NOW)  # 29 days
    assert ch.stale_check_due(State(last_stale_check="2026-09-21"), NOW)  # 30 days


@pytest.mark.parametrize("ref,param,value", [
    ("https://www.youtube.com/@NateHerk", "forHandle", "@NateHerk"),
    ("@samwitteveenai", "forHandle", "@samwitteveenai"),
    ("https://www.youtube.com/channel/UC55ODQSvARtgSyc8ThfiepQ", "id", "UC55ODQSvARtgSyc8ThfiepQ"),
    ("UC55ODQSvARtgSyc8ThfiepQ", "id", "UC55ODQSvARtgSyc8ThfiepQ"),
])
def test_resolve_handle_and_id(mocker, ref, param, value):
    get = mocker.patch("youtube_summarizer.digest.youtube.api_get",
                       return_value={"items": [{"id": "UCresolved", "snippet": {"title": "Resolved Name"}}]})
    c = ch.resolve_channel(ref, api_key="k", bucket="news")
    assert c == ch.Channel("UCresolved", "Resolved Name", "news")
    assert get.call_args.args[1][param] == value


def test_resolve_not_found(mocker):
    mocker.patch("youtube_summarizer.digest.youtube.api_get", return_value={"items": []})
    with pytest.raises(ValueError, match="@nobody"):
        ch.resolve_channel("@nobody", api_key="k")


def test_cli_channels_add_dedupes_and_list(mocker, monkeypatch, capsys):
    from youtube_summarizer.digest import cli
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    mocker.patch.object(cli, "load_config", return_value=Config(env_file=Config().env_file.with_name("none")))
    mocker.patch("youtube_summarizer.digest.youtube.api_get",
                 return_value={"items": [{"id": "UCsam", "snippet": {"title": "Sam Witteveen"}}]})
    assert cli.main(["channels", "add", "https://www.youtube.com/@samwitteveenai", "--bucket", "vault"]) == 0
    assert cli.main(["channels", "add", "@samwitteveenai", "--bucket", "vault"]) == 0
    assert ch.load_channels() == [ch.Channel("UCsam", "Sam Witteveen", "vault")]
    assert "already" in capsys.readouterr().out

    feed = [FeedEntry("x", "UCsam", "Sam", "t", "2026-10-20T10:00:00+00:00", "")]
    mocker.patch("youtube_summarizer.digest.youtube.fetch_feed", return_value=feed)
    assert cli.main(["channels", "list"]) == 0
    out = capsys.readouterr().out
    assert "Sam Witteveen" in out and "vault" in out and "2026-10-20" in out


def test_cli_channels_add_needs_youtube_key(mocker, monkeypatch, capsys):
    from youtube_summarizer.digest import cli
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    mocker.patch.object(cli, "load_config", return_value=Config(env_file=Config().env_file.with_name("none")))
    assert cli.main(["channels", "add", "@x", "--bucket", "news"]) == 1
    assert "YOUTUBE_API_KEY" in capsys.readouterr().out
