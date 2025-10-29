# Youtube video summarization script

## Description

**Idea**: use AI to summarize transcripts from a youtube video

**Context**:
The first POC worked in early 2025 using the `fabric` framework.
A new attempt few month later failed (the error message mentionned a Youtube API error but the API calls were working correcly via test and monitoring on the GCP console - error message genereated in a code written by AI so exception handling was likely lacking)

This is another attempt, this time using
- a script that can be used via CLI
    - trying out claude code capabilities
- an integration with claude code for summarization


## Features

- Download transcripts from YouTube videos
- Support for multiple URL formats (youtube.com, youtu.be, embed)
- Optional timestamp inclusion
- Multi-language support with fallback
- CLI and library usage


## Prerequisites

- Python 3.11+
- UV package manager
- Claude Pro or Max plan (for future summarization features)


## Installation

### Using UV (recommended)

```bash
# Clone the repository
cd /workspace

# Install dependencies
uv sync

# Install with dev dependencies (for testing)
uv sync --extra dev
```

### Manual installation

```bash
pip install youtube-transcript-api
```


## Usage

### CLI Usage

```bash
# Using UV
uv run youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"

# Download with timestamps
uv run youtube-summarizer "VIDEO_ID" -t

# Save to file
uv run youtube-summarizer "VIDEO_ID" -o transcript.txt

# Specify language preferences
uv run youtube-summarizer "VIDEO_ID" -l en es fr
```

### Library Usage

```python
from youtube_summarizer import extract_video_id, download_transcript

# Extract video ID from URL
video_id = extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# Download transcript
transcript = download_transcript(video_id)
print(transcript)

# With language preference
transcript = download_transcript(video_id, languages=['en', 'es'])
```


## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_downloader.py

# Run with coverage
uv run pytest --cov=youtube_summarizer
```

### Project Structure

```
/workspace/
├── pyproject.toml           # UV package configuration
├── README.md                # This file
├── src/
│   └── youtube_summarizer/
│       ├── __init__.py      # Package exports
│       ├── downloader.py    # Core transcript functions
│       └── cli.py           # CLI entry point
└── tests/
    ├── __init__.py
    └── test_downloader.py   # Tests for downloader module
```


## Next Steps

- Add AI summarization integration with Claude
- Create structured summary formats
- Add topic segmentation
- Implement Q&A generation from transcripts
