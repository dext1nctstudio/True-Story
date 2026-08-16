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

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0

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

        self.ledger = Ledger()
        self._lock = threading.Lock()
        self.warnings: list[str] = []

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
    ) -> None:
        with self._lock:
            self.ledger.reserved_cents = max(0.0, self.ledger.reserved_cents - reserved)
            self.ledger.spent_cents += cost_cents
            self.ledger.calls += 1
            if cached:
                self.ledger.cache_hits += 1
            self.ledger.by_tier[str(tier)] = self.ledger.by_tier.get(str(tier), 0.0) + cost_cents
            self.ledger.by_provider[provider] = (
                self.ledger.by_provider.get(provider, 0.0) + cost_cents
            )
            if self.utilisation >= self.warn_at and len(self.warnings) < 8:
                self._warn(
                    f"Run reached {self.utilisation:.0%} of its budget ceiling "
                    f"(${self.ceiling_cents / 100:.2f})."
                )

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
        for processor, tier in plan:
            by_tier[str(tier)] = by_tier.get(str(tier), 0.0) + processor.usd_per_run * 100
        return {
            "subjects": len(plan),
            "projected_cents": round(total, 4),
            "projected_usd": round(total / 100, 4),
            "ceiling_usd": round(self.ceiling_cents / 100, 2),
            "within_budget": total <= self.ceiling_cents,
            "by_tier": {k: round(v, 4) for k, v in by_tier.items()},
        }

    def coverage_warnings(self) -> list[str]:
        """Fed straight onto the front page of the report."""
        return list(self.warnings)

    def snapshot(self) -> dict[str, Any]:
        """The live cost meter payload, emitted over SSE as the swarm runs."""
        return {
            **self.ledger.to_dict(),
            "ceiling_usd": round(self.ceiling_cents / 100, 2),
            "remaining_usd": round(self.remaining_cents / 100, 4),
            "utilisation": round(self.utilisation, 4),
            "warnings": self.warnings,
        }
