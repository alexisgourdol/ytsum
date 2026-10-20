"""`youtube-summarizer digest ...` command line."""

import argparse
from dataclasses import replace
from datetime import datetime, timezone

from youtube_summarizer.digest.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-summarizer digest",
        description="Summarize new videos from the channel list into the Obsidian vault",
    )
    parser.add_argument(
        "--once-per-day", action="store_true",
        help="Do nothing if the digest already ran today (used by the session-start hook)",
    )
    parser.add_argument(
        "--mode", choices=["api", "subscription"],
        help="Override config.toml: Anthropic API key, or claude -p on the Claude subscription",
    )
    parser.add_subparsers(dest="command")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    from youtube_summarizer.digest.pipeline import run_digest

    cfg = load_config()
    if args.mode:
        cfg = replace(cfg, mode=args.mode)
    now = datetime.now(timezone.utc).astimezone()
    report = run_digest(cfg, now, once_per_day=args.once_per_day)
    if report is None:
        print("Digest skipped: already ran today, or another run is in progress.")
        return 0
    print(f"Digest written to {cfg.vault_dir / (now.date().isoformat() + ' digest.md')}")
    if report.fatal:
        print(f"Run failed: {report.fatal}")
        return 1
    return 0
