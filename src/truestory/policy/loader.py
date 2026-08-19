"""Policy loading, matching and validation.

The routing table is load bearing. A malformed rule does not crash anything, it
silently downgrades a CRITICAL subject to a lite lookup and the failure only
shows up in a report that somebody relies on. So the loader validates
aggressively at import time and CI runs the validator as a first class gate.

Run standalone:

    python -m truestory.policy.loader --validate
    python -m truestory.policy.loader --validate-schemas
    python -m truestory.policy.loader --explain REAL_PERSON_DEPICTED
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from truestory.config import POLICY_DIR, SCHEMA_DIR
from truestory.models.enums import (
    PERSON_ADJACENT,
    ElementType,
    Processor,
    RiskTier,
)


class PolicyError(ValueError):
    """A malformed policy file. Fatal at load time, never tolerated at runtime."""


# =============================================================================
# routing
# =============================================================================


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The complete answer for one subject. Nothing downstream re decides this."""

    rule_id: str
    tier: RiskTier
    provider: str
    processor: Processor | None
    schema_name: str | None
    also: tuple[str, ...] = ()
    post: dict[str, Any] = field(default_factory=dict)
    escalated_by: tuple[str, ...] = ()
    note: str = ""

    @property
    def researched(self) -> bool:
        return self.provider not in {"none", "deterministic_rules"}

    @property
    def estimated_cost_usd(self) -> float:
        if not self.researched or self.processor is None:
            return 0.0
        return self.processor.usd_per_run

    def with_escalation(self, tier: RiskTier, reason: str) -> RoutingDecision:
        """Return a copy at a higher tier, recording why.

        The audit trail matters as much as the tier. When a producer asks why
        a throwaway line went to the most expensive processor, the answer is
        one string away.
        """
        processor = self.processor
        if tier is RiskTier.CRITICAL and processor in (Processor.LITE, Processor.BASE):
            processor = Processor.CORE
        elif tier is RiskTier.HIGH and processor is Processor.LITE:
            processor = Processor.BASE
        return RoutingDecision(
            rule_id=self.rule_id,
            tier=tier,
            provider=self.provider,
            processor=processor,
            schema_name=self.schema_name,
            also=self.also,
            post=self.post,
            escalated_by=(*self.escalated_by, reason),
            note=self.note,
        )


@dataclass(frozen=True, slots=True)
class RoutingRule:
    rule_id: str
    match: dict[str, Any]
    tier: RiskTier
    provider: str
    processor: Processor | None
    schema_name: str | None
    also: tuple[str, ...]
    post: dict[str, Any]
    note: str
    enabled: bool = True

    def matches(self, subject: dict[str, Any]) -> bool:
        """Evaluate this rule's match block against a flattened subject dict.

        Deliberately small. Equality, membership, and two numeric comparators.
        Anything that needs more expressive power than this belongs in Python
        where it can be tested, not in a config language nobody can debug.
        """
        for key, expected in self.match.items():
            actual = subject.get(key)

            if isinstance(expected, dict):
                if "gte" in expected and not (actual is not None and actual >= expected["gte"]):
                    return False
                if "lte" in expected and not (actual is not None and actual <= expected["lte"]):
                    return False
                if "in" in expected and actual not in expected["in"]:
                    return False
                continue

            if isinstance(expected, list):
                if _norm(actual) not in {_norm(e) for e in expected}:
                    return False
                continue

            if _norm(actual) != _norm(expected):
                return False

        return True

    def to_decision(self) -> RoutingDecision:
        return RoutingDecision(
            rule_id=self.rule_id,
            tier=self.tier,
            provider=self.provider,
            processor=self.processor,
            schema_name=self.schema_name,
            also=self.also,
            post=self.post,
            note=self.note,
        )


def _norm(value: Any) -> Any:
    """Compare enums and their string values interchangeably."""
    return str(value) if value is not None else None


