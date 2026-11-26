"""Tests for selection: 7-day window, caps, dropping the rest, retries, expiry"""

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


def test_videos_older_than_max_age_are_skipped_when_first_seen():
    """SCP-200: the run after a pause, or a new channel, only takes the last 7 days."""
    state = State(first_run_done=True)
    added = sel.register_new(state, [_entry("old", days_ago=8), _entry("new", days_ago=6),
                                     _entry("other", channel="UC2", days_ago=10)], NOW, Config())
    assert [r.video_id for r in added] == ["new"]
    assert state.videos["old"].status == "skipped" and state.videos["other"].status == "skipped"
    assert state.videos["old"].reason == "published over 7 days before it was first seen"
    assert state.videos["new"].status == "pending"
    assert sel.drop_expired(state, NOW, Config()) == []  # skipped, not dumped into "Dropped"


def test_register_new_ignores_known_videos():
    state = State(first_run_done=True)
    sel.register_new(state, [_entry("a", days_ago=5)], NOW, Config())
    state.videos["a"].status = "done"
    added = sel.register_new(state, [_entry("a", days_ago=5), _entry("b", days_ago=5)], NOW, Config())
    assert [r.video_id for r in added] == ["b"]
    assert state.videos["a"].status == "done"


def test_max_age_days_is_configurable():
    state = State()
    added = sel.register_new(state, [_entry("a", days_ago=3)], NOW, Config(max_age_days=2))
    assert added == [] and state.videos["a"].status == "skipped"


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


def test_drop_unpicked_drops_judged_pending_videos_only():
    """SCP-200: nothing carries over; judged videos past the caps are dropped."""
    cfg = Config(daily_cap=2, max_attempts=3)
    state = State(first_run_done=True)
    sel.register_new(state, [_entry(f"v{i}", channel=f"UC{i}", hours=i) for i in range(5)], NOW, cfg)
    for vid in ("v0", "v1", "v2", "v3"):
        state.videos[vid].judged = True
    sel.record_failure(state.videos["v3"], "no captions", cfg)  # failed, attempts left: retried later
    picked = sel.pick(state, cfg, require_judged=True)
    assert [r.video_id for r in picked] == ["v0", "v1"]
    dropped = sel.drop_unpicked(state, picked, cfg)
    assert [r.video_id for r in dropped] == ["v2"]
    assert state.videos["v2"].status == "dropped"
    assert state.videos["v3"].status == "failed"  # failed with attempts left: not dropped
    assert state.videos["v4"].status == "pending"  # never judged (Data API failure): not dropped
    assert sel.drop_unpicked(state, picked, cfg) == []  # reported once


def test_drop_after_14_days():
    state = State(first_run_done=True)
    sel.register_new(state, [_entry("stale", days_ago=15), _entry("fresh", days_ago=2)], NOW, Config(max_age_days=30))
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
