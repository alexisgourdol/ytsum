"""Tests for selection: first-run window, caps, carry-over, retries, expiry"""

from datetime import datetime, timedelta, timezone

from youtube_summarizer.digest import select as sel
from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.state import State, VideoRecord
from youtube_summarizer.digest.youtube import FeedEntry

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def _iso(days_ago, hours=0):
    return (NOW - timedelta(days=days_ago, hours=hours)).isoformat()


def _entry(video_id, channel="UC1", days_ago=0.5, hours=0):
    return FeedEntry(video_id, channel, f"name-{channel}", f"title-{video_id}", _iso(days_ago, hours), "")


def test_first_run_window():
    state = State()
    added = sel.register_new(state, [_entry("old", days_ago=3), _entry("new", days_ago=1)], NOW, Config())
    assert [r.video_id for r in added] == ["new"]
    assert state.videos["old"].status == "skipped"
    assert state.videos["old"].reason == "before first run"
    assert state.videos["new"].status == "pending"


def test_register_new_ignores_known_and_has_no_window_for_seen_channels():
    state = State(first_run_done=True, seen_channels=["UC1"])
    sel.register_new(state, [_entry("a", days_ago=5)], NOW, Config())
    state.videos["a"].status = "done"
    added = sel.register_new(state, [_entry("a", days_ago=5), _entry("b", days_ago=5)], NOW, Config())
    assert [r.video_id for r in added] == ["b"]
    assert state.videos["a"].status == "done"


def test_per_channel_and_daily_caps():
    state = State(first_run_done=True)
    entries = [_entry(f"{ch}-{i}", channel=ch, days_ago=0, hours=i * 3 + n)
               for n, ch in enumerate(["UCa", "UCb", "UCc"]) for i in range(5)]
    sel.register_new(state, entries, NOW, Config())
    picked = sel.pick(state, Config(per_channel_cap=2, daily_cap=5))
    assert len(picked) == 5
    per_channel = {}
    for r in picked:
        per_channel[r.channel_id] = per_channel.get(r.channel_id, 0) + 1
    assert max(per_channel.values()) <= 2
    published = [r.published for r in picked]
    assert published == sorted(published, reverse=True)


def test_carry_over():
    state = State(first_run_done=True)
    sel.register_new(state, [_entry(f"v{i}", channel=f"UC{i}", hours=i) for i in range(4)], NOW, Config())
    picked = sel.pick(state, Config(daily_cap=2))
    rest = [r for r in state.videos.values() if r not in picked]
    assert len(rest) == 2 and all(r.status == "pending" for r in rest)


def test_drop_after_14_days():
    state = State(first_run_done=True, seen_channels=["UC1"])
    sel.register_new(state, [_entry("stale", days_ago=15), _entry("fresh", days_ago=2)], NOW, Config())
    dropped = sel.drop_expired(state, NOW, Config())
    assert [r.video_id for r in dropped] == ["stale"]
    assert state.videos["stale"].status == "dropped"
    assert state.videos["fresh"].status == "pending"
    assert sel.drop_expired(state, NOW, Config()) == []  # reported once


def test_retry_then_give_up():
    cfg = Config(max_attempts=3)
    state = State(first_run_done=True)
    sel.register_new(state, [_entry("v")], NOW, cfg)
    rec = state.videos["v"]
    for n in range(3):
        assert rec in sel.pick(state, cfg)
        sel.record_failure(rec, "no captions", cfg)
    assert rec.status == "given_up" and rec.attempts == 3 and rec.reason == "no captions"
    assert sel.pick(state, cfg) == []


def test_window_applies_to_a_channel_seen_for_the_first_time_later():
    """A channel added after the first run (digest channels add) doesn't flood the digest."""
    state = State(first_run_done=True, seen_channels=["UC1"])
    added = sel.register_new(state, [_entry("old-new-channel", channel="UCnew", days_ago=40),
                                     _entry("fresh-new-channel", channel="UCnew", days_ago=1),
                                     _entry("old-known-channel", channel="UC1", days_ago=5)], NOW, Config())
    assert sorted(r.video_id for r in added) == ["fresh-new-channel", "old-known-channel"]
    assert state.videos["old-new-channel"].status == "skipped"
    assert "UCnew" in state.seen_channels
    assert sel.drop_expired(state, NOW, Config()) == []  # skipped, not dumped into "Dropped"
