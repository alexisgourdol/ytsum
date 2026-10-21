"""Tests for RSS feed parsing and YouTube Data API metadata"""

import json
from pathlib import Path

import pytest

from youtube_summarizer.digest import youtube as yt

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_feed():
    entries = yt.parse_feed((FIXTURES / "feed.xml").read_text())
    assert [e.video_id for e in entries] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    first = entries[0]
    assert first.title == "Claude & Codex: agents compared"
    assert first.channel_id == "UC55ODQSvARtgSyc8ThfiepQ"
    assert first.channel_name == "Sam Witteveen"
    assert first.published == "2026-10-20T14:00:00+00:00"
    assert first.description == "Comparing two coding agents."
    assert entries[1].description == ""


@pytest.mark.parametrize("value,seconds", [("PT1H2M3S", 3723), ("PT45S", 45), ("PT2M", 120), ("P0D", 0), ("P1DT1S", 86401)])
def test_parse_iso8601_duration(value, seconds):
    assert yt.parse_iso8601_duration(value) == seconds


def test_fetch_video_meta_batches(mocker):
    calls = []

    def fake_get(path, params, api_key):
        ids = params["id"].split(",")
        calls.append(len(ids))
        return {"items": [{"id": i, "snippet": {"liveBroadcastContent": "none"},
                           "contentDetails": {"duration": "PT10M"}, "statistics": {"viewCount": "1"}} for i in ids]}

    mocker.patch.object(yt, "api_get", side_effect=fake_get)
    ids = [f"id{n:09d}" for n in range(120)]
    meta = yt.fetch_video_meta(ids, api_key="k")
    assert calls == [50, 50, 20]
    assert len(meta) == 120 and meta["id000000000"].duration_s == 600


def test_fetch_video_meta_parses_fixture(mocker):
    mocker.patch.object(yt, "api_get", return_value=json.loads((FIXTURES / "videos_list.json").read_text()))
    meta = yt.fetch_video_meta(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"], api_key="k")
    assert meta["aaaaaaaaaaa"] == yt.VideoMeta("aaaaaaaaaaa", 1510, False, 12345)
    assert meta["ccccccccccc"].is_live is True
    assert meta["ccccccccccc"].view_count == 0


def test_skip_reason(mocker):
    mocker.patch.object(yt, "api_get", return_value=json.loads((FIXTURES / "videos_list.json").read_text()))
    meta = yt.fetch_video_meta(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"], api_key="k")
    assert yt.skip_reason(meta["bbbbbbbbbbb"], shorts_max_seconds=180) == "short"
    assert yt.skip_reason(meta["ccccccccccc"], shorts_max_seconds=180) == "livestream"
    assert yt.skip_reason(meta["aaaaaaaaaaa"], shorts_max_seconds=180) is None


def test_fetch_feed_wraps_errors(mocker):
    import urllib.error
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None))
    with pytest.raises(yt.FeedError, match="404"):
        yt.fetch_feed("UCnope")


def test_api_get_reports_api_error(mocker):
    import io
    import urllib.error
    body = io.BytesIO(json.dumps({"error": {"message": "quotaExceeded"}}).encode())
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 403, "Forbidden", {}, body))
    with pytest.raises(yt.YouTubeApiError, match="quotaExceeded"):
        yt.api_get("videos", {"id": "x"}, api_key="k")


@pytest.mark.parametrize("exc", [ConnectionResetError("reset"), __import__("http.client").client.RemoteDisconnected("gone"),
                                 UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")])
def test_fetch_feed_wraps_connection_errors(mocker, exc):
    mocker.patch("urllib.request.urlopen", side_effect=exc)
    with pytest.raises(yt.FeedError):
        yt.fetch_feed("UCx")


def test_api_get_wraps_connection_and_bad_json(mocker):
    import io
    mocker.patch("urllib.request.urlopen", side_effect=ConnectionResetError("reset"))
    with pytest.raises(yt.YouTubeApiError, match="reset"):
        yt.api_get("videos", {}, api_key="k")
    html = mocker.MagicMock()
    html.__enter__.return_value = io.BytesIO(b"<html>oops</html>")
    mocker.patch("urllib.request.urlopen", return_value=html)
    with pytest.raises(yt.YouTubeApiError):
        yt.api_get("videos", {}, api_key="k")
