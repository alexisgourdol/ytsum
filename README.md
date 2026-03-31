# Youtube video summarization script

## Description

**Idea**: use AI to summarize transcripts from a youtube video

**Context**:
The first POC worked in early 2025 using the `fabric` framework.
A new attempt few month later failed (the error message mentionned a Youtube API error but the API calls were working correcly via test and monitoring on the GCP console - error message genereated in a code written by AI so exception handling was likely lacking)

This is another attempt, this time using
- a script that can be used via CLI
    - trying out claude code capabilities
- [Pydantic AI](https://ai.pydantic.dev/) for multi-provider AI summarization (Claude, OpenAI, Gemini, Ollama, and more)


## Features

- Download transcripts from YouTube videos
- Support for multiple URL formats (youtube.com, youtu.be, embed)
- Optional timestamp inclusion
- Multi-language support with fallback
- AI summarization via any Pydantic AI supported provider (opt-in)
- CLI and library usage


## Prerequisites

- Python 3.11+
- [UV package manager](https://docs.astral.sh/uv/getting-started/installation/) - Install with: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- An API key for your chosen AI provider (for summarization)


## Installation

### Quick Install (Recommended)

Install the CLI globally to use `youtube-summarizer` from anywhere:

```bash
# Clone the repository
git clone https://github.com/alexisgourdol/ytsum.git
cd ytsum

# Install globally with UV (transcript only)
uv tool install .

# Install with Claude support
uv tool install '.[anthropic]'

# Install with OpenAI support
uv tool install '.[openai]'

# Install with Gemini support
uv tool install '.[gemini]'

# Reinstall to upgrade an existing installation
uv tool install --reinstall '.[anthropic]'
```

### Development Install

For contributors who want to modify the code:

```bash
# Clone the repository
git clone https://github.com/alexisgourdol/ytsum.git
cd ytsum

# Install dependencies (creates local .venv)
uv sync --extra dev

# Install with Claude support for development
uv sync --extra anthropic --extra dev
```

### Verify Installation

```bash
# Check that it's installed
youtube-summarizer --help
```


## API Key Setup

Summarization requires an API key for your chosen provider. The key is read from an environment variable — nothing is stored in the code.

```bash
# Add to your ~/.zshrc or ~/.bashrc
export ANTHROPIC_API_KEY=$(awk 'NR==1' ~/.claude/api_key)   # Claude
export OPENAI_API_KEY=$(awk 'NR==1' ~/.openai/api_key)       # OpenAI

# Reload your shell config
source ~/.zshrc
```

The `awk 'NR==1'` pattern reads only the first line of the file, which is safe if the file ever has trailing newlines or comments.


## Usage

### CLI Usage (After Global Install)

```bash
# Download transcript from URL
youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"

# Download with timestamps
youtube-summarizer "VIDEO_ID" -t

# Save to file
youtube-summarizer "VIDEO_ID" -o transcript.txt

# Specify language preferences
youtube-summarizer "VIDEO_ID" -l en es fr

# Summarize with Claude (default, requires ANTHROPIC_API_KEY)
youtube-summarizer "VIDEO_URL" --summarize

# Summarize with a specific model
youtube-summarizer "VIDEO_URL" -s --model anthropic:claude-opus-4-6

# Summarize with OpenAI (requires OPENAI_API_KEY)
youtube-summarizer "VIDEO_URL" -s --model openai:gpt-4o

# Summarize with Gemini
youtube-summarizer "VIDEO_URL" -s --model gemini:gemini-2.0-flash

# Summarize with a local Ollama model (no API key needed)
youtube-summarizer "VIDEO_URL" -s --model ollama:llama3

# Custom system prompt
youtube-summarizer "VIDEO_URL" -s --prompt "Summarize in Spanish, 3 bullet points max"
```

### CLI Usage (Development Mode)

If you installed with `uv sync` for development:

```bash
# Run from the project directory
uv run youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Library Usage

```python
from youtube_summarizer import extract_video_id, download_transcript, summarize

# Extract video ID from URL
video_id = extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# Download transcript
transcript = download_transcript(video_id)
print(transcript)

# With language preference
transcript = download_transcript(video_id, languages=['en', 'es'])

# Summarize with default model (Claude)
summary = summarize(transcript)

# Summarize with a different provider
summary = summarize(transcript, model="openai:gpt-4o")
summary = summarize(transcript, model="ollama:llama3")

# Custom system prompt
summary = summarize(transcript, model="anthropic:claude-sonnet-4-6",
                    system_prompt="List the 5 key takeaways as bullet points.")
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
uv run pytest tests/test_summarizer.py

# Run with coverage
uv run pytest --cov=youtube_summarizer
```

### Project Structure

```
ytsum/
├── pyproject.toml           # UV package configuration
├── README.md                # This file
├── src/
│   └── youtube_summarizer/
│       ├── __init__.py      # Package exports
│       ├── downloader.py    # Core transcript functions
│       ├── summarizer.py    # AI summarization via Pydantic AI
│       └── cli.py           # CLI entry point
└── tests/
    ├── __init__.py
    ├── test_downloader.py   # Tests for downloader module
    └── test_summarizer.py   # Tests for summarizer module
```


## Next Steps

- Add topic segmentation
- Implement Q&A generation from transcripts
- Add structured summary output formats (JSON, markdown)
