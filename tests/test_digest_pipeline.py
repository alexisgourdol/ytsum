"""End-to-end digest runs with all network and LLM calls mocked"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from youtube_summarizer.digest import channels as ch
from youtube_summarizer.digest import pipeline
from youtube_summarizer.digest import state as st
from youtube_summarizer.digest.config import Config
from youtube_summarizer.downloader import TranscriptBlocked, TranscriptError
from youtube_summarizer.digest.notes import read_frontmatter
from youtube_summarizer.digest.youtube import FeedEntry, FeedError, VideoMeta, YouTubeBlocked

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)
SUMMARY = "## Summary\n\nProse.\n\n## Key Takeaways\n\n- a\n\n## Deep dive?\n\nNo, an overview."


def _entry(video_id, channel="UCa", hours_ago=1, title=None):
    return FeedEntry(video_id, channel, f"Chan {channel}", title or f"Video {video_id}",
                     (NOW - timedelta(hours=hours_ago)).isoformat(), "desc")


@pytest.fixture
def world(tmp_path, monkeypatch, mocker):
    """Two channels, keys set, every external call mocked; tests adjust the pieces they need."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-key")
    ch.save_channels([ch.Channel("UCa", "Chan UCa", "vault"), ch.Channel("UCb", "Chan UCb", "news")])
    vault = tmp_path / "vault"
    vault.mkdir()
    skill = tmp_path / "SKILL.md"
    skill.write_text("FULL TEMPLATE")
    cfg = Config(vault_dir=vault, skill_path=skill, env_file=tmp_path / "none.env",
                 feed_delay_s=(0, 0), transcript_delay_s=(0, 0))

    feeds = {"UCa": [_entry("aaaaaaaaaa1", "UCa", 1), _entry("aaaaaaaaaa2", "UCa", 2)],
             "UCb": [_entry("bbbbbbbbbb1", "UCb", 3)]}
    meta = {"aaaaaaaaaa1": VideoMeta("aaaaaaaaaa1", 1500, False, 10),
            "aaaaaaaaaa2": VideoMeta("aaaaaaaaaa2", 60, False, 10),  # a Short
            "bbbbbbbbbb1": VideoMeta("bbbbbbbbbb1", 2400, False, 10)}

    def fake_complete(system, user, *, model, mode, kind, video_id=None, title=None):
        if kind == "judge":
            ids = [line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("### video_id: ")]
            text = json.dumps([{"video_id": i, "on_topic": True, "fully_sponsored": False, "reason": "ai"} for i in ids])
            return MagicMock(text=text)
        if kind == "deep_dive":
            return MagicMock(text="# Deep dive\n\nLong.")
        return MagicMock(text=SUMMARY)

    m = MagicMock()
    m.fetch_feed = mocker.patch.object(pipeline.youtube, "fetch_feed", side_effect=lambda cid: feeds[cid])
    m.fetch_meta = mocker.patch.object(pipeline.youtube, "fetch_video_meta",
                                       side_effect=lambda ids, api_key: {i: meta[i] for i in ids if i in meta})
    m.download = mocker.patch.object(pipeline, "download_transcript", side_effect=lambda vid: f"transcript of {vid}")
    m.complete = mocker.patch.object(pipeline.llm, "complete", side_effect=fake_complete)
    m.refresh = mocker.patch.object(pipeline.channels, "maybe_refresh", return_value=[])
    m.cfg, m.vault, m.feeds = cfg, vault, feeds
    return m


def _digest(world):
    return (world.vault / "2026-10-21 digest.md").read_text()


def test_happy_path(world):
    report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert report is not None and not report.fatal
    names = sorted(p.name for p in world.vault.iterdir())
    assert "2026-10-21 LLM - Video aaaaaaaaaa1.md" in names
    assert "2026-10-21 LLM - Video aaaaaaaaaa1 - transcript.md" in names
    assert "2026-10-21 LLM - Video bbbbbbbbbb1.md" in names
    assert not any("aaaaaaaaaa2" in n for n in names)
    digest = _digest(world)
    assert "## New videos" in digest and "short" in digest
    state = st.load_state()
    assert state.videos["aaaaaaaaaa1"].status == "done"
    assert state.videos["aaaaaaaaaa2"].status == "skipped"
    assert state.first_run_done


