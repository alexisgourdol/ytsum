"""Markdown note generation and file export."""

import re
from datetime import date
from pathlib import Path

DEFAULT_SAVE_DIR = ""


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are unsafe in filenames.

    Replaces | and OS-reserved characters with -, then strips
    leading/trailing spaces and dots.
    """
    name = name.replace("|", "-")
    name = re.sub(r'[<>:"/\\?*]', "-", name)
    return name.strip(". ")


def build_filename(topic: str, title: str) -> str:
    """
    Build a markdown filename in the format: YYYY-MM-DD topic - title.md

    Args:
        topic: Topic tag (e.g. 'LLM', 'general')
        title: Note title

    Returns:
        Sanitized filename string.
    """
    today = date.today().strftime("%Y-%m-%d")
    return f"{today} {sanitize_filename(topic)} - {sanitize_filename(title)}.md"


def build_markdown(title: str, video_id: str, topic: str, summary: str) -> str:
    """
    Build the markdown note content.

    Args:
        title:    Note title (used as the H1 heading)
        video_id: YouTube video ID (used to construct the URL)
        topic:    Topic tag
        summary:  AI-generated summary text (expected to include ## Summary
                  and ## Key Takeaways sections)

    Returns:
        Full markdown content as a string.
    """
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://www.youtube.com/watch?v={video_id}"
    return (
        f"# {title}\n\n"
        f"**Date**: {today}\n"
        f"**URL**: {url}\n"
        f"**Topic**: {topic}\n\n"
        f"{summary}"
    )


def write_markdown(output_dir: str, filename: str, content: str) -> Path:
    """
    Write markdown content to a file, creating parent directories if needed.

    Args:
        output_dir: Directory path to write the file into.
        filename:   Name of the file (including .md extension).
        content:    Markdown content to write.

    Returns:
        Path to the written file.
    """
    dir_path = Path(output_dir)
    if not dir_path.exists():
        raise FileNotFoundError(f"Output directory does not exist: {output_dir}")
    path = dir_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
