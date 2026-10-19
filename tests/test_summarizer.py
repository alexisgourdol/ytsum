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
        result = summarize("transcript text", model="anthropic:claude-sonnet-5-5")

        mock_agent_class.assert_called_once_with(
            "anthropic:claude-sonnet-5-5",
            instructions=mocker.ANY,
        )
        mock_instance.run_sync.assert_called_once()
        assert result == "Great summary."

    def test_summarize_uses_default_model(self, mocker):
        """summarize() defaults to anthropic:claude-haiku-5-5"""
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


class TestSummarizeRun:
    """Tests for summarize_run(), which also returns token usage"""

    def test_returns_output_and_usage(self):
        """summarize_run() returns the model output and the run's usage"""
        from pydantic_ai.models.test import TestModel
        from youtube_summarizer.summarizer import summarize_run

        result = summarize_run("transcript", model=TestModel(custom_output_text="A summary."))

        assert result.output == "A summary."
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0
        assert result.usage.requests == 1
        assert result.duration_s >= 0


def _summary_result(output="This is the summary.", input_tokens=1_000, output_tokens=100, duration_s=2.5):
    from pydantic_ai.usage import RunUsage
    from youtube_summarizer.summarizer import SummaryResult
    usage = RunUsage(input_tokens=input_tokens, output_tokens=output_tokens, requests=1)
    return SummaryResult(output=output, usage=usage, duration_s=duration_s)


def _args(**overrides):
    values = dict(model=None, prompt=None, title="My note", topic="LLM")
    values.update(overrides)
    return argparse.Namespace(**values)


def _logged_runs(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id")]
    finally:
        conn.close()


class TestCliSummarization:
    """Tests for _get_summary() in cli.py"""

    def test_get_summary_returns_summary_string(self, mocker):
        """_get_summary() returns the output from summarize_run()"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result("This is the summary."),
        )

        from youtube_summarizer.cli import _get_summary
        summary, _ = _get_summary("fake transcript", _args())

        assert summary == "This is the summary."

    def test_get_summary_passes_model_override(self, mocker):
        """_get_summary() forwards --model to summarize_run()"""
        mock_run = mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result(),
        )

        from youtube_summarizer.cli import _get_summary
        _get_summary("transcript", _args(model="openai:gpt-4o"))

        mock_run.assert_called_once_with(
            "transcript",
            model="openai:gpt-4o",
            system_prompt=mocker.ANY,
        )

    def test_get_summary_passes_prompt_override(self, mocker):
        """_get_summary() forwards --prompt to summarize_run()"""
        mock_run = mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result(),
        )

        from youtube_summarizer.cli import _get_summary
        _get_summary("transcript", _args(prompt="Be very brief."))

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["system_prompt"] == "Be very brief."

    def test_get_summary_import_error_exits_1(self, mocker):
        """_get_summary() exits with code 1 on ImportError"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            side_effect=ImportError("pydantic-ai is required"),
        )

        from youtube_summarizer.cli import _get_summary
        with pytest.raises(SystemExit) as exc:
            _get_summary("transcript", _args())
        assert exc.value.code == 1

    def test_get_summary_generic_error_exits_1(self, mocker):
        """_get_summary() exits with code 1 on unexpected errors"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            side_effect=Exception("API rate limit"),
        )

        from youtube_summarizer.cli import _get_summary
        with pytest.raises(SystemExit) as exc:
            _get_summary("transcript", _args())
        assert exc.value.code == 1

    def test_get_summary_returns_usage_line(self, mocker):
        """_get_summary() returns the line showing tokens, cost and time"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result(input_tokens=12_345, output_tokens=678, duration_s=4.21),
        )

        from youtube_summarizer.cli import _get_summary
        _, line = _get_summary("transcript", _args())

        assert line == "Tokens: 12,345 in / 678 out · ~$0.0016 · 4.2s"

    def test_get_summary_logs_successful_run(self, isolated_run_log):
        """A real (test-model) run is recorded with its tokens and sizes"""
        from youtube_summarizer.cli import _get_summary
        summary, _ = _get_summary("a transcript", _args(model="test"), video_id="dQw4w9WgXcQ")

        [row] = _logged_runs(isolated_run_log)
        assert row["status"] == "ok"
        assert row["video_id"] == "dQw4w9WgXcQ"
        assert row["title"] == "My note"
        assert row["topic"] == "LLM"
        assert row["model"] == "test"
        assert row["input_tokens"] > 0
        assert row["output_tokens"] > 0
        assert row["requests"] == 1
        assert row["est_cost_usd"] is None
        assert row["transcript_chars"] == len("a transcript")
        assert row["summary_chars"] == len(summary)
        assert row["duration_s"] >= 0
        assert row["error"] is None

    def test_get_summary_logs_cost_and_model_call_duration(self, mocker, isolated_run_log):
        """The logged cost comes from the price table, the duration from the model call"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result(input_tokens=10_000, output_tokens=1_000, duration_s=7.5),
        )

        from youtube_summarizer.cli import _get_summary
        _get_summary("transcript", _args())

        [row] = _logged_runs(isolated_run_log)
        assert row["model"] == "anthropic:claude-haiku-5-5"
        assert row["est_cost_usd"] == pytest.approx(0.0015)
        assert row["duration_s"] == 7.5

    def test_get_summary_logs_unknown_model_cost_as_null(self, mocker, isolated_run_log):
        """A model without a price is logged with no cost"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            return_value=_summary_result(),
        )

        from youtube_summarizer.cli import _get_summary
        _get_summary("transcript", _args(model="openai:gpt-4o"))

        [row] = _logged_runs(isolated_run_log)
        assert row["est_cost_usd"] is None

    def test_get_summary_logs_failed_run(self, mocker, isolated_run_log):
        """A model failure is recorded with status=error before exiting"""
        mocker.patch(
            "youtube_summarizer.summarizer.summarize_run",
            side_effect=Exception("API rate limit"),
        )

        from youtube_summarizer.cli import _get_summary
        with pytest.raises(SystemExit):
            _get_summary("transcript", _args(), video_id="dQw4w9WgXcQ")

        [row] = _logged_runs(isolated_run_log)
        assert row["status"] == "error"
        assert row["error"] == "API rate limit"
        assert row["input_tokens"] is None
        assert row["est_cost_usd"] is None


