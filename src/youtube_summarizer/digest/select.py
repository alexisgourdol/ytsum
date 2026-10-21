"""Which videos get summarized this run: new ones, carried-over ones and retries, within the caps."""

from datetime import datetime, timedelta

from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.state import State, VideoRecord
from youtube_summarizer.digest.youtube import FeedEntry


def _published(rec_or_entry) -> datetime:
    return datetime.fromisoformat(rec_or_entry.published)


def register_new(state: State, entries: list[FeedEntry], now: datetime, cfg: Config) -> list[VideoRecord]:
    """
    Add unseen videos as pending. The first time a channel's feed is read (first run,
    or a channel added later), only videos from the last first_run_days are taken;
    older ones are marked skipped, so a new channel never floods the digest.
    """
    added = []
    cutoff = now - timedelta(days=cfg.first_run_days)
    new_channels = {e.channel_id for e in entries} - set(state.seen_channels)
    for e in entries:
        if e.video_id in state.videos:
            continue
        rec = VideoRecord(e.video_id, e.channel_id, e.channel_name, e.title, e.published, "pending")
        if e.channel_id in new_channels and _published(e) < cutoff:
            rec.status, rec.reason = "skipped", "before first run"
        else:
            added.append(rec)
        state.videos[e.video_id] = rec
    state.seen_channels.extend(sorted(new_channels))
    return added


def drop_expired(state: State, now: datetime, cfg: Config) -> list[VideoRecord]:
    cutoff = now - timedelta(days=cfg.pending_max_days)
    dropped = []
    for rec in state.videos.values():
        if rec.status in ("pending", "failed") and _published(rec) < cutoff:
            rec.status = "dropped"
            dropped.append(rec)
    return dropped


def _eligible(rec: VideoRecord, cfg: Config) -> bool:
    return rec.status == "pending" or (rec.status == "failed" and rec.attempts < cfg.max_attempts)


def eligible(state: State, cfg: Config) -> list[VideoRecord]:
    """Videos still waiting: pending, or failed with attempts left."""
    return [r for r in state.videos.values() if _eligible(r, cfg)]


def pick(state: State, cfg: Config, require_judged: bool = False) -> list[VideoRecord]:
    """Newest first, at most per_channel_cap per channel and daily_cap in total."""
    candidates = sorted((r for r in eligible(state, cfg) if r.judged or not require_judged),
                        key=_published, reverse=True)
    picked, per_channel = [], {}
    for rec in candidates:
        if len(picked) >= cfg.daily_cap:
            break
        if per_channel.get(rec.channel_id, 0) >= cfg.per_channel_cap:
            continue
        per_channel[rec.channel_id] = per_channel.get(rec.channel_id, 0) + 1
        picked.append(rec)
    return picked


def record_failure(rec: VideoRecord, reason: str, cfg: Config) -> None:
    rec.attempts += 1
    rec.reason = reason
    rec.status = "given_up" if rec.attempts >= cfg.max_attempts else "failed"
