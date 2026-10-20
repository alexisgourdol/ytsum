#!/usr/bin/env python3
"""
CLI entry point for YouTube Summarizer
"""

import argparse
import sys

from youtube_summarizer.downloader import (
    extract_video_id,
    format_transcript,
)
from youtube_summarizer.exporter import DEFAULT_SAVE_DIR
from youtube_summarizer import tracing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Download and optionally summarize YouTube video transcripts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s dQw4w9WgXcQ -o transcript.txt
  %(prog)s "https://youtu.be/dQw4w9WgXcQ" -t -l en es

  # Summarize to stdout with Claude (requires ANTHROPIC_API_KEY):
  %(prog)s "VIDEO_URL" --summarize

  # Save as an Obsidian note:
  %(prog)s "VIDEO_URL" --save "/path/to/vault/01-zettlekasten" --topic LLM --title "My Note Title"

  # Summarize to stdout AND save:
  %(prog)s "VIDEO_URL" --summarize --save "/path/to/vault" --topic LLM --title "My Note Title"

  # Use a different model:
  %(prog)s "VIDEO_URL" --summarize --model openai:gpt-4o

  # Token usage, cost and timing of past runs, by model:
  %(prog)s --stats

  # Trace a run in a local Phoenix (http://localhost:6006):
  %(prog)s "VIDEO_URL" --summarize --trace
        '''
    )

    parser.add_argument(
        'video',
        help='YouTube video URL or video ID',
        nargs='?',
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file path for the transcript (default: print to stdout)',
        default=None
    )
    parser.add_argument(
        '-t', '--timestamps',
        help='Include timestamps in the transcript',
        action='store_true'
    )
    parser.add_argument(
        '-l', '--languages',
        help='Preferred language codes (e.g., en es fr)',
        nargs='+',
        default=None
    )

    summarize_group = parser.add_argument_group('summarization options')
    summarize_group.add_argument(
        '-s', '--summarize',
        help='Summarize the transcript and print to stdout',
        action='store_true'
    )
    summarize_group.add_argument(
        '--model',
        help=(
            "AI model in 'provider:model-name' format (default: anthropic:claude-haiku-5-5). "
            "Examples: openai:gpt-4o, ollama:llama3, groq:llama-3.1-70b-versatile"
        ),
        default=None,
        metavar='MODEL'
    )
    summarize_group.add_argument(
        '--prompt',
        help='Custom system prompt override for the AI model',
        default=None,
        metavar='PROMPT'
    )
    summarize_group.add_argument(
        '--save',
        help=(
            'Save summary as a markdown note. '
            'Optionally specify a directory; omit to use DEFAULT_SAVE_DIR from exporter.py'
        ),
        nargs='?',
        const=DEFAULT_SAVE_DIR,  # used when --save is passed without a directory
        default=None,            # used when --save is not passed at all
        metavar='DIR'
    )
    summarize_group.add_argument(
        '--topic',
        help="Topic tag used in the markdown filename (default: general). Example: LLM",
        default='general',
        metavar='TOPIC'
    )
    summarize_group.add_argument(
        '--title',
        help="Note title used in the markdown filename and heading (default: general)",
        default='general',
        metavar='TITLE'
    )
    summarize_group.add_argument(
        '--include-transcript',
        help='Append the full transcript under a ## Transcript section in the saved note',
        action='store_true'
    )

    parser.add_argument(
        '--trace',
        help=(
            'Send an OpenTelemetry trace of this run to a local Phoenix '
            '(or OTEL_EXPORTER_OTLP_ENDPOINT); also enabled by YTSUM_TRACE=1. '
            "Needs the [trace] extra"
        ),
        action='store_true'
    )
    parser.add_argument(
        '--stats',
        help='Show token usage, cost and timing of past runs by model, then exit',
        action='store_true'
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.stats:
        from youtube_summarizer.runlog import render_stats
        print(render_stats())
        return
    if not args.video:
        parser.error("the following arguments are required: video")

    # Extract video ID
    video_id = extract_video_id(args.video)
    if not video_id:
        print(f"Error: Invalid YouTube URL or video ID: {args.video}")
        sys.exit(1)

    print(f"Downloading transcript for video ID: {video_id}")

    tracer = None
    if tracing.requested(args.trace):
        try:
            tracer = tracing.start()
        except tracing.TracingUnavailable as e:
            print(f"Error: {e}")
            sys.exit(1)

    from youtube_summarizer.summarizer import DEFAULT_MODEL
    try:
        with tracing.span(tracer, "ytsum run", video_id=video_id, model=args.model or DEFAULT_MODEL, topic=args.topic):
            _run(args, video_id, tracer)
    finally:
        if tracer:
            tracer.shutdown()


def _run(args: argparse.Namespace, video_id: str, tracer=None) -> None:
    """Download the transcript, then print, summarize and save as asked."""
    # Download transcript
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        with tracing.span(tracer, "transcript fetch"):
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)

            if args.languages:
                transcript = None

                for lang in args.languages:
                    try:
                        transcript = transcript_list.find_transcript([lang])
                        print(f"Found transcript in language: {lang}")
                        break
                    except:
                        continue

                if not transcript:
                    print(f"No transcript found in languages: {args.languages}")
                    print("Trying to get any available transcript...")
                    try:
                        transcript = transcript_list.find_generated_transcript(['en'])
                    except:
                        for t in transcript_list:
                            transcript = t
                            break
            else:
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                except:
                    for t in transcript_list:
                        transcript = t
                        break

            transcript_data = transcript.fetch()
            formatted_transcript = format_transcript(transcript_data.to_raw_data(), args.timestamps)

        # Output transcript
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(formatted_transcript)
            print(f"Transcript saved to: {args.output}")
        else:
            print("\n--- TRANSCRIPT ---\n")
            print(formatted_transcript)

        # Summarization (triggered by --summarize or --save)
        if args.summarize or args.save:
            summary, usage_line = _get_summary(formatted_transcript, args, video_id=video_id)
            if args.summarize:
                print("\n--- SUMMARY ---\n")
                print(summary)
            if args.save:
                transcript = formatted_transcript if args.include_transcript else None
                _save_note(summary, video_id, args, transcript=transcript)
            print(f"\n{usage_line}")

    except ImportError:
        print("Error: youtube-transcript-api is not installed.")
        print("Install it with: pip install youtube-transcript-api")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _get_summary(
    transcript_text: str, args: argparse.Namespace, video_id: str | None = None
) -> tuple[str, str]:
    """Summarize and log the run. Returns the summary and its one-line usage summary."""
    import time

    from youtube_summarizer.pricing import estimate_cost
    from youtube_summarizer.runlog import format_usage_line, record_run
    from youtube_summarizer.summarizer import summarize_run, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT

    model = args.model or DEFAULT_MODEL
    system_prompt = args.prompt or DEFAULT_SYSTEM_PROMPT
    run = {
        "video_id": video_id,
        "title": args.title,
        "topic": args.topic,
        "model": model,
        "transcript_chars": len(transcript_text),
    }

    print(f"\nSummarizing with model: {model}")
    started = time.monotonic()
    try:
        result = summarize_run(transcript_text, model=model, system_prompt=system_prompt)
    except Exception as e:
        record_run({**run, "duration_s": time.monotonic() - started, "status": "error", "error": str(e)})
        if isinstance(e, ImportError):
            print(f"Error: {e}")
        else:
            print(f"Error during summarization: {e}")
        sys.exit(1)

    usage = result.usage
    cost = estimate_cost(
        model,
        usage.input_tokens,
        usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    record_run({
        **run,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "requests": usage.requests,
        "est_cost_usd": cost,
        "duration_s": result.duration_s,
        "summary_chars": len(result.output),
        "status": "ok",
    })
    usage_line = format_usage_line(usage.input_tokens, usage.output_tokens, cost, result.duration_s)
    return result.output, usage_line


def _save_note(summary: str, video_id: str, args: argparse.Namespace, transcript: str | None = None) -> None:
    from youtube_summarizer.exporter import build_filename, build_markdown, write_markdown

    if not args.save:
        print("Error: no save directory specified. Pass a path to --save or set the YTSUM_SAVE_DIR environment variable.")
        sys.exit(1)
    filename = build_filename(args.topic, args.title)
    content = build_markdown(args.title, video_id, args.topic, summary, transcript=transcript)
    try:
        path = write_markdown(args.save, filename, content)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"\nNote saved to: {path}")


if __name__ == '__main__':
    main()
