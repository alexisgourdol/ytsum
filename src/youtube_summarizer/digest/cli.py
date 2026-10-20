"""`youtube-summarizer digest ...` command line."""

import argparse


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
    build_parser().parse_args(argv)
    return 0
