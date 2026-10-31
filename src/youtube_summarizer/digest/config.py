"""Digest settings (config.toml in the digest data dir) and secrets loading."""

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Optional

from youtube_summarizer import runlog


@dataclass(frozen=True)
class Config:
    mode: str = "api"  # "api" (Anthropic API key) or "subscription" (claude -p)
    judge_model: str = "claude-haiku-5-5"
    summary_model: str = "claude-haiku-5-5"
    deep_dive_model: str = "claude-sonnet-5-5"
    daily_cap: int = 10
    per_channel_cap: int = 2
    deep_dive_cap: int = 3
    shorts_max_seconds: int = 180
    first_run_days: int = 2
    pending_max_days: int = 14
    max_attempts: int = 3
    # Random wait (seconds) between YouTube requests, so the IP isn't blocked (SCP-100).
    feed_delay_s: tuple[float, float] = (5, 8)
    transcript_delay_s: tuple[float, float] = (40, 70)
    vault_dir: Path = Path("/workspace-external/obsidian-synch/general-kb/01-raw")
    topic_tag: str = "LLM"
    skill_path: Path = Path("~/.claude/skills/video-summary/SKILL.md").expanduser()
    # Secrets live in the main ytsum checkout, not the .digest-main worktree the job runs from.
    env_file: Path = Path("/workspace-external/ytsum/.env.local")


PATH_FIELDS = {"vault_dir", "skill_path", "env_file"}
DELAY_FIELDS = {"feed_delay_s", "transcript_delay_s"}
# Keys older config files may still set; ignored. refresh_days went with the channel auto-refresh (SCP-78).
RETIRED_FIELDS = {"refresh_days"}


def data_dir() -> Path:
    """Where the digest keeps its config, channel list and state: next to the run log."""
    path = runlog.db_path().parent / "digest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config(path: Optional[Path] = None) -> Config:
    """
    Read config.toml (default: in data_dir()); every key is optional.

    Raises:
        ValueError: for a key Config doesn't know, so a typo can't be silently ignored,
            or a delay that isn't [min, max] seconds.
    """
    path = path or data_dir() / "config.toml"
    if not path.exists():
        return Config()
    values = {k: v for k, v in tomllib.loads(path.read_text()).items() if k not in RETIRED_FIELDS}
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"Unknown key(s) in {path}: {', '.join(unknown)}")
    for key in PATH_FIELDS & set(values):
        values[key] = Path(values[key]).expanduser()
    for key in DELAY_FIELDS & set(values):
        bounds = values[key]
        if not (isinstance(bounds, list) and len(bounds) == 2 and 0 <= bounds[0] <= bounds[1]):
            raise ValueError(f"{key} in {path} must be [min, max] seconds, got {bounds!r}")
        values[key] = (bounds[0], bounds[1])
    return replace(Config(), **values)


def load_env_file(path: Path) -> None:
    """Set KEY=VALUE lines from a dotenv-style file, never overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
