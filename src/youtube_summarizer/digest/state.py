"""Digest state (videos seen, pending, failed), the once-per-day stamp and the run lock."""

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Iterator, Optional

from youtube_summarizer.digest.config import data_dir

STALE_LOCK_SECONDS = 3 * 3600


@dataclass
class VideoRecord:
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    published: str  # ISO 8601
    status: str  # pending | done | skipped | failed | given_up | dropped
    reason: str = ""
    attempts: int = 0
    note_path: str = ""
    duration_s: Optional[int] = None
    judged: bool = False  # the judge already found it on topic


@dataclass
class State:
    videos: dict[str, VideoRecord] = field(default_factory=dict)
    first_run_done: bool = False
    last_refresh: str = ""
    # Channels whose feed was read at least once; a channel's first read only takes recent videos.
    seen_channels: list[str] = field(default_factory=list)


def load_state() -> State:
    path = data_dir() / "state.json"
    if not path.exists():
        return State()
    raw = json.loads(path.read_text())
    videos = {vid: VideoRecord(**rec) for vid, rec in raw.get("videos", {}).items()}
    return State(videos=videos, first_run_done=raw.get("first_run_done", False),
                 last_refresh=raw.get("last_refresh", ""), seen_channels=raw.get("seen_channels", []))


def save_state(state: State) -> None:
    """Write state.json atomically, so a crash mid-write never leaves a half file."""
    path = data_dir() / "state.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def already_ran_today(today: date) -> bool:
    path = data_dir() / "last_run_date"
    return path.exists() and path.read_text().strip() == today.isoformat()


def mark_ran_today(today: date) -> None:
    (data_dir() / "last_run_date").write_text(today.isoformat())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_stale(path) -> bool:
    try:
        pid = int(path.read_text().strip() or 0)
        age = time.time() - path.stat().st_mtime
    except (OSError, ValueError):
        return True
    return not _pid_alive(pid) or age > STALE_LOCK_SECONDS


@contextmanager
def acquire_lock() -> Iterator[bool]:
    """
    Yield True if this process holds digest.lock, False if another live run does.
    A lock left by a dead process, or older than 3 hours, is taken over.
    """
    path = data_dir() / "digest.lock"
    acquired = False
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _is_stale(path):
                break
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        acquired = True
        break
    try:
        yield acquired
    finally:
        if acquired:
            path.unlink(missing_ok=True)
