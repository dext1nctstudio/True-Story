"""BudgetGovernor.

Principle P4, cost is a governed runtime resource rather than a hope. This is a
real component with real behaviour, not a counter that gets printed at the end.

Two rules define it:

  1. Degrade before failing. When the ceiling approaches, depth walks down
     core to base to lite. A shallower answer with citations beats no answer.
  2. CRITICAL work is never degraded. A reserve is held back that ordinary
     subjects cannot draw down, so a script full of cheap background elements
     can never starve the one line that gets the production sued.

When the governor degrades anything, the run carries a coverage warning onto
the front page of the report. Principle P5, degrade honestly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from truestory.models.enums import Processor, RiskTier
from truestory.policy import load_routing


class BudgetExhausted(RuntimeError):
    """Even the reserve is gone. The run stops rather than producing junk."""


@dataclass(slots=True)
class Ledger:
    """Running totals, reported live on the cost meter."""

    spent_cents: float = 0.0
    reserved_cents: float = 0.0
    calls: int = 0
    cache_hits: int = 0
    degradations: int = 0
    refusals: int = 0
    by_tier: dict[str, float] = field(default_factory=dict)
    by_provider: dict[str, float] = field(default_factory=dict)

    # Model spend is a separate bill from research spend: Parallel is priced
    # per task run, Gemini per token. Kept apart so the research ceiling still
    # governs research, and reported together so the run's true cost is
    # visible rather than only its research half.
    model_cents: float = 0.0
    model_calls: int = 0
    model_prompt_tokens: int = 0
    model_output_tokens: int = 0
    model_cached_tokens: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    # What the cache hits would have cost at list price. A hit records zero
    # spend, which is correct for the meter and useless for the economics: the
    # draft over draft argument is exactly this number, and it was being
    # discarded at the moment it was known.
    cache_saved_cents: float = 0.0

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0

    @property
    def total_cents(self) -> float:
        """Research plus model. What the run actually costs."""
        return self.spent_cents + self.model_cents

    def to_dict(self) -> dict[str, Any]:
        return {
            "spent_cents": round(self.spent_cents, 4),
            "spent_usd": round(self.spent_cents / 100, 4),
            "reserved_cents": round(self.reserved_cents, 4),
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "degradations": self.degradations,
            "refusals": self.refusals,
            "by_tier": {k: round(v, 4) for k, v in self.by_tier.items()},
            "by_provider": {k: round(v, 4) for k, v in self.by_provider.items()},
            "model_cents": round(self.model_cents, 4),
            "model_usd": round(self.model_cents / 100, 4),
            "model_calls": self.model_calls,
            "model_prompt_tokens": self.model_prompt_tokens,
            "model_output_tokens": self.model_output_tokens,
            "model_cached_tokens": self.model_cached_tokens,
            "by_model": {k: round(v, 4) for k, v in self.by_model.items()},
            "total_cents": round(self.total_cents, 4),
            "total_usd": round(self.total_cents / 100, 4),
            "cache_saved_cents": round(self.cache_saved_cents, 4),
            "cache_saved_usd": round(self.cache_saved_cents / 100, 4),
        }


class BudgetGovernor:
    """Per run spend control. Thread safe because the swarm fans out."""

    def __init__(
        self,
        ceiling_usd: float | None = None,
        reserve_critical_usd: float | None = None,
        *,
        degrade_on_exceed: bool | None = None,
    ) -> None:
        policy = load_routing().budget_policy
        self.ceiling_cents = float(
            (ceiling_usd if ceiling_usd is not None else policy.get("per_script_ceiling_usd", 5.0))
            * 100
        )
        self.reserve_cents = float(
            (
                reserve_critical_usd
                if reserve_critical_usd is not None
                else policy.get("reserve_for_critical_usd", 1.5)
            )
            * 100
        )
        self.degrade_on_exceed = (
            degrade_on_exceed
            if degrade_on_exceed is not None
            else policy.get("on_exceed") == "degrade_tier"
        )
        self.warn_at = float(policy.get("warn_at_fraction", 0.80))
        self.never_degrade = {RiskTier(t) for t in policy.get("never_degrade_tiers", ["CRITICAL"])}

        # What a manual clearance report costs and how long it takes, so the
        # comparison the product is built on is a policy value an attorney can
        # argue with rather than a number hard coded in a React component.
        self.manual_baseline = dict(
            policy.get(
                "manual_baseline",
                {
                    "report_usd_low": 1000,
                    "report_usd_high": 3000,
                    "turnaround_days_low": 3,
                    "turnaround_days_high": 10,
                    "source": "vendor published rates, see Agentic Cin.md §5.3",
                },
            )
        )

        self.ledger = Ledger()
        self._lock = threading.Lock()
        self.warnings: list[str] = []
        #: The pre flight estimate, kept so the report and the UI can put the
        #: projection beside the actual instead of showing one or the other.
        self.projection: dict[str, Any] = {}

    # ── availability ─────────────────────────────────────────────────────────
    @property
    def remaining_cents(self) -> float:
        return max(0.0, self.ceiling_cents - self.ledger.spent_cents)

    @property
    def general_remaining_cents(self) -> float:
        """What a non CRITICAL subject may spend. The reserve is invisible to it."""
        return max(0.0, self.remaining_cents - self.reserve_cents)

    @property
    def utilisation(self) -> float:
        return self.ledger.spent_cents / self.ceiling_cents if self.ceiling_cents else 0.0

    def available_for(self, tier: RiskTier) -> float:
        return self.remaining_cents if tier in self.never_degrade else self.general_remaining_cents

    def can_afford(self, cost_cents: float, tier: RiskTier) -> bool:
        with self._lock:
            return cost_cents <= self.available_for(tier)

    # ── the interesting part ─────────────────────────────────────────────────
    def resolve(self, processor: Processor, tier: RiskTier) -> Processor:
        """Return the processor this subject may actually use.

        CRITICAL never degrades, by policy and by reserve. Everything else
        walks down the depth ladder until it fits, and if nothing fits the
        caller gets BudgetExhausted rather than a silent skip.
        """
        with self._lock:
            if tier in self.never_degrade:
                if processor.usd_per_run * 100 > self.remaining_cents:
                    raise BudgetExhausted(
                        f"CRITICAL subject cannot be funded: needs "
                        f"{processor.usd_per_run * 100:.2f}c, reserve holds "
                        f"{self.remaining_cents:.2f}c"
                    )
                return processor

            if not self.degrade_on_exceed:
                if processor.usd_per_run * 100 > self.general_remaining_cents:
                    raise BudgetExhausted("budget exhausted and degradation is disabled")
                return processor

            current = processor
            while current.usd_per_run * 100 > self.general_remaining_cents:
                cheaper = current.cheaper()
                if cheaper is None:
                    self.ledger.refusals += 1
                    raise BudgetExhausted(
                        f"budget exhausted: {self.general_remaining_cents:.2f}c left "
                        "and no cheaper processor exists"
                    )
                current = cheaper

            if current is not processor:
                self.ledger.degradations += 1
                self._warn(
                    f"Depth reduced from {processor} to {current} on at least one "
                    "subject because the run approached its budget ceiling."
                )
            return current

    def reserve(self, cost_cents: float, tier: RiskTier) -> None:
        """Hold spend before dispatching, so concurrent workers cannot overshoot."""
        with self._lock:
            if cost_cents > self.available_for(tier):
                raise BudgetExhausted(
                    f"cannot reserve {cost_cents:.2f}c for tier {tier}: "
                    f"{self.available_for(tier):.2f}c available"
                )
            self.ledger.reserved_cents += cost_cents

    def record(
        self,
        cost_cents: float,
        tier: RiskTier,
        provider: str,
        *,
        cached: bool = False,
        reserved: float = 0.0,
        list_price_cents: float | None = None,
    ) -> None:
        """Record one completed lookup.

        `list_price_cents` is what the call would have cost had it gone to the
        provider. On a cache hit that is the whole saving, and it is the number
        the draft over draft economics rest on.
        """
        with self._lock:
            self.ledger.reserved_cents = max(0.0, self.ledger.reserved_cents - reserved)
            self.ledger.spent_cents += cost_cents
            self.ledger.calls += 1
            if cached:
                self.ledger.cache_hits += 1
                self.ledger.cache_saved_cents += max(0.0, (list_price_cents or 0.0) - cost_cents)
            self.ledger.by_tier[str(tier)] = self.ledger.by_tier.get(str(tier), 0.0) + cost_cents
            self.ledger.by_provider[provider] = (
                self.ledger.by_provider.get(provider, 0.0) + cost_cents
            )
            if self.utilisation >= self.warn_at and len(self.warnings) < 8:
                self._warn(
                    f"Run reached {self.utilisation:.0%} of its budget ceiling "
                    f"(${self.ceiling_cents / 100:.2f})."
                )

    def record_model(
        self, model: str, prompt_tokens: int, output_tokens: int, cached_tokens: int = 0
    ) -> float:
        """Meter one language model call and return what it cost, in cents.

        Deliberately does not draw on the research ceiling. That ceiling exists
        to bound how much web research a script may buy, and charging model
        tokens against it would silently reduce the research a run can afford.
        Model spend is reported alongside rather than inside it.
        """
        from truestory.providers.model_cost import cost_cents

        cents = cost_cents(model, prompt_tokens, output_tokens, cached_tokens)
        with self._lock:
            self.ledger.model_cents += cents
            self.ledger.model_calls += 1
            self.ledger.model_prompt_tokens += prompt_tokens
            self.ledger.model_output_tokens += output_tokens
            self.ledger.model_cached_tokens += cached_tokens
            self.ledger.by_model[model] = self.ledger.by_model.get(model, 0.0) + cents
        return cents

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    # ── projection ───────────────────────────────────────────────────────────
    def project(self, plan: list[tuple[Processor, RiskTier]]) -> dict[str, Any]:
        """Pre flight estimate, shown to the user before the swarm dispatches.

        The demo beat is this number appearing on screen before anything is
        spent: two hundred subjects, projected two dollars and seventy one
        cents, against a thousand dollar manual report.
        """
        total = sum(p.usd_per_run * 100 for p, _ in plan)
        by_tier: dict[str, float] = {}
        by_processor: dict[str, dict[str, float]] = {}
        for processor, tier in plan:
            cents = processor.usd_per_run * 100
            by_tier[str(tier)] = by_tier.get(str(tier), 0.0) + cents
            row = by_processor.setdefault(str(processor), {"subjects": 0, "cents": 0.0})
            row["subjects"] += 1
            row["cents"] += cents

        self.projection = {
            "subjects": len(plan),
            "projected_cents": round(total, 4),
            "projected_usd": round(total / 100, 4),
            "ceiling_usd": round(self.ceiling_cents / 100, 2),
            "within_budget": total <= self.ceiling_cents,
            "by_tier": {k: round(v, 4) for k, v in by_tier.items()},
            # Which depth the money is going to, which is the question a
            # producer actually asks when the number surprises them.
            "by_processor": {
                k: {"subjects": int(v["subjects"]), "usd": round(v["cents"] / 100, 4)}
                for k, v in sorted(by_processor.items())
            },
        }
        return self.projection

    # ── unit economics ───────────────────────────────────────────────────────
    def economics(
        self,
        *,
        subjects: int = 0,
        claims: int = 0,
        pages: float = 0.0,
    ) -> dict[str, Any]:
        """Cost per unit of work, and the comparison that justifies the product.

        Separate from `snapshot` because it needs facts the governor does not
        hold: how many pages the script ran to and how many claims came out of
        it. The API assembles those and calls this.
        """
        total_usd = self.ledger.total_cents / 100
        low = float(self.manual_baseline.get("report_usd_low", 1000))
        high = float(self.manual_baseline.get("report_usd_high", 3000))

        def per(n: float) -> float | None:
            return round(total_usd / n, 4) if n else None

        return {
            "total_usd": round(total_usd, 4),
            "research_usd": round(self.ledger.spent_cents / 100, 4),
            "model_usd": round(self.ledger.model_cents / 100, 4),
            "cache_saved_usd": round(self.ledger.cache_saved_cents / 100, 4),
            "per_subject_usd": per(subjects),
            "per_claim_usd": per(claims),
            "per_page_usd": per(pages),
            "manual_baseline": {
                **self.manual_baseline,
                "midpoint_usd": round((low + high) / 2, 2),
            },
            # Deliberately a multiple against the low end of the manual range.
            # The flattering number is the high end and it is the one to avoid.
            "savings_vs_manual_usd": round(low - total_usd, 2),
            "cost_ratio": round(total_usd / low, 6) if low else None,
            "times_cheaper": round(low / total_usd, 1) if total_usd > 0 else None,
        }

    def coverage_warnings(self) -> list[str]:
        """Fed straight onto the front page of the report."""
        return list(self.warnings)

    def snapshot(self) -> dict[str, Any]:
        """The live cost meter payload, emitted over SSE as the swarm runs."""
        return {
            **self.ledger.to_dict(),
            "ceiling_usd": round(self.ceiling_cents / 100, 2),
            "reserve_usd": round(self.reserve_cents / 100, 2),
            "remaining_usd": round(self.remaining_cents / 100, 4),
            "utilisation": round(self.utilisation, 4),
            "warnings": self.warnings,
            # The projection travels with the meter so the UI can show what the
            # run was expected to cost beside what it is costing. A meter with
            # no expectation attached is a number nobody can read.
            "projection": self.projection,
        }
