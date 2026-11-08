---
name: ytsum
description: Download and summarize YouTube transcripts, or run a daily digest of new videos from a list of channels, with the youtube-summarizer CLI. Use when asked to summarize a YouTube video, fetch its transcript, or set up or run a video digest.
---

# ytsum

Everything goes through the `youtube-summarizer` CLI. Run the commands below; don't reimplement them.

## Install

Check with `youtube-summarizer --help`. If it's missing, install it with one provider extra (`anthropic`, `openai` or `gemini`):

```bash
uv tool install "youtube-summarizer[anthropic] @ git+https://github.com/alexisgourdol/ytsum"
```

Set the provider's key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GOOGLE_API_KEY`.

## One video

```bash
youtube-summarizer "VIDEO_URL"                              # transcript only, no API key
youtube-summarizer "VIDEO_URL" --summarize                  # summary with the default model
youtube-summarizer "VIDEO_URL" -s --model openai:gpt-4o     # another provider
youtube-summarizer "VIDEO_URL" --save /path/to/folder --topic TOPIC --title "Note title"
```

## Daily digest

The digest writes one short note per new on-topic video into a folder of markdown notes. It uses the Anthropic API, or `--mode subscription` for `claude -p`.

1. Create `~/.local/share/ytsum/digest/config.toml` with the folder for the notes (ask the user which one):

   ```toml
   vault_dir = "/path/to/notes"
   ```

2. Set `YOUTUBE_API_KEY` (YouTube Data API v3) and `ANTHROPIC_API_KEY`, in the environment or in a dotenv file named by `env_file` in `config.toml`.
3. Add channels, then run:

   ```bash
   youtube-summarizer digest channels add https://www.youtube.com/@CHANNEL --bucket news
   youtube-summarizer digest channels list
   youtube-summarizer digest
   ```

A run takes about 10–15 minutes because it paces its YouTube requests. To get a full deep dive, set `deep_dive: true` in a note's frontmatter; the next run writes it.

For a daily schedule, use `youtube-summarizer digest --once-per-day` (recipes in the project README under "Scheduling the digest"). If the digest says it's paused, YouTube blocked this IP: wait for the date it prints.
