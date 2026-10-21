"""One digest run, from feeds to the digest note. Plain Python except the judge, summary and deep-dive calls."""

import logging
import os
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from youtube_summarizer import runlog
from youtube_summarizer.downloader import TranscriptError, download_transcript
from youtube_summarizer.digest import channels, judge, llm, notes, select, state as st, youtube
from youtube_summarizer.digest.config import Config, data_dir, load_env_file
from youtube_summarizer.digest.notes import DigestReport

log = logging.getLogger("ytsum.digest")


class FatalError(Exception):
    """The run cannot go on (missing key, no channels); reported at the top of the digest."""


def _label(rec: st.VideoRecord) -> str:
    return f"{rec.title} · {rec.channel_name}"


def _url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


class _Run:
    def __init__(self, cfg: Config, now: datetime):
        self.cfg, self.now, self.day = cfg, now, now.date()
        self.report = DigestReport()
        self.state = st.load_state()
        self.entries: dict[str, youtube.FeedEntry] = {}
        self.transcripts: dict[str, str] = {}

    def fail(self, rec: st.VideoRecord, reason: str) -> None:
        select.record_failure(rec, reason, self.cfg)
        if rec.status == "given_up":
            self.report.given_up.append(f"{_label(rec)}: {reason} ({_url(rec.video_id)})")
        else:
            self.report.failures.append(f"{_label(rec)}: {reason} (attempt {rec.attempts}/{self.cfg.max_attempts})")

    def check_keys(self) -> str:
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            raise FatalError("YOUTUBE_API_KEY is not set")
        if self.cfg.mode == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise FatalError("ANTHROPIC_API_KEY is not set (needed in api mode)")
        return api_key

    def discover(self, chs: list[channels.Channel]) -> None:
        for c in chs:
            try:
                feed = youtube.fetch_feed(c.channel_id)
            except youtube.FeedError as e:
                self.report.failures.append(f"{c.name}: {e}")
                continue
            for e in feed:
                self.entries[e.video_id] = e
            select.register_new(self.state, feed, self.now, self.cfg)
        for rec in select.drop_expired(self.state, self.now, self.cfg):
            self.report.dropped.append(f"{_label(rec)} ({_url(rec.video_id)})")

    def triage(self, api_key: str) -> None:
        """Metadata filter, transcripts and the judge, for waiting videos not judged yet."""
        todo = [r for r in select.eligible(self.state, self.cfg) if not r.judged]
        if not todo:
            return
        try:
            meta = youtube.fetch_video_meta([r.video_id for r in todo], api_key)
        except youtube.YouTubeApiError as e:
            self.report.failures.append(f"YouTube Data API: {e} (videos wait for the next run)")
            return
        items = []
        for rec in todo:
            m = meta.get(rec.video_id)
            if m is None:
                rec.status, rec.reason = "skipped", "not available (private, deleted or members-only)"
                self.report.skipped.append(f"{_label(rec)}: {rec.reason}")
                continue
            rec.duration_s = m.duration_s
            reason = youtube.skip_reason(m, self.cfg.shorts_max_seconds)
            if reason:
                rec.status, rec.reason = "skipped", reason
                self.report.skipped.append(f"{_label(rec)}: {reason}")
                continue
            transcript = self.transcript(rec)
            if transcript is None:
                continue
            entry = self.entries.get(rec.video_id) or youtube.FeedEntry(
                rec.video_id, rec.channel_id, rec.channel_name, rec.title, rec.published, "")
            items.append((entry, transcript))
        try:
            verdicts = judge.judge(items, self.cfg)
        except (judge.JudgeError, llm.LlmError) as e:
            for entry, _ in items:
                self.fail(self.state.videos[entry.video_id], f"judge failed: {e}")
            return
        for vid, v in verdicts.items():
            rec = self.state.videos.get(vid)
            if rec is None:
                continue
            if not v.on_topic or v.fully_sponsored:
                what = "fully sponsored" if v.fully_sponsored else "off-topic"
                rec.status, rec.reason = "skipped", f"{what}: {v.reason}"
                self.report.skipped.append(f"{_label(rec)}: {rec.reason}")
            else:
                rec.judged = True
        st.save_state(self.state)

    def transcript(self, rec: st.VideoRecord) -> Optional[str]:
        if rec.video_id not in self.transcripts:
            try:
                self.transcripts[rec.video_id] = download_transcript(rec.video_id)
            except TranscriptError as e:
                self.fail(rec, str(e))
                return None
        return self.transcripts[rec.video_id]

    def summarize(self) -> None:
        cfg = self.cfg
        for rec in select.pick(self.state, cfg, require_judged=True):
            transcript = self.transcript(rec)
            if transcript is None:
                continue
            try:
                r = llm.complete(notes.SHORT_NOTE_PROMPT, transcript, model=cfg.summary_model,
                                 mode=cfg.mode, kind="summary", video_id=rec.video_id, title=rec.title)
            except llm.LlmError as e:
                self.fail(rec, f"summary failed: {e}")
                continue
            short, transcript_path, _ = notes.note_paths(cfg.vault_dir, self.day, rec.title, rec.video_id, cfg.topic_tag)
            suggested = notes.parse_deep_dive_verdict(r.text)
            transcript_path.write_text(notes.render_transcript(transcript))
            short.write_text(notes.render_short_note(rec, r.text, suggested, self.day, transcript_path.stem, cfg.topic_tag))
            rec.status, rec.reason, rec.note_path = "done", "", str(short)
            st.save_state(self.state)
            duration = notes._duration(rec.duration_s)
            self.report.new.append(
                f"[[{short.stem}]] · {rec.channel_name} · {duration} · deep dive: {'yes' if suggested else 'no'}")
        for rec in select.eligible(self.state, cfg):
            if rec.judged:
                self.report.carried_over.append(_label(rec))

    def deep_dive_failed(self, note: Path, reason: str) -> None:
        attempts = notes.deep_dive_attempts(notes.read_frontmatter(note)) + 1
        notes.set_frontmatter(note, "deep_dive_attempts", str(attempts))
        if attempts >= self.cfg.max_attempts:
            self.report.given_up.append(f"Deep dive for [[{note.stem}]]: {reason}")
        else:
            self.report.failures.append(
                f"Deep dive for [[{note.stem}]]: {reason} (attempt {attempts}/{self.cfg.max_attempts})")

    def deep_dives(self) -> None:
        cfg = self.cfg
        requests = notes.find_deep_dive_requests(cfg.vault_dir, cfg.deep_dive_cap, cfg.max_attempts)
        if not requests:
            return
        try:
            system = notes.deep_dive_prompt(cfg.skill_path.read_text())
        except OSError as e:
            self.report.failures.append(f"Deep dives: cannot read {cfg.skill_path}: {e}")
            return
        for note in requests:
            transcript_path = note.with_name(note.stem + notes.SUFFIX_TRANSCRIPT + ".md")
            deep_path = note.with_name(note.stem + notes.SUFFIX_DEEP_DIVE + ".md")
            if not transcript_path.exists():
                self.deep_dive_failed(note, "no saved transcript")
                continue
            transcript = transcript_path.read_text().removeprefix("## Transcript").strip()
            fm = notes.read_frontmatter(note)
            try:
                r = llm.complete(system, transcript, model=cfg.deep_dive_model, mode=cfg.mode,
                                 kind="deep_dive", video_id=fm.get("video_id"), title=note.stem)
            except llm.LlmError as e:
                self.deep_dive_failed(note, str(e))
                continue
            deep_path.write_text(r.text.strip() + "\n")
            notes.set_frontmatter(note, "deep_dive_note", f'"[[{deep_path.stem}]]"')
            self.report.deep_dives.append(f"[[{deep_path.stem}]]")


