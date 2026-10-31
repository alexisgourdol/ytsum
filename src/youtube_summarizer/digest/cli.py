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
    sub = parser.add_subparsers(dest="command")
    chans = sub.add_parser("channels", help="Show or edit the channel list").add_subparsers(dest="action", required=True)
    add = chans.add_parser("add", help="Add a channel by URL, @handle or UC… ID")
    add.add_argument("ref")
    add.add_argument("--bucket", required=True, choices=["vault", "news", "labs", "discovery"])
    add.add_argument("--pin", action="store_true", help="Never remove it in a monthly refresh")
    chans.add_parser("list", help="List channels with their latest upload date")
    return parser


def _channels(args, cfg) -> int:
    import os

    from youtube_summarizer.digest import channels, youtube
    from youtube_summarizer.digest.config import load_env_file

    if args.action == "list":
        rows = []
        feeds = youtube.Feeds(cfg.feed_delay_s)
        for c in channels.load_channels():
            try:
                feed = feeds.fetch(c.channel_id)
                latest = max((e.published[:10] for e in feed), default="-")
            except youtube.FeedError:
                latest = "feed error"
            except youtube.YouTubeBlocked as e:
                print(f"Stopped: YouTube is blocking this IP ({e})")
                return 1
            rows.append((c.bucket, c.name, "pinned" if c.pinned else "", latest, c.channel_id))
        for row in sorted(rows):
            print("  ".join(row))
        print(f"{len(rows)} channels")
        return 0

    load_env_file(cfg.env_file)
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        print("Error: YOUTUBE_API_KEY is not set")
        return 1
    try:
        new = channels.resolve_channel(args.ref, api_key, bucket=args.bucket, pinned=args.pin)
    except (ValueError, youtube.YouTubeApiError) as e:
        print(f"Error: {e}")
        return 1
    chs = channels.load_channels()
    if any(c.channel_id == new.channel_id for c in chs):
        print(f"{new.name} is already in the list")
        return 0
    channels.save_channels(chs + [new])
    print(f"Added {new.name} ({new.channel_id}) to {new.bucket}")
    return 0


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    if args.command == "channels":
        return _channels(args, cfg)

    from youtube_summarizer.digest.pipeline import run_digest
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
