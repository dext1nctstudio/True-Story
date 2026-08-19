"""Token pricing for the language model calls.

Research spend and model spend are different bills. Parallel is priced per
task run and metered by `BudgetGovernor`; Gemini is priced per token and, until
this module existed, was not counted anywhere. The figure on the cost meter was
therefore the research half only, which understates what a run actually costs.

Prices verified 19 August 2026 against https://ai.google.dev/gemini-api/docs/pricing
and are USD per one million tokens. Gemini 2.5 Pro is tiered on prompt size;
Flash is flat. Re verify before quoting these anywhere that matters.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("truestory.model_cost")

_MILLION = 1_000_000

# Prompts at or under this many tokens use the cheaper Pro tier.
_PRO_TIER_BOUNDARY = 200_000


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per million tokens, with the Pro tier's large prompt surcharge."""

    input_per_m: float
    output_per_m: float
    input_per_m_large: float | None = None
    output_per_m_large: float | None = None
    #: Cached prompt tokens, billed at a fraction of the input rate. A long
    #: screenplay re read at four stages is the case this exists for.
    cached_input_per_m: float | None = None
    cached_input_per_m_large: float | None = None

    def usd(self, prompt_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        large = prompt_tokens > _PRO_TIER_BOUNDARY
        rate_in = self.input_per_m_large if large and self.input_per_m_large else self.input_per_m
        rate_out = (
            self.output_per_m_large if large and self.output_per_m_large else self.output_per_m
        )
        # Cached tokens are counted inside the prompt total by the API, so they
        # are billed at the cached rate and removed from the full price tokens
        # rather than charged twice.
        cached = max(0, min(cached_tokens, prompt_tokens))
        if cached and self.cached_input_per_m is not None:
            rate_cached = (
                self.cached_input_per_m_large
                if large and self.cached_input_per_m_large
                else self.cached_input_per_m
            )
            fresh = prompt_tokens - cached
            return (
                (fresh / _MILLION) * rate_in
                + (cached / _MILLION) * rate_cached
                + (output_tokens / _MILLION) * rate_out
            )
        return (prompt_tokens / _MILLION) * rate_in + (output_tokens / _MILLION) * rate_out


# Order matters: the longest matching prefix wins, so "gemini-2.5-flash-lite"
# must be tested before "gemini-2.5-flash". `price_for` sorts, so the table
# itself stays readable.
_PRICES: dict[str, ModelPrice] = {
    "gemini-2.5-pro": ModelPrice(1.25, 10.00, 2.50, 15.00, 0.125, 0.25),
    "gemini-2.5-flash-lite": ModelPrice(0.10, 0.40, cached_input_per_m=0.01),
    "gemini-2.5-flash": ModelPrice(0.30, 2.50, cached_input_per_m=0.03),
}

# Anything unrecognised is priced as Pro, the most expensive of the two we use.
# Silently costing an unknown model at zero would hide spend, which is the
# failure mode this module exists to remove.
_FALLBACK = _PRICES["gemini-2.5-pro"]


def price_for(model: str) -> ModelPrice:
    name = (model or "").strip().lower()
    # Longest prefix first: "gemini-2.5-flash-lite" must not be priced as
    # "gemini-2.5-flash", which is four times the input rate.
    for known in sorted(_PRICES, key=len, reverse=True):
        if name.startswith(known):
            return _PRICES[known]
    return _FALLBACK


def price_table() -> dict[str, dict[str, float | None]]:
    """The published rates, for the cost panel and the report footer.

    Exposed rather than restated in the UI, so there is one place where a
    price is written down and one date on which it was verified.
    """
    return {
        model: {
            "input_per_m_usd": p.input_per_m,
            "output_per_m_usd": p.output_per_m,
            "input_per_m_usd_large_prompt": p.input_per_m_large,
            "output_per_m_usd_large_prompt": p.output_per_m_large,
            "cached_input_per_m_usd": p.cached_input_per_m,
        }
        for model, p in _PRICES.items()
    }


def usage_from_response(response: Any) -> tuple[int, int, int]:
    """Pull (prompt_tokens, output_tokens, cached_tokens) off a genai response.

    Returns zeros rather than raising when the field is absent: a missing
    usage block must not take down a run that otherwise succeeded.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return 0, 0, 0
    prompt = getattr(meta, "prompt_token_count", 0) or 0
    # Thinking tokens are billed as output on the 2.5 models.
    output = (getattr(meta, "candidates_token_count", 0) or 0) + (
        getattr(meta, "thoughts_token_count", 0) or 0
    )
    # Cached prompt tokens are already inside prompt_token_count and are billed
    # at roughly a tenth of the rate. Ignoring them overstated a long
    # screenplay's model spend on every stage after the first.
    cached = getattr(meta, "cached_content_token_count", 0) or 0
    return int(prompt), int(output), int(cached)


def cost_cents(model: str, prompt_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    return price_for(model).usd(prompt_tokens, output_tokens, cached_tokens) * 100


# ── per run metering ─────────────────────────────────────────────────────────
# The four model calling agents are constructed independently of the budget
# governor, and two runs can be in flight at once, so a module level total
# would blend them. A context variable is inherited by the asyncio tasks a run
# spawns and stays private to that run.
_current_meter: ContextVar[Any | None] = ContextVar("truestory_model_meter", default=None)


def set_meter(governor: Any | None) -> None:
    """Point model metering at this run's budget governor."""
    _current_meter.set(governor)


def meter_response(model: str, response: Any) -> None:
    """Record one model call against the run in scope, if there is one.

    Never raises. Cost accounting must not be able to fail a run that has
    already produced its answer.
    """
    governor = _current_meter.get()
    if governor is None:
        return
    try:
        prompt, output, cached = usage_from_response(response)
        if prompt or output:
            governor.record_model(model, prompt, output, cached)
    except Exception:
        log.debug("model usage not recorded for %s", model, exc_info=True)