def _usage_since(started_iso: str) -> list[tuple]:
    path = runlog.db_path()
    if not path.exists():
        return []
    conn = sqlite3.connect(path, timeout=10)
    try:
        return conn.execute(
            "SELECT model, kind, COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            "SUM(est_cost_usd) FROM runs WHERE topic = 'digest' AND timestamp >= ? "
            "GROUP BY model, kind ORDER BY model, kind",
            (started_iso,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _setup_logging() -> None:
    if log.handlers:
        return
    handler = logging.FileHandler(data_dir() / "digest.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def run_digest(cfg: Config, now: datetime, *, once_per_day: bool) -> Optional[DigestReport]:
    """Run once; None if skipped (already ran today, or another run holds the lock)."""
    if once_per_day and st.already_ran_today(now.date()):
        return None
    with st.acquire_lock() as got:
        if not got:
            return None
        if once_per_day:
            st.mark_ran_today(now.date())
        return _run_locked(cfg, now)


def _run_locked(cfg: Config, now: datetime) -> DigestReport:
    _setup_logging()
    # Same format as runlog timestamps (UTC), so string comparison is time comparison.
    started_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run = _Run(cfg, now)
    # The session-start hook passes this when it couldn't update the .digest-main worktree.
    if os.environ.get("YTSUM_DIGEST_UPDATE_FAILED"):
        run.report.failures.append(f"Running old code: {os.environ['YTSUM_DIGEST_UPDATE_FAILED']}")
    try:
        load_env_file(cfg.env_file)
        api_key = run.check_keys()
        chs = channels.load_channels()
        if not chs:
            raise FatalError("the channel list is empty (youtube-summarizer digest channels add ...)")
        run.report.channel_changes = channels.maybe_refresh(cfg, run.state, now, api_key)
        run.discover(channels.load_channels())
        run.triage(api_key)
        run.summarize()
        run.deep_dives()
        run.state.first_run_done = True
        st.save_state(run.state)
    except FatalError as e:
        run.report.fatal = str(e)
        log.error("run failed: %s", e)
    except Exception as e:
        run.report.fatal = f"{type(e).__name__}: {e}"
        log.error("run crashed:\n%s", traceback.format_exc())
    run.report.usage = _usage_since(started_iso)
    path = notes.write_digest(cfg.vault_dir, now.date(), notes.render_digest(run.report, now.date()))
    log.info("digest written to %s", path)
    return run.report
