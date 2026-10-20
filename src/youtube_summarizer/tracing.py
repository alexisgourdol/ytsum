"""
Opt-in OpenTelemetry tracing of a run, sent over OTLP/HTTP to a local
Arize Phoenix (or any other OTLP backend).

Nothing here imports the OpenTelemetry SDK until start() is called, so
untraced runs load none of it.
"""

import os
import socket
import sys
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "http://localhost:6006/v1/traces"
CONNECT_TIMEOUT_S = 0.5
EXPORT_TIMEOUT_S = 5
INSTALL_HINT = (
    "Tracing needs the [trace] extra. Install it with: "
    "uv tool install --reinstall '.[anthropic,trace]'"
)


class TracingUnavailable(Exception):
    """The tracing dependencies aren't installed."""


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def requested(flag: bool) -> bool:
    """True when --trace was passed or YTSUM_TRACE is set."""
    return flag or _truthy(os.environ.get("YTSUM_TRACE"))


def endpoint() -> str:
    """OTLP/HTTP traces URL, following the standard OTEL_EXPORTER_OTLP_* variables."""
    traces = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if traces:
        return traces
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if base:
        return base.rstrip("/") + "/v1/traces"
    return DEFAULT_ENDPOINT


def _reachable(url: str) -> bool:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname, port), timeout=CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


def _default_exporter():
    """OTLP exporter for endpoint(), or None (with a warning) if nothing listens there."""
    url = endpoint()
    # Checked up front: the exporter retries an unreachable collector for
    # several seconds, which would stall the CLI.
    if not _reachable(url):
        print(
            f"Warning: no trace collector at {url}; running without tracing. "
            "Start Phoenix with: phoenix serve",
            file=sys.stderr,
        )
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter(endpoint=url, timeout=EXPORT_TIMEOUT_S)


class Tracer:
    """Spans for one CLI run; shutdown() flushes them and turns instrumentation off."""

    def __init__(self, provider):
        self._provider = provider
        self._tracer = provider.get_tracer("ytsum")

    def span(self, name: str, **attributes):
        return self._tracer.start_as_current_span(name, attributes=attributes)

    def shutdown(self) -> None:
        from pydantic_ai import Agent
        Agent.instrument_all(False)
        self._provider.shutdown()


@contextmanager
def span(tracer: Optional[Tracer], name: str, **attributes):
    """
    A span when tracing is on, otherwise a no-op.

    The CLI reports failures with sys.exit(1), which OpenTelemetry doesn't
    count as an error, so a non-zero exit marks the span as failed here.
    """
    if tracer is None:
        yield None
        return
    with tracer.span(name, **attributes) as current:
        try:
            yield current
        except SystemExit as e:
            if e.code not in (0, None):
                from opentelemetry.trace import Status, StatusCode
                current.set_status(Status(StatusCode.ERROR, f"exited with code {e.code}"))
            raise


def start() -> Optional[Tracer]:
    """
    Set up tracing and instrument every pydantic-ai agent created afterwards.

    Returns None (after a warning) if no collector is reachable.
    Raises TracingUnavailable if the [trace] extra isn't installed.
    """
    try:
        from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: F401
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        raise TracingUnavailable(INSTALL_HINT) from e

    exporter = _default_exporter()
    if exporter is None:
        return None

    provider = TracerProvider(resource=Resource.create({
        "service.name": "ytsum",
        # Phoenix files traces under this project name.
        "openinference.project.name": "ytsum",
    }))
    # Adds the OpenInference attributes Phoenix's LLM views read (prompt, response, tokens).
    provider.add_span_processor(OpenInferenceSpanProcessor())
    # Exported in the background and flushed by shutdown(), so a slow collector
    # never delays the run or inflates the logged model-call time.
    provider.add_span_processor(BatchSpanProcessor(exporter))

    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider, include_content=True))
    return Tracer(provider)