class RoutingPolicy:
    """The compiled routing table. First match wins, top to bottom."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version = raw.get("version", 0)
        self.defaults = raw.get("defaults", {})
        self.escalations = raw.get("escalations", {})
        self.budget_policy = raw.get("budget_policy", {})
        self.concurrency = raw.get("concurrency", {})
        self.monitors = raw.get("monitors", {})
        self.rules = self._compile(raw.get("rules", []))

    # ── compilation ──────────────────────────────────────────────────────────
    @staticmethod
    def _compile(entries: list[dict[str, Any]]) -> list[RoutingRule]:
        rules: list[RoutingRule] = []
        seen: set[str] = set()

        for i, e in enumerate(entries):
            rule_id = e.get("id") or f"rule_{i}"
            if rule_id in seen:
                raise PolicyError(f"duplicate routing rule id: {rule_id}")
            seen.add(rule_id)

            if "match" not in e:
                raise PolicyError(f"rule {rule_id} has no match block")

            tier_raw = e.get("tier", "MEDIUM")
            try:
                tier = RiskTier(tier_raw)
            except ValueError as exc:
                raise PolicyError(f"rule {rule_id}: unknown tier {tier_raw!r}") from exc

            proc_raw = e.get("processor")
            processor: Processor | None = None
            if proc_raw is not None:
                try:
                    processor = Processor(proc_raw)
                except ValueError as exc:
                    raise PolicyError(f"rule {rule_id}: unknown processor {proc_raw!r}") from exc

            provider = e.get("provider", "parallel_task")

            # A tier above LOW that neither researches nor names a schema is
            # almost certainly a typo, and it is the exact typo that silently
            # drops a real subject on the floor.
            if (
                provider not in {"none", "deterministic_rules"}
                and not e.get("schema")
                and tier.rank >= RiskTier.MEDIUM.rank
            ):
                raise PolicyError(
                    f"rule {rule_id}: tier {tier} researches but declares no output schema"
                )

            rules.append(
                RoutingRule(
                    rule_id=rule_id,
                    match=dict(e["match"]),
                    tier=tier,
                    provider=provider,
                    processor=processor,
                    schema_name=e.get("schema"),
                    also=tuple(e.get("also", ())),
                    post=dict(e.get("post", {})),
                    note=e.get("note", ""),
                    enabled=bool(e.get("enabled", True)),
                )
            )
        return rules

    # ── matching ─────────────────────────────────────────────────────────────
    def match(self, subject: dict[str, Any]) -> RoutingDecision:
        """Route one subject. Always returns a decision, never None."""
        for rule in self.rules:
            if rule.enabled and rule.matches(subject):
                return rule.to_decision()

        d = self.defaults
        return RoutingDecision(
            rule_id="__default__",
            tier=RiskTier(d.get("tier", "MEDIUM")),
            provider=d.get("provider", "parallel_task"),
            processor=Processor(d.get("processor", "lite")),
            schema_name=d.get("schema", "entity_v1"),
            note="fell through to defaults",
        )

    def apply_project_escalations(
        self,
        decision: RoutingDecision,
        subject: dict[str, Any],
        project: dict[str, Any],
    ) -> RoutingDecision:
        """The truth claim framing rule.

        A production asserting "this is a true story" escalates every person
        adjacent subject one full tier, because courts treated the framing
        itself as evidence bearing on reckless disregard. One method
        implementing a doctrine, and the reason the escalation is auditable
        rather than buried in a prompt.
        """
        if not project.get("truth_claim_framing"):
            return decision

        element_type = subject.get("type") or subject.get("element_type")
        is_claim = subject.get("kind") == "claim"
        is_person_adjacent = is_claim or (
            element_type is not None and _norm(element_type) in {str(t) for t in PERSON_ADJACENT}
        )
        if not is_person_adjacent or decision.tier is RiskTier.NONE:
            return decision

        escalated = decision.tier.escalate(1)
        if escalated is decision.tier:
            return decision
        return decision.with_escalation(escalated, "truth_claim_framing")

    # ── monitors ─────────────────────────────────────────────────────────────
    def monitor_cadence(self, element_type: ElementType | str) -> str:
        by_type = self.monitors.get("by_type", {})
        return by_type.get(str(element_type), self.monitors.get("default_cadence", "monthly"))

    def validate(self) -> list[str]:
        """Return human readable problems. Empty list means healthy."""
        problems: list[str] = []

        if not self.rules:
            problems.append("routing.yaml declares no rules")

        declared = {r.schema_name for r in self.rules if r.schema_name}
        for name in sorted(declared):
            if not (SCHEMA_DIR / f"{name}.json").exists():
                problems.append(f"rule references missing schema file: schemas/{name}.json")

        # Every element type in the taxonomy should be routable, otherwise a
        # real detection has nowhere to go and quietly takes the default.
        routed: set[str] = set()
        for r in self.rules:
            t = r.match.get("type")
            if isinstance(t, list):
                routed.update(str(x) for x in t)
            elif t is not None:
                routed.add(str(t))

        skip = {
            ElementType.TRUTH_CLAIM_FRAMING,  # project level, never routed
            ElementType.PRINT_QUOTE,  # handled through the claim path
        }
        for et in ElementType:
            if et in skip:
                continue
            if str(et) not in routed:
                problems.append(f"element type has no explicit rule, will take defaults: {et}")

        bp = self.budget_policy
        if bp.get("reserve_for_critical_usd", 0) >= bp.get("per_script_ceiling_usd", 0):
            problems.append("budget reserve is not smaller than the per script ceiling")

        return problems


# =============================================================================
# rubric
# =============================================================================


class Rubric:
    """Deterministic post checks, thresholds, and the fixed verdict wording."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.confidence = raw.get("confidence", {})
        self.escalate_always = raw.get("escalate_always", [])
        self.amber_density = raw.get("amber_density", {})
        self.language = raw.get("language", {})
        self.status_language = raw.get("status_language", {})
        self.remedy = raw.get("remedy", {})
        self.coverage = raw.get("coverage", {})

    @property
    def counsel_threshold(self) -> float:
        return float(self.confidence.get("counsel_threshold", 0.75))

    @property
    def fallback_cap(self) -> float:
        return float(self.confidence.get("fallback_cap", 0.60))

    @property
    def critical_clear_requires_human(self) -> bool:
        return bool(self.confidence.get("critical_clear_requires_human", True))

    @property
    def contradicted_requires_primary_source(self) -> bool:
        return bool(self.confidence.get("contradicted_requires_primary_source", True))

    @property
    def contradicted_requires_classified_primary(self) -> bool:
        """Whether a red line needs a recognised record, not a declared one."""
        return bool(self.confidence.get("contradicted_requires_classified_primary", True))

    @property
    def low_trust_cannot_decide(self) -> bool:
        return bool(self.confidence.get("low_trust_cannot_decide", True))

    @property
    def stale_source_days(self) -> int:
        return int(self.confidence.get("stale_source_days", 1825))

    def min_independent_domains(self, tier: RiskTier) -> int:
        """Distinct domains required before a verdict counts as corroborated."""
        table = self.confidence.get("min_independent_domains", {})
        return int(table.get(str(tier), 1))

    def corroboration_cap(self, score: float) -> float:
        """Confidence ceiling implied by how well corroborated the finding is."""
        floor = float(self.confidence.get("corroboration_cap_floor", 0.35))
        span = float(self.confidence.get("corroboration_cap_span", 0.65))
        return min(1.0, floor + span * max(0.0, min(1.0, score)))

    @property
    def max_remedy_iterations(self) -> int:
        return int(self.remedy.get("max_iterations", 3))

    def min_citations(self, tier: RiskTier) -> int:
        return int(self.confidence.get("min_citations", {}).get(str(tier), 1))

    def amber_threshold(self) -> tuple[float, int]:
        """(density threshold, minimum claim count before the ratio is meaningful)."""
        return (
            float(self.amber_density.get("threshold", 0.30)),
            int(self.amber_density.get("min_claims", 4)),
        )

    def verdict_language(self, verdict: str, surface: str = "ui") -> str:
        """The fixed wording. Nobody improvises this in a template.

        UNSUPPORTED is not FALSE, and the sentence that says so is the same
        sentence everywhere it appears.
        """
        entry = self.language.get(str(verdict), {})
        return entry.get(surface, entry.get("label", str(verdict)))


