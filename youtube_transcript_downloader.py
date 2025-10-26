#!/usr/bin/env python3
"""
YouTube Transcript Downloader
Downloads transcripts from YouTube videos using video URL or ID.
"""

import argparse
import re
import sys
from typing import Optional


def extract_video_id(url_or_id: str) -> Optional[str]:
    """
    Extract video ID from YouTube URL or return the ID if already provided.

    Args:
        url_or_id: YouTube URL or video ID

    Returns:
        Video ID or None if invalid
    """
    # If it's already a video ID (11 characters, alphanumeric)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id

    # Try to extract from various YouTube URL formats
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/v\/([a-zA-Z0-9_-]{11})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    return None


def download_transcript(video_id: str, languages: list = None) -> str:
    """
    Download transcript for a YouTube video.

    Args:
        video_id: YouTube video ID
        languages: List of language codes to try (e.g., ['en', 'es'])

    Returns:
        Transcript text as a string
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("Error: youtube-transcript-api is not installed.")
        print("Install it with: pip install youtube-transcript-api")
        sys.exit(1)

    try:
        if languages:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            # Try to find transcript in specified languages
            transcript = None
            for lang in languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    break
                except:
                    continue

            if not transcript:
                # Fall back to any available transcript
                transcript = transcript_list.find_generated_transcript(['en'])
        else:
            # Get transcript in any available language
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
            return format_transcript(transcript_data)

        # Fetch and format the transcript
        transcript_data = transcript.fetch()
        return format_transcript(transcript_data)

    except Exception as e:
        print(f"Error downloading transcript: {e}")
        sys.exit(1)


def format_transcript(transcript_data: list, include_timestamps: bool = False) -> str:
    """
    Format transcript data into readable text.

    Args:
        transcript_data: List of transcript entries
        include_timestamps: Whether to include timestamps

    Returns:
        Formatted transcript text
    """
    lines = []

    for entry in transcript_data:
        if include_timestamps:
            timestamp = format_timestamp(entry['start'])
            lines.append(f"[{timestamp}] {entry['text']}")
        else:
            lines.append(entry['text'])

    return '\n'.join(lines)


def format_timestamp(seconds: float) -> str:
    """
    Format seconds into HH:MM:SS timestamp.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


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

        if args.languages:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
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
                transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
            else:
                transcript_data = transcript.fetch()
        else:
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id)

        # Format transcript
        formatted_transcript = format_transcript(transcript_data, args.timestamps)

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
