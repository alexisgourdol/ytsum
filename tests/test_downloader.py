"""Tests for downloader module"""

import pytest
from youtube_summarizer.downloader import (
    extract_video_id,
    format_timestamp,
    format_transcript,
    download_transcript,
)


class TestExtractVideoId:
    """Tests for extract_video_id function"""

    def test_extract_from_watch_url(self):
        """Test extraction from standard watch URL"""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_short_url(self):
        """Test extraction from youtu.be short URL"""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_embed_url(self):
        """Test extraction from embed URL"""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_v_url(self):
        """Test extraction from /v/ URL format"""
        url = "https://www.youtube.com/v/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_direct_video_id(self):
        """Test with direct video ID (11 characters)"""
        video_id = "dQw4w9WgXcQ"
        assert extract_video_id(video_id) == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        """Test with invalid URL"""
        assert extract_video_id("https://example.com") is None

    def test_invalid_video_id(self):
        """Test with invalid video ID (wrong length)"""
        assert extract_video_id("short") is None
        assert extract_video_id("toolongvideoid123") is None

    def test_empty_string(self):
        """Test with empty string"""
        assert extract_video_id("") is None

    def test_url_with_additional_params(self):
        """Test URL with additional query parameters"""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"
        assert extract_video_id(url) == "dQw4w9WgXcQ"


class TestFormatTimestamp:
    """Tests for format_timestamp function"""

    def test_seconds_only(self):
        """Test formatting with seconds only"""
        assert format_timestamp(45.5) == "00:45"

    def test_minutes_and_seconds(self):
        """Test formatting with minutes and seconds"""
        assert format_timestamp(125.0) == "02:05"

    def test_hours_minutes_seconds(self):
        """Test formatting with hours, minutes, and seconds"""
        assert format_timestamp(3661.0) == "01:01:01"

    def test_zero_time(self):
        """Test formatting with zero time"""
        assert format_timestamp(0) == "00:00"

    def test_exact_hour(self):
        """Test formatting with exact hour"""
        assert format_timestamp(3600) == "01:00:00"

    def test_large_time(self):
        """Test formatting with large time value"""
        assert format_timestamp(7325.5) == "02:02:05"

    def test_fractional_seconds(self):
        """Test that fractional seconds are truncated"""
        assert format_timestamp(65.999) == "01:05"


class TestFormatTranscript:
    """Tests for format_transcript function"""

    def test_format_without_timestamps(self):
        """Test formatting transcript without timestamps"""
        transcript_data = [
            {'start': 0.0, 'text': 'Hello world'},
            {'start': 2.5, 'text': 'This is a test'},
        ]
        result = format_transcript(transcript_data, include_timestamps=False)
        assert result == "Hello world\nThis is a test"

    def test_format_with_timestamps(self):
        """Test formatting transcript with timestamps"""
        transcript_data = [
            {'start': 0.0, 'text': 'Hello world'},
            {'start': 65.0, 'text': 'One minute in'},
        ]
        result = format_transcript(transcript_data, include_timestamps=True)
        assert result == "[00:00] Hello world\n[01:05] One minute in"

    def test_empty_transcript(self):
        """Test formatting empty transcript"""
        result = format_transcript([], include_timestamps=False)
        assert result == ""

    def test_single_entry(self):
        """Test formatting transcript with single entry"""
        transcript_data = [{'start': 0.0, 'text': 'Single line'}]
        result = format_transcript(transcript_data, include_timestamps=False)
        assert result == "Single line"

    def test_multiline_text(self):
        """Test formatting with multiple entries"""
        transcript_data = [
            {'start': 0.0, 'text': 'Line 1'},
            {'start': 1.0, 'text': 'Line 2'},
            {'start': 2.0, 'text': 'Line 3'},
        ]
        result = format_transcript(transcript_data, include_timestamps=False)
        assert result == "Line 1\nLine 2\nLine 3"


