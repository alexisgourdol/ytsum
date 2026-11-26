"""Which videos get summarized this run (new ones and retries, within the caps) and which are dropped."""

from datetime import datetime, timedelta

from youtube_summarizer.digest.config import Config
from youtube_summarizer.digest.state import State, VideoRecord
from youtube_summarizer.digest.youtube import FeedEntry


def _published(rec_or_entry) -> datetime:
    return datetime.fromisoformat(rec_or_entry.published)


def register_new(state: State, entries: list[FeedEntry], now: datetime, cfg: Config) -> list[VideoRecord]:
    """
    Add unseen videos as pending. Videos published more than max_age_days ago are
    marked skipped instead, so the run after a pause or a new channel never floods the digest.
    """
    added = []
    cutoff = now - timedelta(days=cfg.max_age_days)
    for e in entries:
        if e.video_id in state.videos:
            continue
        rec = VideoRecord(e.video_id, e.channel_id, e.channel_name, e.title, e.published, "pending")
        if _published(e) < cutoff:
            rec.status, rec.reason = "skipped", f"published over {cfg.max_age_days} days before it was first seen"
        else:
            added.append(rec)
        state.videos[e.video_id] = rec
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


def drop_unpicked(state: State, picked: list[VideoRecord], cfg: Config) -> list[VideoRecord]:
    """
    Mark judged, pending videos this run didn't pick as dropped: nothing carries over (SCP-200).
    Unjudged videos and failed ones with attempts left keep waiting.
    """
    picked_ids = {r.video_id for r in picked}
    dropped = []
    for rec in state.videos.values():
        if rec.status == "pending" and rec.judged and rec.video_id not in picked_ids:
            rec.status, rec.reason = "dropped", f"not in this run's top {cfg.daily_cap}"
            dropped.append(rec)
    return dropped


def record_failure(rec: VideoRecord, reason: str, cfg: Config) -> None:
    rec.attempts += 1
    rec.reason = reason
    rec.status = "given_up" if rec.attempts >= cfg.max_attempts else "failed"
