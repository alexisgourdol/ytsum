"""Tests for opt-in tracing (tracing module and --trace)"""

import socket
import subprocess
import sys
import textwrap

import pytest
from unittest.mock import MagicMock

from youtube_summarizer import tracing


@pytest.fixture(autouse=True)
def no_trace_env(monkeypatch):
    for name in ("YTSUM_TRACE", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def memory_exporter(mocker):
    """Send spans to memory instead of a collector."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    mocker.patch("youtube_summarizer.tracing._default_exporter", return_value=exporter)
    return exporter


def _closed_port_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1/traces"


def _mock_transcript(mocker, text="hello from the video"):
    mock_api_class = mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")
    mock_fetched = (
        mock_api_class.return_value.list.return_value
        .find_generated_transcript.return_value.fetch.return_value
    )
    mock_fetched.to_raw_data.return_value = [{"text": text, "start": 0.0, "duration": 1.0}]


def _run_cli(mocker, *extra_args):
    mocker.patch.object(sys, "argv", ["youtube-summarizer", "dQw4w9WgXcQ", "--summarize", "--model", "test", *extra_args])
    from youtube_summarizer.cli import main
    main()


class TestRequested:
    """Tests for requested()"""

    def test_flag(self):
        assert tracing.requested(True)

    def test_off_by_default(self):
        assert not tracing.requested(False)

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("YTSUM_TRACE", "1")
        assert tracing.requested(False)

    def test_env_var_zero_is_off(self, monkeypatch):
        monkeypatch.setenv("YTSUM_TRACE", "0")
        assert not tracing.requested(False)


class TestEndpoint:
    """Tests for endpoint()"""

    def test_default_is_local_phoenix(self):
        assert tracing.endpoint() == "http://localhost:6006/v1/traces"

    def test_base_endpoint_env(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
        assert tracing.endpoint() == "http://collector:4318/v1/traces"

    def test_traces_endpoint_env_wins(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://other:9999/traces")
        assert tracing.endpoint() == "http://other:9999/traces"


class TestTracedRun:
    """--trace produces one span tree per run"""

    def test_span_tree(self, mocker, memory_exporter):
        _mock_transcript(mocker, text="unique transcript words")
        _run_cli(mocker, "--trace", "--topic", "LLM")

        spans = {s.name: s for s in memory_exporter.get_finished_spans()}
        root = spans["ytsum run"]
        assert root.parent is None
        assert root.attributes["video_id"] == "dQw4w9WgXcQ"
        assert root.attributes["model"] == "test"
        assert root.attributes["topic"] == "LLM"
        assert root.resource.attributes["service.name"] == "ytsum"
        assert root.resource.attributes["openinference.project.name"] == "ytsum"

        fetch = spans["transcript fetch"]
        assert fetch.parent.span_id == root.context.span_id

        llm = next(s for s in spans.values() if s.attributes.get("openinference.span.kind") == "LLM")
        assert llm.attributes["llm.token_count.prompt"] > 0
        assert llm.attributes["llm.token_count.completion"] > 0
        assert "unique transcript words" in llm.attributes["input.value"]
        assert llm.context.trace_id == root.context.trace_id

    def test_env_var_enables_tracing(self, mocker, memory_exporter, monkeypatch):
        monkeypatch.setenv("YTSUM_TRACE", "1")
        _mock_transcript(mocker)
        _run_cli(mocker)

        assert "ytsum run" in {s.name for s in memory_exporter.get_finished_spans()}

    def test_instrumentation_is_reset_after_run(self, mocker, memory_exporter):
        """Agents created after a traced run aren't instrumented any more"""
        from pydantic_ai import Agent
        _mock_transcript(mocker)
        _run_cli(mocker, "--trace")

        # The default that Agent.instrument_all() sets; there is no public getter.
        assert Agent._instrument_default is False


class TestTracedRunTiming:
    """Exporting spans must not slow the run down or inflate the logged model time"""

    def test_slow_collector_does_not_inflate_model_time(self, mocker, isolated_run_log):
        import time
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        class SlowExporter(InMemorySpanExporter):
            def export(self, spans):
                time.sleep(0.5)
                return super().export(spans)

        exporter = SlowExporter()
        mocker.patch("youtube_summarizer.tracing._default_exporter", return_value=exporter)
        _mock_transcript(mocker)
        _run_cli(mocker, "--trace")

        import sqlite3
        conn = sqlite3.connect(isolated_run_log)
        [(duration_s,)] = conn.execute("SELECT duration_s FROM runs").fetchall()
        conn.close()
        assert duration_s < 0.4
        # Spans are still all delivered once the run ends
        assert "ytsum run" in {s.name for s in exporter.get_finished_spans()}


class TestFailedRunSpan:
    """A run that fails is marked as an error on its root span"""

    def _root(self, exporter):
        return next(s for s in exporter.get_finished_spans() if s.name == "ytsum run")

    def test_transcript_failure_marks_root_span(self, mocker, memory_exporter):
        from opentelemetry.trace import StatusCode
        mock_api_class = mocker.patch("youtube_transcript_api.YouTubeTranscriptApi")
        mock_api_class.return_value.list.side_effect = Exception("video unavailable")

        with pytest.raises(SystemExit):
            _run_cli(mocker, "--trace")

        assert self._root(memory_exporter).status.status_code == StatusCode.ERROR

    def test_model_failure_marks_root_span(self, mocker, memory_exporter):
        from opentelemetry.trace import StatusCode
        _mock_transcript(mocker)
        mocker.patch.object(sys, "argv", ["youtube-summarizer", "dQw4w9WgXcQ", "--summarize", "--model", "no-such-provider:model", "--trace"])
        from youtube_summarizer.cli import main
        with pytest.raises(SystemExit):
            main()

        assert self._root(memory_exporter).status.status_code == StatusCode.ERROR

    def test_successful_run_is_not_an_error(self, mocker, memory_exporter):
        from opentelemetry.trace import StatusCode
        _mock_transcript(mocker)
        _run_cli(mocker, "--trace")

        assert self._root(memory_exporter).status.status_code != StatusCode.ERROR


class TestTracingUnavailable:
    """--trace degrades instead of breaking the run"""

    def test_unreachable_collector_warns_and_runs(self, mocker, monkeypatch, capsys, isolated_run_log):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", _closed_port_url())
        _mock_transcript(mocker)
        _run_cli(mocker, "--trace")

        captured = capsys.readouterr()
        assert "Warning: no trace collector at" in captured.err
        assert "--- SUMMARY ---" in captured.out
        import sqlite3
        conn = sqlite3.connect(isolated_run_log)
        assert conn.execute("SELECT status FROM runs").fetchall() == [("ok",)]
        conn.close()

    def test_missing_extra_exits_with_install_hint(self, mocker, capsys):
        mocker.patch.dict("sys.modules", {"opentelemetry.sdk.trace": None})
        _mock_transcript(mocker)
        with pytest.raises(SystemExit) as exc:
            _run_cli(mocker, "--trace")

        assert exc.value.code == 1
        assert "[trace]" in capsys.readouterr().out


class TestUntracedRun:
    """Without --trace nothing changes"""

    def test_no_spans_and_no_sdk_import(self, tmp_path):
        """A normal run loads no OpenTelemetry SDK or exporter"""
        code = textwrap.dedent("""
            import sys
            from unittest.mock import MagicMock, patch
            api = MagicMock()
            api.return_value.list.return_value.find_generated_transcript.return_value \\
                .fetch.return_value.to_raw_data.return_value = [{"text": "hi", "start": 0.0, "duration": 1.0}]
            with patch("youtube_transcript_api.YouTubeTranscriptApi", api):
                from youtube_summarizer.cli import main
                sys.argv = ["youtube-summarizer", "dQw4w9WgXcQ", "--summarize", "--model", "test"]
                main()
            loaded = [m for m in sys.modules if m.startswith(("opentelemetry.sdk", "opentelemetry.exporter", "openinference"))]
            print("LOADED:", loaded)
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={"PATH": "", "YTSUM_RUNS_DB": str(tmp_path / "runs.db"), "HOME": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        assert "LOADED: []" in result.stdout


class TestBanner:
    """pydantic-ai's observability banner is switched off"""

    def test_banner_disabled_after_a_run(self):
        import pydantic_ai
        from pydantic_ai.models.test import TestModel
        from youtube_summarizer.summarizer import summarize_run

        summarize_run("transcript", model=TestModel())

        assert pydantic_ai.BANNER_ENABLED is False
