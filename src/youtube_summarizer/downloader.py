"""
YouTube Transcript Downloader
Downloads transcripts from YouTube videos using video URL or ID.
"""

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
        # Create an instance of the API
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        if languages:
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

        # Fetch and format the transcript
        transcript_data = transcript.fetch()
        # Convert to raw dict format for compatibility
        return format_transcript(transcript_data.to_raw_data())

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
