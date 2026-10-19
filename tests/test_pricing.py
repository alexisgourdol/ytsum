"""Tests for pricing module"""

import pytest
from youtube_summarizer.pricing import estimate_cost


class TestEstimateCost:
    """Tests for estimate_cost function"""

    def test_haiku_input_and_output(self):
        """Haiku 5.5: $0.10 in / $0.50 out per million tokens"""
        cost = estimate_cost("anthropic:claude-haiku-5-5", input_tokens=10_000, output_tokens=1_000)
        assert cost == pytest.approx(10_000 * 0.10 / 1e6 + 1_000 * 0.50 / 1e6)

    def test_bare_model_name_without_provider(self):
        """A model name without the provider prefix is priced the same"""
        assert estimate_cost("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.00)

    def test_haiku_long_prompt_uses_higher_tier(self):
        """Haiku 5.5 prompts over 100K tokens: $0.50 in / $2.50 out"""
        cost = estimate_cost("anthropic:claude-haiku-5-5", input_tokens=200_000, output_tokens=1_000)
        assert cost == pytest.approx(200_000 * 0.50 / 1e6 + 1_000 * 2.50 / 1e6)

    def test_cache_tokens_priced_separately(self):
        """input_tokens includes cache tokens; those are billed at cache rates"""
        cost = estimate_cost(
            "anthropic:claude-sonnet-5-5",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_tokens=500_000,
            cache_write_tokens=100_000,
        )
        # 400K uncached at $2, 500K cache reads at $0.20, 100K cache writes at 1.25 x $2
        assert cost == pytest.approx(0.4 * 2.00 + 0.5 * 0.20 + 0.1 * 2.50)

    def test_other_provider_prefix_returns_none(self):
        """Claude served through another provider has other prices: no guess"""
        assert estimate_cost("google-vertex:claude-sonnet-5-5", 1_000, 100) is None
        assert estimate_cost("bedrock:claude-sonnet-5-5", 1_000, 100) is None

    def test_unknown_model_returns_none(self):
        """Models missing from the table get no cost, never a guess"""
        assert estimate_cost("openai:gpt-4o", 1_000, 100) is None
