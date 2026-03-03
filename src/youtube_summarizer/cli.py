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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Download and optionally summarize YouTube video transcripts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s dQw4w9WgXcQ -o transcript.txt
  %(prog)s "https://youtu.be/dQw4w9WgXcQ" -t -l en es

  # Summarize with Claude (requires ANTHROPIC_API_KEY):
  %(prog)s "VIDEO_URL" --summarize

  # Summarize with OpenAI (requires OPENAI_API_KEY):
  %(prog)s "VIDEO_URL" -s --model openai:gpt-4o

  # Summarize with a local Ollama model:
  %(prog)s "VIDEO_URL" -s --model ollama:llama3

  # Custom system prompt:
  %(prog)s "VIDEO_URL" -s --prompt "Summarize in Spanish, 3 bullet points max"
        '''
    )

    parser.add_argument(
        'video',
        help='YouTube video URL or video ID'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file path (default: print to stdout)',
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
        help='Summarize the transcript using an AI model',
        action='store_true'
    )
    summarize_group.add_argument(
        '--model',
        help=(
            "AI model in 'provider:model-name' format (default: anthropic:claude-sonnet-4-6). "
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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Extract video ID
    video_id = extract_video_id(args.video)
    if not video_id:
        print(f"Error: Invalid YouTube URL or video ID: {args.video}")
        sys.exit(1)

    print(f"Downloading transcript for video ID: {video_id}")

    # Download transcript
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Create an instance of the API
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
                    # If no English transcript, get the first available one
                    for t in transcript_list:
                        transcript = t
                        break
        else:
            # Get the first available transcript (usually auto-generated English)
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
            except:
                # If no auto-generated English, get the first available transcript
                for t in transcript_list:
                    transcript = t
                    break

        transcript_data = transcript.fetch()

        # Format transcript
        # Convert to raw dict format for compatibility
        formatted_transcript = format_transcript(transcript_data.to_raw_data(), args.timestamps)

        # Output transcript
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(formatted_transcript)
            print(f"Transcript saved to: {args.output}")
        else:
            print("\n--- TRANSCRIPT ---\n")
            print(formatted_transcript)

        # Optional summarization
        if args.summarize:
            _run_summarization(formatted_transcript, args)

    except ImportError:
        print("Error: youtube-transcript-api is not installed.")
        print("Install it with: pip install youtube-transcript-api")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def _run_summarization(transcript_text: str, args: argparse.Namespace) -> None:
    from youtube_summarizer.summarizer import summarize, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT

    model = args.model or DEFAULT_MODEL
    system_prompt = args.prompt or DEFAULT_SYSTEM_PROMPT

    print(f"\nSummarizing with model: {model}")
    try:
        summary = summarize(transcript_text, model=model, system_prompt=system_prompt)
        print("\n--- SUMMARY ---\n")
        print(summary)
    except ImportError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error during summarization: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
