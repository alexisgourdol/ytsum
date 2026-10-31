"""Files the digest writes into the vault: short notes, transcripts, deep dives, the daily digest note."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from youtube_summarizer.exporter import sanitize_filename
from youtube_summarizer.digest.state import VideoRecord

SHORT_NOTE_PROMPT = """You summarize a YouTube video transcript for a daily AI digest that its reader skims every morning.

Write exactly these three markdown sections and nothing else:

## Summary
A few short paragraphs of prose: what the video is about, the main argument or system, and what is new or useful in it.

## Key Takeaways
3-5 bullet points with the most important points.

## Deep dive?
Start with "Yes" or "No", then one sentence explaining why. Answer Yes for hands-on tutorials with commands, prompts or workflows worth keeping verbatim; No for news, opinion or overviews this summary already covers.

Write in the language of the transcript."""

SUFFIX_TRANSCRIPT = " - transcript"
SUFFIX_DEEP_DIVE = " - deep dive"


def _duration(seconds) -> str:
    if not seconds:
        return ""
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def read_frontmatter(path: Path) -> dict[str, str]:
    """Top-level `key: value` pairs of a note's YAML frontmatter, values unquoted (no YAML library)."""
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    values = {}
    for line in text[3:end].splitlines():
        if not line or line[0] in " \t-#" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value.strip()
    return values


def set_frontmatter(path: Path, key: str, value: str) -> None:
    """Set one top-level frontmatter line (value written as given), leaving every other byte as it was."""
    text = path.read_text()
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    if pattern.search(head):
        head = pattern.sub(lambda _: f"{key}: {value}", head, count=1)
    else:
        head = f"{head}\n{key}: {value}"
    path.write_text(head + rest)


def is_true(value: str) -> bool:
    return value.strip().strip("\"'").strip().lower() in ("true", "yes", "1")


def note_paths(vault_dir: Path, day: date, title: str, video_id: str, topic: str = "LLM") -> tuple[Path, Path, Path]:
    """(short note, transcript, deep dive) paths; a different video with the same title gets its ID appended."""
    # Obsidian wikilinks break on [ ] # ^ |, so the digest's own names drop them.
    name = re.sub(r"[\[\]#^|]", "", sanitize_filename(title)).strip()
    name = re.sub(r"\s{2,}", " ", name)
    if not re.search(r"\w", name):
        name = video_id
    base = f"{day.isoformat()} {topic} - {name}"
    short = vault_dir / f"{base}.md"
    if short.exists() and read_frontmatter(short).get("video_id") != video_id:
        base = f"{base} ({video_id})"
        short = vault_dir / f"{base}.md"
    return short, vault_dir / f"{base}{SUFFIX_TRANSCRIPT}.md", vault_dir / f"{base}{SUFFIX_DEEP_DIVE}.md"


def render_short_note(rec: VideoRecord, body: str, deep_dive_suggested: bool, day: date,
                      transcript_name: str, topic: str = "LLM") -> str:
    url = f"https://www.youtube.com/watch?v={rec.video_id}"
    channel = rec.channel_name.replace('"', "'")
    return (
        "---\n"
        f"video_id: {rec.video_id}\n"
        f"url: {url}\n"
        f'channel: "{channel}"\n'
        f"published: {rec.published}\n"
        f"duration: {_duration(rec.duration_s)}\n"
        f"digest_date: {day.isoformat()}\n"
        f"deep_dive_suggested: {'true' if deep_dive_suggested else 'false'}\n"
        "deep_dive: false\n"
        'deep_dive_note: ""\n'
        "---\n\n"
        f"# {rec.title}\n\n"
        f"**Date**: {day.isoformat()}\n"
        f"**URL**: {url}\n"
        f"**Channel**: {rec.channel_name}\n"
        f"**Topic**: {topic}\n\n"
        f"{body.strip()}\n\n"
        f"Transcript: [[{transcript_name.removesuffix('.md')}]]\n"
    )


def render_transcript(transcript: str) -> str:
    return f"## Transcript\n\n{transcript}\n"


