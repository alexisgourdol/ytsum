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


def main():
    parser = argparse.ArgumentParser(
        description='Download transcripts from YouTube videos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s dQw4w9WgXcQ -o transcript.txt
  %(prog)s "https://youtu.be/dQw4w9WgXcQ" -t -l en es
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

    except ImportError:
        print("Error: youtube-transcript-api is not installed.")
        print("Install it with: pip install youtube-transcript-api")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
