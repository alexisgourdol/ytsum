"""The channel list (channels.toml in the digest data dir)."""

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from youtube_summarizer.digest import judge, llm, youtube
from youtube_summarizer.digest.config import Config, data_dir
from youtube_summarizer.digest.state import State

BUCKETS = ("vault", "news", "labs", "discovery")
DISCOVERY_SLOTS = 3
DISCOVERY_QUERIES = ["new AI model release", "AI agents", "Claude Code", "OpenAI Codex", "LLM reasoning"]
DISCOVERY_WINDOW_DAYS = 60
MIN_ON_TOPIC_VIDEOS = 2
STALE_DAYS = 90


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


def resolve_channel(ref: str, api_key: str, bucket: str = "vault", pinned: bool = False) -> Channel:
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
    return Channel(items[0]["id"], items[0]["snippet"]["title"], bucket, pinned)


def _due(state: State, now: datetime, cfg: Config) -> bool:
    if not state.last_refresh:
        return True
    return (now.date() - date.fromisoformat(state.last_refresh)).days >= cfg.refresh_days


def _discover(listed: set[str], cfg: Config, now: datetime, api_key: str) -> list[tuple[str, str, int, int]]:
    """(channel_id, name, on-topic videos, average views) for new candidate channels, best first."""
    after = (now - timedelta(days=DISCOVERY_WINDOW_DAYS)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos: dict[str, youtube.FeedEntry] = {}
    for q in DISCOVERY_QUERIES:
        data = youtube.api_get("search", {"part": "snippet", "type": "video", "order": "viewCount",
                                          "publishedAfter": after, "maxResults": 50, "q": q}, api_key)
        for item in data.get("items", []):
            sn, vid = item["snippet"], item["id"]["videoId"]
            if sn["channelId"] in listed:
                continue
            videos[vid] = youtube.FeedEntry(vid, sn["channelId"], sn["channelTitle"], sn["title"],
                                            sn.get("publishedAt", ""), sn.get("description", ""))
    verdicts = judge.judge([(e, "") for e in videos.values()], cfg)
    on_topic: dict[str, list[str]] = {}
    for vid, v in verdicts.items():
        if v.on_topic and not v.fully_sponsored:
            on_topic.setdefault(videos[vid].channel_id, []).append(vid)
    qualified = {cid: vids for cid, vids in on_topic.items() if len(vids) >= MIN_ON_TOPIC_VIDEOS}
    if not qualified:
        return []
    meta = youtube.fetch_video_meta([v for vids in qualified.values() for v in vids], api_key)
    ranked = []
    for cid, vids in qualified.items():
        views = [meta[v].view_count for v in vids if v in meta]
        avg = sum(views) // len(views) if views else 0
        ranked.append((cid, videos[vids[0]].channel_name, len(vids), avg))
    return sorted(ranked, key=lambda r: r[3], reverse=True)


def _stale_lines(chs: list[Channel], now: datetime) -> list[str]:
    lines = []
    for c in chs:
        if c.pinned or c.bucket == "discovery":
            continue
        try:
            feed = youtube.fetch_feed(c.channel_id)
        except youtube.FeedError as e:
            lines.append(f"? {c.name} ({c.bucket}): feed unavailable ({e}) — check the channel")
            continue
        newest = max((datetime.fromisoformat(e.published) for e in feed), default=None)
        if newest is None or (now - newest).days > STALE_DAYS:
            lines.append(f"? {c.name} ({c.bucket}): no uploads for 90 days — consider replacing it")
    return lines


def maybe_refresh(cfg: Config, state: State, now: datetime, api_key: str) -> list[str]:
    """
    Monthly channel refresh; returns change lines for the digest.
    Only unpinned discovery channels are replaced; other buckets only get suggestions.
    On failure nothing changes and the refresh is retried next run.
    """
    if not _due(state, now, cfg):
        return []
    chs = load_channels()
    try:
        ranked = _discover({c.channel_id for c in chs}, cfg, now, api_key)
        stale = _stale_lines(chs, now)
    except (youtube.YouTubeApiError, judge.JudgeError, llm.LlmError) as e:
        return [f"Channel refresh failed, retried next run: {e}"]

    replaceable = [c for c in chs if c.bucket == "discovery" and not c.pinned]
    pinned_discovery = sum(1 for c in chs if c.bucket == "discovery" and c.pinned)
    free = max(DISCOVERY_SLOTS - pinned_discovery, 0)
    added = [Channel(cid, name, "discovery") for cid, name, _, _ in ranked[:free]]
    # Replace only as many as there are newcomers; the rest stay (oldest listed are replaced first).
    open_slots = max(free - len(replaceable), 0)
    removed = replaceable[:max(len(added) - open_slots, 0)]
    stats = {cid: (n, avg) for cid, _, n, avg in ranked}

    lines = []
    for c in added:
        n, avg = stats[c.channel_id]
        lines.append(f"+ {c.name} (discovery): {n} on-topic videos in 60 days, {avg:,} average views")
    for c in removed:
        lines.append(f"− {c.name} (discovery): replaced by the monthly refresh")
    removed_ids = {c.channel_id for c in removed}
    save_channels([c for c in chs if c.channel_id not in removed_ids] + added)
    state.last_refresh = now.date().isoformat()
    return lines + stale
