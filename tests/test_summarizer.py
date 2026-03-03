"""Tests for summarizer module and CLI summarization integration"""

import argparse
import pytest
from unittest.mock import MagicMock


class TestSummarize:
    """Tests for the summarize() function"""

    def test_summarize_calls_agent_with_model_and_instructions(self, mocker):
        """summarize() creates an Agent with the correct model and instructions"""
        mock_agent_class = mocker.patch("pydantic_ai.Agent")
        mock_instance = MagicMock()
        mock_instance.run_sync.return_value = MagicMock(output="Great summary.")
        mock_agent_class.return_value = mock_instance

        from youtube_summarizer.summarizer import summarize
        result = summarize("transcript text", model="anthropic:claude-sonnet-4-6")

        mock_agent_class.assert_called_once_with(
            "anthropic:claude-sonnet-4-6",
            instructions=mocker.ANY,
        )
        mock_instance.run_sync.assert_called_once()
        assert result == "Great summary."

    def test_summarize_uses_default_model(self, mocker):
        """summarize() defaults to anthropic:claude-sonnet-4-6"""
        mock_agent_class = mocker.patch("pydantic_ai.Agent")
        mock_instance = MagicMock()
        mock_instance.run_sync.return_value = MagicMock(output="summary")
        mock_agent_class.return_value = mock_instance

        from youtube_summarizer.summarizer import summarize, DEFAULT_MODEL
        summarize("text")

        call_args = mock_agent_class.call_args
        assert call_args[0][0] == DEFAULT_MODEL

    def test_summarize_forwards_custom_system_prompt(self, mocker):
        """summarize() passes a custom system_prompt as instructions"""
        mock_agent_class = mocker.patch("pydantic_ai.Agent")
        mock_instance = MagicMock()
        mock_instance.run_sync.return_value = MagicMock(output="summary")
        mock_agent_class.return_value = mock_instance

        from youtube_summarizer.summarizer import summarize
        summarize("text", system_prompt="Be very brief.")

        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs["instructions"] == "Be very brief."

    def test_summarize_transcript_is_included_in_prompt(self, mocker):
        """summarize() includes the transcript text in the run_sync call"""
        mock_agent_class = mocker.patch("pydantic_ai.Agent")
        mock_instance = MagicMock()
        mock_instance.run_sync.return_value = MagicMock(output="summary")
        mock_agent_class.return_value = mock_instance

        from youtube_summarizer.summarizer import summarize
        summarize("my unique transcript content")

        prompt_arg = mock_instance.run_sync.call_args[0][0]
        assert "my unique transcript content" in prompt_arg

    def test_summarize_returns_output_string(self, mocker):
        """summarize() returns the .output attribute of the agent result"""
        mock_agent_class = mocker.patch("pydantic_ai.Agent")
        mock_instance = MagicMock()
        mock_instance.run_sync.return_value = MagicMock(output="The video is about cats.")
        mock_agent_class.return_value = mock_instance

        from youtube_summarizer.summarizer import summarize
        result = summarize("transcript")

        assert result == "The video is about cats."


class TestSummarizeMissingDependency:
    """Tests for graceful handling of missing pydantic-ai"""

    def test_import_error_raised_when_pydantic_ai_missing(self, mocker):
        """summarize() raises ImportError with install hint if pydantic_ai is absent"""
        mocker.patch.dict("sys.modules", {"pydantic_ai": None})

        # Re-import to pick up the patched sys.modules
        import importlib
        import youtube_summarizer.summarizer as summarizer_module
        importlib.reload(summarizer_module)

        with pytest.raises(ImportError, match="pip install"):
            summarizer_module.summarize("text")

        # Restore module state
        importlib.reload(summarizer_module)


class TestCliSummarization:
    """Tests for _run_summarization() in cli.py"""

    def test_run_summarization_prints_summary(self, mocker, capsys):
        """_run_summarization() prints the summary to stdout"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize",
            return_value="This is the summary.",
        )

        from youtube_summarizer.cli import _run_summarization
        args = argparse.Namespace(model=None, prompt=None)
        _run_summarization("fake transcript", args)

        captured = capsys.readouterr()
        assert "SUMMARY" in captured.out
        assert "This is the summary." in captured.out

    def test_run_summarization_passes_model_override(self, mocker):
        """_run_summarization() forwards --model to summarize()"""
        mock_summarize = mocker.patch(
            "youtube_summarizer.summarizer.summarize",
            return_value="summary",
        )

        from youtube_summarizer.cli import _run_summarization
        args = argparse.Namespace(model="openai:gpt-4o", prompt=None)
        _run_summarization("transcript", args)

        mock_summarize.assert_called_once_with(
            "transcript",
            model="openai:gpt-4o",
            system_prompt=mocker.ANY,
        )

    def test_run_summarization_passes_prompt_override(self, mocker):
        """_run_summarization() forwards --prompt to summarize()"""
        mock_summarize = mocker.patch(
            "youtube_summarizer.summarizer.summarize",
            return_value="summary",
        )

        from youtube_summarizer.cli import _run_summarization
        args = argparse.Namespace(model=None, prompt="Be very brief.")
        _run_summarization("transcript", args)

        call_kwargs = mock_summarize.call_args[1]
        assert call_kwargs["system_prompt"] == "Be very brief."

    def test_run_summarization_import_error_exits_1(self, mocker):
        """_run_summarization() exits with code 1 on ImportError"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize",
            side_effect=ImportError("pydantic-ai is required"),
        )

        from youtube_summarizer.cli import _run_summarization
        args = argparse.Namespace(model=None, prompt=None)
        with pytest.raises(SystemExit) as exc:
            _run_summarization("transcript", args)
        assert exc.value.code == 1

    def test_run_summarization_generic_error_exits_1(self, mocker):
        """_run_summarization() exits with code 1 on unexpected errors"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize",
            side_effect=Exception("API rate limit"),
        )

        from youtube_summarizer.cli import _run_summarization
        args = argparse.Namespace(model=None, prompt=None)
        with pytest.raises(SystemExit) as exc:
            _run_summarization("transcript", args)
        assert exc.value.code == 1


class TestCliNoSummarize:
    """Verify summarize() is never called when --summarize flag is absent"""

    def test_summarize_not_called_without_flag(self, mocker):
        """Without --summarize, _run_summarization is never invoked"""
        mock_run_summarization = mocker.patch("youtube_summarizer.cli._run_summarization")

        # Mock the transcript download pipeline
        mock_api_class = mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        mock_transcript_list = MagicMock()
        mock_api.list.return_value = mock_transcript_list
        mock_transcript = MagicMock()
        mock_transcript_list.find_generated_transcript.return_value = mock_transcript
        mock_fetched = MagicMock()
        mock_transcript.fetch.return_value = mock_fetched
        mock_fetched.to_raw_data.return_value = [{"text": "hello", "start": 0.0, "duration": 1.0}]

        import sys
        mocker.patch.object(sys, "argv", ["youtube-summarizer", "dQw4w9WgXcQ"])

        from youtube_summarizer.cli import main
        main()

        mock_run_summarization.assert_not_called()
