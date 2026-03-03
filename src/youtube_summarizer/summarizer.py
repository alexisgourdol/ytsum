"""AI summarization using pydantic-ai."""

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert at summarizing YouTube video transcripts. "
    "Produce a clear, concise summary capturing the main topics, key points, "
    "and conclusions. Use bullet points for key takeaways."
)


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
                       Examples: 'anthropic:claude-sonnet-4-6', 'openai:gpt-4o',
                       'ollama:llama3', 'groq:llama-3.1-70b-versatile'
        system_prompt: System prompt / instructions for the AI.

    Returns:
        Summary string from the model.
    """
    try:
        from pydantic_ai import Agent
    except ImportError:
        raise ImportError(
            "pydantic-ai is required for summarization.\n"
            "Install it with: pip install 'youtube-summarizer[anthropic]'"
        )

    agent = Agent(model, instructions=system_prompt)
    result = agent.run_sync(
        f"Please summarize the following YouTube transcript:\n\n{transcript}"
    )
    return result.output