def parse_deep_dive_verdict(markdown: str) -> bool:
    m = re.search(r"^##\s*Deep dive\?\s*$(.*)", markdown, re.M | re.S)
    if not m:
        return False
    words = re.findall(r"[A-Za-z]+", m.group(1))
    return bool(words) and words[0].lower() == "yes"


def deep_dive_attempts(fm: dict[str, str]) -> int:
    try:
        return int(fm.get("deep_dive_attempts", "0") or 0)
    except ValueError:
        return 0


def find_deep_dive_requests(vault_dir: Path, cap: int, max_attempts: int = 3) -> list[Path]:
    """
    Digest notes waiting for a deep dive: ticked by the reader first, then model-suggested; newest first.
    Notes whose deep dive already failed max_attempts times are left out.
    """
    flagged, suggested = [], []
    for path in vault_dir.glob("*.md"):
        if path.stem.endswith((SUFFIX_TRANSCRIPT, SUFFIX_DEEP_DIVE)):
            continue
        fm = read_frontmatter(path)
        if "digest_date" not in fm or fm.get("deep_dive_note", "") or deep_dive_attempts(fm) >= max_attempts:
            continue
        key = (fm["digest_date"], path.name)
        if is_true(fm.get("deep_dive", "")):
            flagged.append((key, path))
        elif is_true(fm.get("deep_dive_suggested", "")):
            suggested.append((key, path))
    ordered = [p for _, p in sorted(flagged, reverse=True)] + [p for _, p in sorted(suggested, reverse=True)]
    return ordered[:cap]


def deep_dive_prompt(skill_text: str) -> str:
    return f"{skill_text.rstrip()}\n\nThe transcript is below. Ignore the fetch and save steps; output only the summary markdown."


@dataclass
class DigestReport:
    new: list[str] = field(default_factory=list)
    deep_dives: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    carried_over: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    given_up: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    channel_changes: list[str] = field(default_factory=list)
    # (log_model, kind, calls, input_tokens, output_tokens, est_cost_usd or None)
    usage: list[tuple] = field(default_factory=list)
    fatal: str = ""
    blocked: str = ""  # "<step>: <reason>" when a YouTube block stopped the run


def render_digest(report: DigestReport, day: date) -> str:
    lines = [f"# Digest {day.isoformat()}", ""]
    if report.fatal:
        lines += [f"**Run failed: {report.fatal}** — see `~/.local/share/ytsum/digest/digest.log`.", ""]
    if report.blocked:
        lines += [f"**Run stopped: YouTube is blocking this IP** (step: {report.blocked}). "
                  "No more YouTube requests this run; the digest is paused (see `paused_until`).", ""]
    sections = [
        ("Channel list changes", report.channel_changes),
        ("New videos", report.new),
        ("Deep dives written", report.deep_dives),
        ("Skipped", report.skipped),
        ("Carried over to tomorrow", report.carried_over),
        ("Failures (retried next run)", report.failures),
        ("Given up", report.given_up),
        ("Dropped (waited over 14 days)", report.dropped),
    ]
    for heading, items in sections:
        if items:
            lines += [f"## {heading}", ""] + [f"- {item}" for item in items] + [""]
    if report.usage:
        lines += ["## Usage", "", "| model | kind | calls | tokens in | tokens out | est. cost |", "|---|---|---|---|---|---|"]
        for model, kind, calls, tin, tout, cost in report.usage:
            cost_text = "n/a" if cost is None else f"${cost:.4f}"
            lines.append(f"| {model} | {kind} | {calls} | {tin:,} | {tout:,} | {cost_text} |")
        lines.append("")
    return "\n".join(lines)


def write_digest(vault_dir: Path, day: date, text: str) -> Path:
    path = vault_dir / f"{day.isoformat()} digest.md"
    if path.exists():
        with path.open("a") as fh:
            fh.write(f"\n## Run {datetime.now().strftime('%H:%M')}\n\n{text}")
    else:
        path.write_text(text)
    return path
