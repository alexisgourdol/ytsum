"""
One entry point for every digest LLM call, with two backends:
- api:          pydantic-ai on the Anthropic API (ANTHROPIC_API_KEY, billed per token)
- subscription: `claude -p` on the Claude Code subscription login
Every call, ok or not, is written to the run log with its tokens.
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

from youtube_summarizer.pricing import estimate_cost
from youtube_summarizer.runlog import record_run

SUBSCRIPTION_TIMEOUT_S = 900


class LlmError(Exception):
    """An LLM call failed (already logged)."""


@dataclass
class LlmResult:
    text: str
    input_tokens: int  # including cache reads and writes, like the run log
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    duration_s: float
    log_model: str


def subscription_command(model: str, system: str) -> list[str]:
    # Never --bare: bare mode only accepts ANTHROPIC_API_KEY, not the subscription login.
    return [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]


def subscription_env() -> dict:
    """Without ANTHROPIC_API_KEY Claude Code uses the subscription; the marker stops hook recursion."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["YTSUM_DIGEST_CHILD"] = "1"
    return env


def _run_subscription(system: str, user: str, model: str) -> LlmResult:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ytsum-digest-") as cwd:
        proc = subprocess.run(
            subscription_command(model, system), input=user, capture_output=True, text=True,
            cwd=cwd, env=subscription_env(), timeout=SUBSCRIPTION_TIMEOUT_S,
        )
    duration_s = time.monotonic() - started
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = None
    if proc.returncode != 0 or not isinstance(data, dict) or data.get("is_error"):
        detail = (data or {}).get("result") if isinstance(data, dict) else None
        raise LlmError(f"claude -p failed (exit {proc.returncode}): {detail or proc.stderr.strip() or proc.stdout[:500]}")
    usage = data.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    return LlmResult(
        text=data.get("result", ""),
        input_tokens=(usage.get("input_tokens", 0) or 0) + cache_read + cache_write,
        output_tokens=usage.get("output_tokens", 0) or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        duration_s=data.get("duration_ms", duration_s * 1000) / 1000,
        log_model=f"claude-code:{model}",
    )


def _run_api(system: str, user: str, model: str) -> LlmResult:
    from youtube_summarizer import summarizer

    result = summarizer.summarize_run(user, model=f"anthropic:{model}", system_prompt=system, user_prefix="")
    u = result.usage
    return LlmResult(
        text=result.output,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_tokens,
        cache_write_tokens=u.cache_write_tokens,
        duration_s=result.duration_s,
        log_model=f"anthropic:{model}",
    )


def complete(
    system: str,
    user: str,
    *,
    model: str,
    mode: str,
    kind: str,
    video_id: Optional[str] = None,
    title: Optional[str] = None,
) -> LlmResult:
    """
    Run one LLM call and log it. kind is judge, summary or deep_dive.

    Raises:
        ValueError: unknown mode.
        LlmError:   the call failed; an error row has been logged.
    """
    backends = {"api": _run_api, "subscription": _run_subscription}
    if mode not in backends:
        raise ValueError(f"Unknown mode {mode!r}: use 'api' or 'subscription'")
    prefix = "anthropic" if mode == "api" else "claude-code"
    row = {"video_id": video_id, "title": title, "topic": "digest", "kind": kind,
           "model": f"{prefix}:{model}", "transcript_chars": len(user)}

    started = time.monotonic()
    try:
        r = backends[mode](system, user, model)
    except Exception as e:
        record_run({**row, "duration_s": time.monotonic() - started, "status": "error", "error": str(e)})
        raise e if isinstance(e, LlmError) else LlmError(str(e)) from e

    record_run({
        **row,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cache_read_tokens": r.cache_read_tokens,
        "cache_write_tokens": r.cache_write_tokens,
        "requests": 1,
        "est_cost_usd": estimate_cost(model, r.input_tokens, r.output_tokens,
                                      cache_read_tokens=r.cache_read_tokens,
                                      cache_write_tokens=r.cache_write_tokens),
        "duration_s": r.duration_s,
        "summary_chars": len(r.text),
        "status": "ok",
    })
    return r
