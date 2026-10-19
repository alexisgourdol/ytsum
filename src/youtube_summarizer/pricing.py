"""Estimated cost of a summarization run, from per-model token prices."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""
    input: float
    output: float
    cache_read: float
    cache_write: float


def _price(input: float, output: float, cache_read: Optional[float] = None) -> Price:
    # Cache writes (5-minute TTL) bill at 1.25x input. Where Anthropic lists no
    # cache-read price, use its general 0.1x-input rate.
    return Price(
        input=input,
        output=output,
        cache_read=cache_read if cache_read is not None else input * 0.1,
        cache_write=input * 1.25,
    )


# Anthropic first-party API prices, as listed on 2026-10-06. Add a model here
# to get cost estimates for it; unlisted models are logged with no cost.
PRICES: dict[str, Price] = {
    "claude-haiku-5-5": _price(0.10, 0.50),
    "claude-sonnet-5-5": _price(2.00, 10.00, cache_read=0.20),
    "claude-opus-5-5": _price(4.00, 20.00, cache_read=0.20),
    "claude-fable-5-1": _price(10.00, 50.00, cache_read=0.25),
}

# Prompts above the threshold (in input tokens) are billed at the second price.
LONG_PROMPT_PRICES: dict[str, tuple[int, Price]] = {
    "claude-haiku-5-5": (100_000, _price(0.50, 2.50)),
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Optional[float]:
    """
    Estimate the USD cost of a run, or None if the model has no known price.

    Args:
        model:              Model string, bare or with the 'anthropic:' prefix
                            (e.g. 'anthropic:claude-haiku-5-5').
        input_tokens:       Prompt tokens, including cache reads and writes.
        output_tokens:      Generated tokens.
        cache_read_tokens:  Prompt tokens served from the cache.
        cache_write_tokens: Prompt tokens written to the cache.
    """
    # Only Anthropic's own API is priced: the same model through another
    # provider (Bedrock, Vertex, ...) bills differently, so it gets no estimate.
    name = model.removeprefix("anthropic:")
    price = PRICES.get(name)
    if price is None:
        return None

    long_prompt = LONG_PROMPT_PRICES.get(name)
    if long_prompt and input_tokens > long_prompt[0]:
        price = long_prompt[1]

    uncached = input_tokens - cache_read_tokens - cache_write_tokens
    return (
        uncached * price.input
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
        + output_tokens * price.output
    ) / 1_000_000
