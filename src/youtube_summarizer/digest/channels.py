"""The channel list (channels.toml in the digest data dir)."""

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime

from youtube_summarizer.digest import youtube
from youtube_summarizer.digest.config import data_dir
from youtube_summarizer.digest.state import State

# Labels only: channels are added and removed by hand (digest channels add, or an edit of channels.toml).
BUCKETS = ("vault", "news", "labs", "discovery")
STALE_DAYS = 90
STALE_CHECK_DAYS = 30


@dataclass
class Channel:
    channel_id: str
    name: str
    bucket: str  # vault | news | labs | discovery


def _path():
    return data_dir() / "channels.toml"


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_channels() -> list[Channel]:
    path = _path()
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    # Older files also carry pinned = true/false, from the monthly auto-refresh removed in SCP-78.
    return [Channel(c["channel_id"], c["name"], c["bucket"]) for c in data.get("channel", [])]


def save_channels(chs: list[Channel]) -> None:
    lines = ["# Channels the daily digest follows. Add with `youtube-summarizer digest channels add`, or edit by hand.", ""]
    for c in chs:
        lines += [
            "[[channel]]",
            f"channel_id = {_toml_str(c.channel_id)}",
            f"name = {_toml_str(c.name)}",
            f"bucket = {_toml_str(c.bucket)}",
            "",
        ]
    _path().write_text("\n".join(lines))


def resolve_channel(ref: str, api_key: str, bucket: str = "vault") -> Channel:
    """A channel from a URL (/channel/UC… or /@handle), an @handle or a UC… ID."""
    ref = ref.strip()
    m = re.search(r"/channel/(UC[\w-]+)", ref) or re.fullmatch(r"(UC[\w-]{22})", ref)
    if m:
        params = {"id": m.group(1)}
    else:
        h = re.search(r"(@[\w.-]+)", ref)
        if not h:
            raise ValueError(f"Not a channel URL, @handle or ID: {ref}")
        params = {"forHandle": h.group(1)}
    data = youtube.api_get("channels", {"part": "snippet", **params}, api_key)
    items = data.get("items") or []
    if not items:
        raise ValueError(f"No YouTube channel found for {ref}")
    return Channel(items[0]["id"], items[0]["snippet"]["title"], bucket)


def stale_check_due(state: State, now: datetime) -> bool:
    if not state.last_stale_check:
        return True
    return (now.date() - date.fromisoformat(state.last_stale_check)).days >= STALE_CHECK_DAYS


def stale_lines(chs: list[Channel], feeds: dict[str, list[youtube.FeedEntry]], now: datetime) -> list[str]:
    """
    Channels with no upload for STALE_DAYS, from the feeds the run already read (no extra request).
    A channel missing from feeds couldn't be read; the run lists it under failures already.
    """
    lines = []
    for c in chs:
        if c.channel_id not in feeds:
            continue
        newest = max((datetime.fromisoformat(e.published) for e in feeds[c.channel_id]), default=None)
        if newest is None or (now - newest).days > STALE_DAYS:
            lines.append(f"? {c.name} ({c.bucket}): no uploads for {STALE_DAYS} days — consider replacing it")
    return lines
