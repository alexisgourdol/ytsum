"""Tests for the channel list file"""

from youtube_summarizer.digest import channels as ch


def test_channels_roundtrip():
    chs = [
        ch.Channel("UC1", 'Nate Herk | AI "Automation"', "vault", pinned=True),
        ch.Channel("UC2", "Back\\slash", "discovery"),
    ]
    ch.save_channels(chs)
    assert ch.load_channels() == chs


def test_load_channels_missing_is_empty():
    assert ch.load_channels() == []


import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.state import State
from youtube_summarizer.digest.youtube import FeedEntry, VideoMeta

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("ref,param,value", [
    ("https://www.youtube.com/@NateHerk", "forHandle", "@NateHerk"),
    ("@samwitteveenai", "forHandle", "@samwitteveenai"),
    ("https://www.youtube.com/channel/UC55ODQSvARtgSyc8ThfiepQ", "id", "UC55ODQSvARtgSyc8ThfiepQ"),
    ("UC55ODQSvARtgSyc8ThfiepQ", "id", "UC55ODQSvARtgSyc8ThfiepQ"),
])
def test_resolve_handle_and_id(mocker, ref, param, value):
    get = mocker.patch("youtube_summarizer.digest.youtube.api_get",
                       return_value={"items": [{"id": "UCresolved", "snippet": {"title": "Resolved Name"}}]})
    c = ch.resolve_channel(ref, api_key="k", bucket="news", pinned=True)
    assert c == ch.Channel("UCresolved", "Resolved Name", "news", True)
    assert get.call_args.args[1][param] == value


def test_resolve_not_found(mocker):
    mocker.patch("youtube_summarizer.digest.youtube.api_get", return_value={"items": []})
    with pytest.raises(ValueError, match="@nobody"):
        ch.resolve_channel("@nobody", api_key="k")


def test_refresh_not_due(mocker):
    get = mocker.patch("youtube_summarizer.digest.youtube.api_get")
    state = State(last_refresh=(NOW - timedelta(days=10)).date().isoformat())
    assert ch.maybe_refresh(Config(), state, NOW, "k") == []
    get.assert_not_called()


def _search_reply(query_channels):
    items = []
    for cid, n in query_channels:
        for i in range(n):
            items.append({"id": {"videoId": f"{cid}-v{i}"},
                          "snippet": {"channelId": cid, "channelTitle": f"Name {cid}",
                                      "title": f"AI video {i}", "description": "d"}})
    return {"items": items}


@pytest.fixture
def refresh_world(mocker):
    ch.save_channels([
        ch.Channel("UCvault", "Vault", "vault"),
        ch.Channel("UCpin", "Pinned discovery", "discovery", pinned=True),
        ch.Channel("UCold", "Old discovery", "discovery"),
    ])
    replies = _search_reply([("UCnew1", 3), ("UCnew2", 2), ("UCnew3", 1), ("UCvault", 4)])
    mocker.patch("youtube_summarizer.digest.youtube.api_get", return_value=replies)
    views = {"UCnew1": 1000, "UCnew2": 5000}
    mocker.patch("youtube_summarizer.digest.youtube.fetch_video_meta",
                 side_effect=lambda ids, api_key: {i: VideoMeta(i, 600, False, views[i.split("-")[0]]) for i in ids})
    fresh = [FeedEntry("x", "UCvault", "Vault", "t", (NOW - timedelta(days=3)).isoformat(), "")]
    mocker.patch("youtube_summarizer.digest.youtube.fetch_feed", return_value=fresh)

    def fake_judge(items, cfg):
        from youtube_summarizer.digest.judge import Verdict
        return {e.video_id: Verdict(e.video_id, True, False, "ai") for e, _ in items}
    mocker.patch("youtube_summarizer.digest.judge.judge", side_effect=fake_judge)


def test_refresh_replaces_unpinned_discovery_only(refresh_world):
    state = State()
    lines = ch.maybe_refresh(Config(), state, NOW, "k")
    chs = {c.channel_id: c for c in ch.load_channels()}
    assert set(chs) == {"UCvault", "UCpin", "UCnew2", "UCnew1"}  # 3 discovery slots: 1 pinned + top 2
    assert chs["UCnew2"].bucket == "discovery"
    assert any(l.startswith("+ Name UCnew2") and "5,000" in l for l in lines)
    assert any(l.startswith("− Old discovery") for l in lines)
    assert not any("UCnew3" in l for l in lines)  # only 1 on-topic video
    assert state.last_refresh == "2026-10-21"


