"""Tests for the exporter module."""

import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import date

from youtube_summarizer.exporter import (
    sanitize_filename,
    build_filename,
    build_markdown,
    write_markdown,
)


class TestSanitizeFilename:
    def test_replaces_pipe_with_dash(self):
        assert sanitize_filename("title | subtitle") == "title - subtitle"

    def test_replaces_os_unsafe_chars(self):
        for char in ['<', '>', ':', '"', '/', '\\', '?', '*']:
            result = sanitize_filename(f"a{char}b")
            assert result == "a-b", f"Expected 'a-b' for char '{char}', got '{result}'"

    def test_strips_leading_trailing_spaces(self):
        assert sanitize_filename("  title  ") == "title"

    def test_strips_leading_trailing_dots(self):
        assert sanitize_filename("...title...") == "title"

    def test_leaves_normal_text_unchanged(self):
        assert sanitize_filename("My Great Video") == "My Great Video"

    def test_handles_empty_string(self):
        assert sanitize_filename("") == ""


class TestBuildFilename:
    def test_format_includes_date_topic_title(self):
        with patch("youtube_summarizer.exporter.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026-03-03"
            result = build_filename("LLM", "Anthropic releases Claude 4")
        assert result == "2026-03-03 LLM - Anthropic releases Claude 4.md"

    def test_sanitizes_topic_and_title(self):
        with patch("youtube_summarizer.exporter.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026-03-03"
            result = build_filename("LLM", "Video | With Pipe")
        assert result == "2026-03-03 LLM - Video - With Pipe.md"

    def test_ends_with_md_extension(self):
        result = build_filename("general", "My Note")
        assert result.endswith(".md")


class TestBuildMarkdown:
    def test_contains_title_as_heading(self):
        content = build_markdown("My Title", "abc123", "LLM", "## Summary\ntext")
        assert "# My Title" in content

    def test_contains_video_url(self):
        content = build_markdown("Title", "dQw4w9WgXcQ", "LLM", "summary")
        assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in content

    def test_contains_topic(self):
        content = build_markdown("Title", "abc123", "LLM", "summary")
        assert "**Topic**: LLM" in content

    def test_contains_summary(self):
        content = build_markdown("Title", "abc123", "LLM", "## Summary\nGreat video.")
        assert "## Summary\nGreat video." in content

    def test_contains_date(self):
        with patch("youtube_summarizer.exporter.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026-03-03"
            content = build_markdown("Title", "abc123", "LLM", "summary")
        assert "**Date**: 2026-03-03" in content


class TestWriteMarkdown:
    def test_creates_file_with_content(self, tmp_path):
        path = write_markdown(str(tmp_path), "note.md", "# Hello")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# Hello"

    def test_returns_path_object(self, tmp_path):
        result = write_markdown(str(tmp_path), "note.md", "content")
        assert isinstance(result, Path)

    def test_requires_existing_directory(self, tmp_path):
        nested_dir = str(tmp_path / "a" / "b" / "c")
        with pytest.raises(FileNotFoundError):
            write_markdown(nested_dir, "note.md", "content")

    def test_filename_in_output_path(self, tmp_path):
        path = write_markdown(str(tmp_path), "my-note.md", "content")
        assert path.name == "my-note.md"

    def test_raises_if_directory_does_not_exist(self, tmp_path):
        missing = str(tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError, match="Output directory does not exist"):
            write_markdown(missing, "note.md", "content")