class TestDownloadTranscript:
    """Tests for download_transcript function (with mocking)"""

    def test_download_transcript_success(self, mocker):
        """Test successful transcript download"""
        # Mock the YouTubeTranscriptApi class
        mock_api_class = mocker.patch('youtube_transcript_api.YouTubeTranscriptApi')

        # Create mock instance, transcript list, and transcript
        mock_api_instance = mocker.MagicMock()
        mock_transcript_list = mocker.MagicMock()
        mock_transcript = mocker.MagicMock()

        # Set up the mock chain
        mock_api_class.return_value = mock_api_instance
        mock_api_instance.list.return_value = mock_transcript_list

        # Mock FetchedTranscript with to_raw_data() method
        mock_fetched = mocker.MagicMock()
        mock_fetched.to_raw_data.return_value = [
            {'start': 0.0, 'text': 'Hello'},
            {'start': 1.0, 'text': 'World'},
        ]
        mock_transcript.fetch.return_value = mock_fetched
        mock_transcript_list.find_generated_transcript.return_value = mock_transcript

        result = download_transcript('dQw4w9WgXcQ')
        assert result == "Hello\nWorld"
        mock_api_instance.list.assert_called_once_with('dQw4w9WgXcQ')

    def test_download_transcript_with_languages(self, mocker):
        """Test transcript download with language preference"""
        # Mock the YouTubeTranscriptApi class
        mock_api_class = mocker.patch('youtube_transcript_api.YouTubeTranscriptApi')

        # Create mock instance, transcript list, and transcript
        mock_api_instance = mocker.MagicMock()
        mock_transcript_list = mocker.MagicMock()
        mock_transcript = mocker.MagicMock()

        # Set up the mock chain
        mock_api_class.return_value = mock_api_instance
        mock_api_instance.list.return_value = mock_transcript_list

        # Mock FetchedTranscript with to_raw_data() method
        mock_fetched = mocker.MagicMock()
        mock_fetched.to_raw_data.return_value = [
            {'start': 0.0, 'text': 'Hola'},
            {'start': 1.0, 'text': 'Mundo'},
        ]
        mock_transcript.fetch.return_value = mock_fetched
        mock_transcript_list.find_transcript.return_value = mock_transcript

        result = download_transcript('dQw4w9WgXcQ', languages=['es'])
        assert result == "Hola\nMundo"
        mock_api_instance.list.assert_called_once_with('dQw4w9WgXcQ')

    def test_download_transcript_fallback(self, mocker):
        """Test transcript download with language fallback"""
        # Mock the YouTubeTranscriptApi class
        mock_api_class = mocker.patch('youtube_transcript_api.YouTubeTranscriptApi')

        # Create mock instance, transcript list, and transcript
        mock_api_instance = mocker.MagicMock()
        mock_transcript_list = mocker.MagicMock()
        mock_transcript = mocker.MagicMock()

        # Set up the mock chain
        mock_api_class.return_value = mock_api_instance
        mock_api_instance.list.return_value = mock_transcript_list

        # Mock FetchedTranscript with to_raw_data() method
        mock_fetched = mocker.MagicMock()
        mock_fetched.to_raw_data.return_value = [
            {'start': 0.0, 'text': 'Hello'},
        ]
        mock_transcript.fetch.return_value = mock_fetched

        # First language fails, second succeeds
        def find_transcript_side_effect(lang_list):
            if lang_list == ['fr']:
                raise Exception("Not found")
            return mock_transcript

        mock_transcript_list.find_transcript.side_effect = find_transcript_side_effect

        result = download_transcript('dQw4w9WgXcQ', languages=['fr', 'en'])
        assert "Hello" in result


class TestDownloadTranscriptIntegration:
    """Integration tests with real YouTube API (run manually)"""

    @pytest.mark.integration
    def test_download_real_video(self):
        """Test downloading transcript from a real YouTube video"""
        # Use a video with verified captions
        video_id = "rfDvkSkelhg"

        result = download_transcript(video_id)

        # Basic assertions
        assert result is not None
        assert len(result) > 0
        assert isinstance(result, str)
        print(f"\nDownloaded transcript length: {len(result)} characters")
        print(f"First 200 characters: {result[:200]}")