def test_one_failure_does_not_stop_the_run(world):
    def feed(cid):
        if cid == "UCb":
            raise FeedError("feed for UCb: HTTP Error 404")
        return world.feeds[cid]
    world.fetch_feed.side_effect = feed
    world.download.side_effect = lambda vid: (_ for _ in ()).throw(TranscriptError("no captions")) if vid == "aaaaaaaaaa1" else "t"
    world.feeds["UCa"].append(_entry("aaaaaaaaaa3", "UCa", 4))
    world.fetch_meta.side_effect = lambda ids, api_key: {i: VideoMeta(i, 1500, False, 1) for i in ids}

    pipeline.run_digest(world.cfg, NOW, once_per_day=False)

    digest = _digest(world)
    assert "404" in digest and "no captions" in digest
    # a picked video whose transcript fails keeps its slot (no backfill: fewer requests while YouTube blocks)
    assert any("aaaaaaaaaa2" in p.name for p in world.vault.iterdir())
    assert st.load_state().videos["aaaaaaaaaa1"].status == "failed"


def test_state_saved_after_each_video(world):
    calls = {"n": 0}
    original = world.complete.side_effect

    def flaky(system, user, **kw):
        if kw["kind"] == "summary":
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("container stopped")
        return original(system, user, **kw)

    world.complete.side_effect = flaky
    report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert report.fatal  # unexpected error → fatal digest, no traceback to the hook
    state = st.load_state()
    done = [v for v, r in state.videos.items() if r.status == "done"]
    assert done == ["aaaaaaaaaa1"]

    world.complete.side_effect = original
    world.complete.reset_mock()
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    summarized = [c.kwargs["video_id"] for c in world.complete.call_args_list if c.kwargs["kind"] == "summary"]
    assert summarized == ["bbbbbbbbbb1"]


def test_once_per_day_skips_second_run(world):
    assert pipeline.run_digest(world.cfg, NOW, once_per_day=True) is not None
    assert pipeline.run_digest(world.cfg, NOW, once_per_day=True) is None
    assert pipeline.run_digest(world.cfg, NOW, once_per_day=False) is not None


def test_lock_held_skips(world):
    with st.acquire_lock():
        assert pipeline.run_digest(world.cfg, NOW, once_per_day=False) is None


def test_deep_dive_uses_saved_transcript(world):
    note = world.vault / "2026-10-19 LLM - Old.md"
    note.write_text('---\nvideo_id: zzzzzzzzzzz\ndigest_date: 2026-10-19\ndeep_dive: true\ndeep_dive_note: ""\n---\n\n# Old\n')
    (world.vault / "2026-10-19 LLM - Old - transcript.md").write_text("## Transcript\n\nsaved words")

    pipeline.run_digest(world.cfg, NOW, once_per_day=False)

    assert "zzzzzzzzzzz" not in [c.args[0] for c in world.download.call_args_list]
    deep_calls = [c for c in world.complete.call_args_list if c.kwargs["kind"] == "deep_dive"]
    assert len(deep_calls) == 1
    assert "saved words" in deep_calls[0].args[1]
    assert deep_calls[0].args[0].startswith("FULL TEMPLATE")
    assert deep_calls[0].kwargs["model"] == "claude-sonnet-5-5"
    assert (world.vault / "2026-10-19 LLM - Old - deep dive.md").exists()
    assert read_frontmatter(note)["deep_dive_note"] == "[[2026-10-19 LLM - Old - deep dive]]"