class TestCliUsageLine:
    """The usage line is printed once the summary is out"""

    def test_usage_line_follows_summary(self, mocker, capsys, isolated_run_log):
        mock_api_class = mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")
        mock_fetched = (
            mock_api_class.return_value.list.return_value
            .find_generated_transcript.return_value.fetch.return_value
        )
        mock_fetched.to_raw_data.return_value = [{"text": "hello", "start": 0.0, "duration": 1.0}]

        import sys
        mocker.patch.object(sys, "argv", ["youtube-summarizer", "dQw4w9WgXcQ", "--summarize", "--model", "test"])

        from youtube_summarizer.cli import main
        main()

        out = capsys.readouterr().out
        assert out.index("--- SUMMARY ---") < out.index("Tokens: ")
        assert len(_logged_runs(isolated_run_log)) == 1


class TestCliStats:
    """Tests for the --stats flag"""

    def test_stats_runs_without_video(self, mocker, capsys):
        """--stats prints the stats and never downloads a transcript"""
        mock_api_class = mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")
        import sys
        mocker.patch.object(sys, "argv", ["youtube-summarizer", "--stats"])

        from youtube_summarizer.cli import main
        main()

        assert "No runs recorded yet" in capsys.readouterr().out
        mock_api_class.assert_not_called()

    def test_video_still_required_without_stats(self, mocker, capsys):
        """Without --stats, a missing video argument is still an error"""
        import sys
        mocker.patch.object(sys, "argv", ["youtube-summarizer"])

        from youtube_summarizer.cli import main
        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 2
        assert "the following arguments are required: video" in capsys.readouterr().err


class TestCliNoSummarize:
    """Verify summarize() is never called when --summarize flag is absent"""

    def test_summarize_not_called_without_flag(self, mocker):
        """Without --summarize or --save, _get_summary is never invoked"""
        mock_run_summarization = mocker.patch("youtube_summarizer.cli._get_summary")

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
