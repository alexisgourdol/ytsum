"""The channel list (channels.toml in the digest data dir)."""

import tomllib
from dataclasses import dataclass
from datetime import datetime

from youtube_summarizer.digest.config import Config, data_dir
from youtube_summarizer.digest.state import State

BUCKETS = ("vault", "news", "labs", "discovery")


@dataclass
class Channel:
    channel_id: str
    name: str
    bucket: str  # vault | news | labs | discovery
    pinned: bool = False


def _path():
    return data_dir() / "channels.toml"


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_channels() -> list[Channel]:
    path = _path()
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    return [Channel(c["channel_id"], c["name"], c["bucket"], bool(c.get("pinned", False)))
            for c in data.get("channel", [])]


def save_channels(chs: list[Channel]) -> None:
    lines = ["# Channels the daily digest follows. Set pinned = true to keep a channel through monthly refreshes.", ""]
    for c in chs:
        lines += [
            "[[channel]]",
            f"channel_id = {_toml_str(c.channel_id)}",
            f"name = {_toml_str(c.name)}",
            f"bucket = {_toml_str(c.bucket)}",
            f"pinned = {'true' if c.pinned else 'false'}",
            "",
        ]
    _path().write_text("\n".join(lines))


def maybe_refresh(cfg: Config, state: State, now: datetime, api_key: str) -> list[str]:
    """Monthly channel refresh; returns change lines for the digest."""
    return []