def test_carried_over_videos_are_not_rejudged(world):
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)  # judges and summarizes everything
    world.feeds["UCa"] += [_entry(f"cccccccccc{i}", "UCa", 0.5) for i in range(3)]
    world.fetch_meta.side_effect = lambda ids, api_key: {i: VideoMeta(i, 1500, False, 1) for i in ids}
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)  # 3 new, cap 2 per channel → 1 carried
    world.complete.reset_mock()
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    kinds = [c.kwargs["kind"] for c in world.complete.call_args_list]
    assert kinds == ["summary"]


def test_missing_api_key_writes_fatal_digest(world, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY")
    report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert "YOUTUBE_API_KEY" in report.fatal
    assert "Run failed" in _digest(world)
    world.complete.assert_not_called()


def test_subscription_mode_needs_no_anthropic_key(world, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    from dataclasses import replace
    report = pipeline.run_digest(replace(world.cfg, mode="subscription"), NOW, once_per_day=False)
    assert not report.fatal


def test_usage_totals_come_from_this_runs_log_rows(world, monkeypatch):
    from youtube_summarizer.runlog import record_run
    monkeypatch.setenv("TZ", "Asia/Tokyo")  # local time ahead of UTC
    import time
    time.tzset()
    original = world.complete.side_effect

    def logging_complete(system, user, **kw):
        record_run({"model": "anthropic:claude-haiku-5-5", "kind": kw["kind"], "topic": "digest",
                    "input_tokens": 100, "output_tokens": 10, "status": "ok"})
        return original(system, user, **kw)

    world.complete.side_effect = logging_complete
    try:
        report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
    kinds = {(m, k): (calls, tin) for m, k, calls, tin, tout, cost in report.usage}
    assert kinds[("anthropic:claude-haiku-5-5", "summary")] == (2, 200)
    assert kinds[("anthropic:claude-haiku-5-5", "judge")] == (1, 100)
    assert "## Usage" in _digest(world)


def test_cli_runs_pipeline_and_reports_fatal(world, monkeypatch, mocker, capsys):
    from youtube_summarizer.digest import cli
    mocker.patch.object(cli, "load_config", return_value=world.cfg)
    assert cli.main([]) == 0
    assert "digest.md" in capsys.readouterr().out
    monkeypatch.delenv("YOUTUBE_API_KEY")
    assert cli.main([]) == 1
    assert cli.main(["--once-per-day"]) == 1
    assert cli.main(["--once-per-day"]) == 0  # second run today is skipped
    assert "skipped" in capsys.readouterr().out


def test_unavailable_video_is_listed(world):
    world.fetch_meta.side_effect = lambda ids, api_key: {i: VideoMeta(i, 1500, False, 1) for i in ids if i != "bbbbbbbbbb1"}
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert "Video bbbbbbbbbb1" in _digest(world) and "not available" in _digest(world)


def test_deep_dive_failure_counts_attempts_then_gives_up(world):
    note = world.vault / "2026-10-19 LLM - Old.md"
    note.write_text('---\nvideo_id: zzzzzzzzzzz\ndigest_date: 2026-10-19\ndeep_dive: true\ndeep_dive_note: ""\n---\n\n# Old\n')
    # no transcript file next to it: every attempt fails
    for _ in range(3):
        pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert read_frontmatter(note)["deep_dive_attempts"] == "3"
    assert "Given up" in _digest(world)
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert read_frontmatter(note)["deep_dive_attempts"] == "3"  # no longer retried


def test_hook_update_failure_is_reported(world, monkeypatch):
    monkeypatch.setenv("YTSUM_DIGEST_UPDATE_FAILED", "could not update .digest-main")
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert "could not update .digest-main" in _digest(world)


def test_transcripts_only_for_picked_videos(world):
    from dataclasses import replace
    world.feeds["UCa"] += [_entry(f"aaaaaaaaab{i}", "UCa", 1 + i * 0.1) for i in range(4)]
    world.fetch_meta.side_effect = lambda ids, api_key: {i: VideoMeta(i, 1500, False, 1) for i in ids}
    pipeline.run_digest(replace(world.cfg, daily_cap=2), NOW, once_per_day=False)
    downloaded = [c.args[0] for c in world.download.call_args_list]
    summarized = [c.kwargs["video_id"] for c in world.complete.call_args_list if c.kwargs["kind"] == "summary"]
    assert sorted(downloaded) == sorted(summarized) and len(downloaded) == 2
    judge_prompt = next(c.args[1] for c in world.complete.call_args_list if c.kwargs["kind"] == "judge")
    assert "transcript of" not in judge_prompt


LIBRARY_ERROR = (
    "Error downloading transcript for _UetnlytnJ4: \n"
    "Could not retrieve a transcript for the video https://www.youtube.com/watch?v=_UetnlytnJ4! "
    "This is most likely caused by:\n\nSubtitles are disabled for this video\n\n"
    "If you are sure that the described cause is not responsible for this error ..."
)


def test_failure_lines_are_one_line(world):
    world.download.side_effect = lambda vid: (_ for _ in ()).throw(TranscriptError(LIBRARY_ERROR))
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    failures = _digest(world).split("## Failures")[1].split("\n## ")[0]
    lines = [l for l in failures.splitlines() if l.strip()][1:]  # drop the heading's tail
    assert lines and all(l.startswith("- ") for l in lines)
    assert "Subtitles are disabled for this video" in failures
    assert "If you are sure" not in failures


def test_short_reason():
    assert pipeline.short_reason(LIBRARY_ERROR) == (
        "Error downloading transcript for _UetnlytnJ4: Subtitles are disabled for this video")
    assert pipeline.short_reason("plain error") == "plain error"
    assert len(pipeline.short_reason("x" * 500)) <= 200


def _paused_until():
    return (st.data_dir() / "paused_until").read_text().strip()


def test_feed_block_stops_youtube_requests_and_pauses(world):
    world.fetch_feed.side_effect = YouTubeBlocked("feed for UCa: redirected to google.com/sorry")
    report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert not report.fatal
    assert world.fetch_feed.call_count == 1  # no second feed after the block
    world.fetch_meta.assert_not_called()
    world.download.assert_not_called()
    assert "Run stopped: YouTube is blocking this IP** (step: feeds" in _digest(world)
    assert _paused_until() == "2026-10-23"
    assert st.load_state().block_streak == 1


def test_transcript_block_leaves_attempts_unchanged(world):
    world.download.side_effect = TranscriptBlocked("Error downloading transcript: IpBlocked")
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert world.download.call_count == 1  # stopped at the first block
    state = st.load_state()
    assert all(r.attempts == 0 for r in state.videos.values())
    assert state.videos["aaaaaaaaaa1"].status == "pending"
    assert "(step: transcripts" in _digest(world)
    assert _paused_until() == "2026-10-23"


def test_refresh_block_skips_feeds(world):
    world.refresh.side_effect = YouTubeBlocked("3 feeds failed")
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    world.fetch_feed.assert_not_called()
    assert "(step: channel refresh" in _digest(world)


def test_consecutive_blocks_double_the_pause_and_a_clean_run_resets(world):
    world.fetch_feed.side_effect = YouTubeBlocked("429")
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert _paused_until() == "2026-10-25" and st.load_state().block_streak == 2
    world.fetch_feed.side_effect = lambda cid: world.feeds[cid]
    pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert st.load_state().block_streak == 0


def test_deep_dives_still_run_after_a_block(world):
    note = world.vault / "2026-10-19 LLM - Old.md"
    note.write_text('---\nvideo_id: zzzzzzzzzzz\ndigest_date: 2026-10-19\ndeep_dive: true\ndeep_dive_note: ""\n---\n\n# Old\n')
    (world.vault / "2026-10-19 LLM - Old - transcript.md").write_text("## Transcript\n\nsaved words")
    world.fetch_feed.side_effect = YouTubeBlocked("429")
    report = pipeline.run_digest(world.cfg, NOW, once_per_day=False)
    assert report.deep_dives == ["[[2026-10-19 LLM - Old - deep dive]]"]