# =============================================================================
# jurisdictions
# =============================================================================


class Jurisdictions:
    """Territory rules. Decides whether a deceased subject is a research question."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.defaults = raw.get("defaults", {})
        self.us_states = raw.get("us_states", {})
        self.territories = raw.get("territories", {})
        self.expansion = raw.get("expansion", {})
        self.instruments = raw.get("instruments", [])

    def post_mortem_term(self, state: str | None) -> int:
        if not state:
            return int(self.defaults.get("post_mortem_publicity_years", 0))
        entry = self.us_states.get(state.upper(), {})
        return int(entry.get("post_mortem_publicity_years", 0))

    def publicity_rights_live(
        self, state: str | None, death_year: int | None, now_year: int
    ) -> bool:
        """Whether a post mortem publicity licence is still required."""
        if death_year is None:
            return False
        term = self.post_mortem_term(state)
        return term > 0 and (now_year - death_year) < term

    def anti_slapp_available(self, state: str | None) -> bool:
        if not state:
            return bool(self.defaults.get("anti_slapp_available", False))
        return bool(self.us_states.get(state.upper(), {}).get("anti_slapp_available", False))

    def expand(self, shoot: list[str], distribution: list[str]) -> list[str]:
        """The jurisdiction set attached to every element in a project."""
        always = list(self.expansion.get("always_include", ["US"]))
        cap = int(self.expansion.get("max_jurisdictions_per_subject", 5))
        ordered: list[str] = []
        for j in [*always, *shoot, *distribution]:
            if j and j not in ordered:
                ordered.append(j)
        return ordered[:cap]

    def instruments_needing_verification(self) -> list[dict[str, Any]]:
        """Anything that must be confirmed against a primary source before it ships."""
        return [i for i in self.instruments if i.get("status") == "verify_before_citing"]


# =============================================================================
# loading
# =============================================================================


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PolicyError(f"missing policy file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise PolicyError(f"policy file is not a mapping: {path}")
    return data


@lru_cache(maxsize=1)
def load_routing() -> RoutingPolicy:
    return RoutingPolicy(_read_yaml(POLICY_DIR / "routing.yaml"))


@lru_cache(maxsize=1)
def load_rubric() -> Rubric:
    return Rubric(_read_yaml(POLICY_DIR / "rubric.yaml"))


@lru_cache(maxsize=1)
def load_jurisdictions() -> Jurisdictions:
    return Jurisdictions(_read_yaml(POLICY_DIR / "jurisdictions.yaml"))


@lru_cache(maxsize=32)
def load_schema(name: str) -> dict[str, Any]:
    """Load one Parallel output schema by bare name, without the extension."""
    path = SCHEMA_DIR / f"{name}.json"
    if not path.exists():
        raise PolicyError(f"missing output schema: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def reload_all() -> None:
    """Drop every cached policy. Used by tests and by the hot reload endpoint."""
    load_routing.cache_clear()
    load_rubric.cache_clear()
    load_jurisdictions.cache_clear()
    load_schema.cache_clear()


# =============================================================================
# cli
# =============================================================================


def _validate_schemas() -> int:
    import jsonschema

    failures = 0
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            print(f"  ok    {path.name}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL  {path.name}: {exc}")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if "--validate-schemas" in args:
        print("validating output schemas")
        failures = _validate_schemas()
        print("all schemas valid" if not failures else f"{failures} schema failures")
        return 1 if failures else 0

    if "--validate" in args:
        print("validating routing policy")
        try:
            policy = load_routing()
        except PolicyError as exc:
            print(f"  FATAL {exc}")
            return 1

        problems = policy.validate()
        for p in problems:
            print(f"  warn  {p}")

        print(f"  rules loaded: {len(policy.rules)}")
        print(f"  version: {policy.version}")
        print("policy valid" if not problems else f"{len(problems)} advisories")
        return 0

    if "--explain" in args:
        idx = args.index("--explain")
        subject_type = args[idx + 1] if idx + 1 < len(args) else "REAL_PERSON_DEPICTED"
        policy = load_routing()
        decision = policy.match({"type": subject_type, "occurrence_count": 1})
        print(f"subject type: {subject_type}")
        print(f"  rule      : {decision.rule_id}")
        print(f"  tier      : {decision.tier}")
        print(f"  provider  : {decision.provider}")
        print(f"  processor : {decision.processor}")
        print(f"  schema    : {decision.schema_name}")
        print(f"  also      : {list(decision.also)}")
        print(f"  est cost  : ${decision.estimated_cost_usd:.4f}")
        if decision.note:
            print(f"  note      : {decision.note}")
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