def test_stale_channel_is_reported_not_removed(refresh_world, mocker):
    old = [FeedEntry("x", "UCvault", "Vault", "t", (NOW - timedelta(days=120)).isoformat(), "")]
    mocker.patch("youtube_summarizer.digest.youtube.fetch_feed", return_value=old)
    lines = ch.maybe_refresh(Config(), State(), NOW, "k")
    assert any("Vault" in l and "90 days" in l for l in lines)
    assert "UCvault" in {c.channel_id for c in ch.load_channels()}


def test_refresh_failure_is_reported_and_retried(mocker):
    from youtube_summarizer.digest.youtube import YouTubeApiError
    ch.save_channels([ch.Channel("UCvault", "Vault", "vault")])
    mocker.patch("youtube_summarizer.digest.youtube.api_get", side_effect=YouTubeApiError("quotaExceeded"))
    state = State()
    lines = ch.maybe_refresh(Config(), state, NOW, "k")
    assert any("quotaExceeded" in l for l in lines)
    assert state.last_refresh == ""


def test_cli_channels_add_dedupes_and_list(mocker, monkeypatch, capsys):
    from youtube_summarizer.digest import cli
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    mocker.patch.object(cli, "load_config", return_value=Config(env_file=Config().env_file.with_name("none")))
    mocker.patch("youtube_summarizer.digest.youtube.api_get",
                 return_value={"items": [{"id": "UCsam", "snippet": {"title": "Sam Witteveen"}}]})
    assert cli.main(["channels", "add", "https://www.youtube.com/@samwitteveenai", "--bucket", "vault", "--pin"]) == 0
    assert cli.main(["channels", "add", "@samwitteveenai", "--bucket", "vault"]) == 0
    assert ch.load_channels() == [ch.Channel("UCsam", "Sam Witteveen", "vault", True)]
    assert "already" in capsys.readouterr().out

    feed = [FeedEntry("x", "UCsam", "Sam", "t", "2026-10-20T10:00:00+00:00", "")]
    mocker.patch("youtube_summarizer.digest.youtube.fetch_feed", return_value=feed)
    assert cli.main(["channels", "list"]) == 0
    out = capsys.readouterr().out
    assert "Sam Witteveen" in out and "vault" in out and "2026-10-20" in out and "pinned" in out


def test_cli_channels_add_needs_youtube_key(mocker, monkeypatch, capsys):
    from youtube_summarizer.digest import cli
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    mocker.patch.object(cli, "load_config", return_value=Config(env_file=Config().env_file.with_name("none")))
    assert cli.main(["channels", "add", "@x", "--bucket", "news"]) == 1
    assert "YOUTUBE_API_KEY" in capsys.readouterr().out


def test_refresh_keeps_discovery_channels_it_cannot_replace(mocker):
    ch.save_channels([ch.Channel("UCd1", "Disc 1", "discovery"), ch.Channel("UCd2", "Disc 2", "discovery"),
                      ch.Channel("UCd3", "Disc 3", "discovery")])
    mocker.patch("youtube_summarizer.digest.youtube.api_get", return_value=_search_reply([("UCnew1", 2)]))
    mocker.patch("youtube_summarizer.digest.youtube.fetch_video_meta",
                 side_effect=lambda ids, api_key: {i: VideoMeta(i, 600, False, 100) for i in ids})

    def fake_judge(items, cfg):
        from youtube_summarizer.digest.judge import Verdict
        return {e.video_id: Verdict(e.video_id, True, False, "ai") for e, _ in items}
    mocker.patch("youtube_summarizer.digest.judge.judge", side_effect=fake_judge)

    lines = ch.maybe_refresh(Config(), State(), NOW, "k")
    ids = [c.channel_id for c in ch.load_channels()]
    assert len(ids) == 3 and "UCnew1" in ids
    assert sum(1 for l in lines if l.startswith("−")) == 1
