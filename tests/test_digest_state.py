"""Tests for digest state, daily stamp and lock"""

import os
import time
from datetime import date

from youtube_summarizer.digest import state as st
from youtube_summarizer.digest.config import data_dir


def _rec(video_id="v1", **kw):
    base = dict(video_id=video_id, channel_id="UC1", channel_name="Chan", title="T",
                published="2026-10-20T10:00:00+00:00", status="pending")
    base.update(kw)
    return st.VideoRecord(**base)


def test_state_roundtrip():
    s = st.State(videos={"v1": _rec(attempts=2, duration_s=600)}, first_run_done=True, last_refresh="2026-10-01")
    st.save_state(s)
    loaded = st.load_state()
    assert loaded == s


def test_load_state_missing_is_empty():
    assert st.load_state() == st.State(videos={})


def test_save_is_atomic():
    st.save_state(st.State(videos={"v1": _rec()}))
    assert not list(data_dir().glob("*.tmp"))
    assert (data_dir() / "state.json").exists()


def test_stamp_once_per_day():
    today = date(2026, 10, 21)
    assert not st.already_ran_today(today)
    st.mark_ran_today(today)
    assert st.already_ran_today(today)
    assert not st.already_ran_today(date(2026, 10, 22))


def test_lock_exclusive():
    with st.acquire_lock() as outer:
        assert outer
        with st.acquire_lock() as inner:
            assert not inner
    assert not (data_dir() / "digest.lock").exists()


def test_stale_lock_is_taken_over():
    lock = data_dir() / "digest.lock"
    lock.write_text("999999")  # no such process
    with st.acquire_lock() as got:
        assert got

    lock.write_text(str(os.getpid()))  # alive, but 4 hours old
    old = time.time() - 4 * 3600
    os.utime(lock, (old, old))
    with st.acquire_lock() as got:
        assert got


def test_pause_after_block_doubles_up_to_14_days_and_resets():
    state = st.State()
    today = date(2026, 10, 31)
    days = [(st.pause_after_block(state, today) - today).days for _ in range(5)]
    assert days == [2, 4, 8, 14, 14]
    assert (data_dir() / "paused_until").read_text().strip() == "2026-11-14"
    assert st.load_state().block_streak == 0  # pause_after_block doesn't save; the run does
    state.block_streak = 0
    assert (st.pause_after_block(state, today) - today).days == 2
