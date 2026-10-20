"""AI summarization using pydantic-ai."""

import time
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "anthropic:claude-haiku-5-5"
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert at summarizing YouTube video transcripts. "
    "Structure your response with exactly these two markdown sections:\n\n"
    "## Summary\n"
    "A clear, concise summary of the main topics and conclusions.\n\n"
    "## Key Takeaways\n"
    "3-5 bullet points of the most important points from the video."
)


@dataclass
class SummaryResult:
    """A summary, the token usage of the run that produced it, and how long the model call took."""
    output: str
    usage: Any  # pydantic_ai.usage.RunUsage; pydantic-ai is imported lazily
    duration_s: float


def summarize(
    transcript: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """
    Summarize a YouTube transcript using an AI model via pydantic-ai.

    Args:
        transcript:    The formatted transcript text to summarize.
        model:         Model string in 'provider:model-name' format.
                       Examples: 'anthropic:claude-haiku-5-5', 'openai:gpt-4o',
                       'ollama:llama3', 'groq:llama-3.1-70b-versatile'
        system_prompt: System prompt / instructions for the AI.

    Returns:
        Summary string from the model.
    """
    return summarize_run(transcript, model=model, system_prompt=system_prompt).output


def summarize_run(
    transcript: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> SummaryResult:
    """
    Like summarize(), but also returns the run's token usage.

    Returns:
        SummaryResult with the summary, a pydantic-ai RunUsage
        (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, requests)
        and the duration of the model call alone, in seconds.
    """
    try:
        from pydantic_ai import Agent
    except ImportError:
        raise ImportError(
            "pydantic-ai is required for summarization.\n"
            "Install it with: pip install 'youtube-summarizer[anthropic]'"
        )

    import pydantic_ai
    pydantic_ai.BANNER_ENABLED = False  # pydantic-ai 2.x prints an observability ad on every run

    agent = Agent(model, instructions=system_prompt)
    started = time.monotonic()
    result = agent.run_sync(
        f"Please summarize the following YouTube transcript:\n\n{transcript}"
    )
    duration_s = time.monotonic() - started
    # pydantic-ai 2.x exposes usage as a property; 1.x as a method.
    usage = result.usage() if callable(result.usage) else result.usage
    return SummaryResult(output=result.output, usage=usage, duration_s=duration_s)
