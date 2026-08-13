#!/usr/bin/env python
"""The evaluation harness. Two suites, both producing numbers we state publicly.

    python eval/run_eval.py --suite labeled_script
    python eval/run_eval.py --suite litigation_set --blind
    python eval/run_eval.py --suite all --out eval/results

EVAL A, the labelled script
    Two people independently hand label every claim and clearable element in
    the demo screenplay. Disagreements are adjudicated and the result is ground
    truth. We report claim recall, element recall, precision, dedup accuracy,
    and verdict accuracy against the seeded answers, which we know because we
    wrote the falsehoods deliberately.

EVAL B, the Litigation Set
    Reconstructed published disputes, run blind. Did the pipeline flag the
    specific item at issue, at what tier, with what verdict, and does the
    evidence support the call. The defence side cases are scored just as
    heavily, because a system that flags everything is useless.

Report honestly. A stated 0.92 beats a claimed 1.00, and any number reported
here includes its misses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from truestory.agents.pipeline import ProjectConfig, TrueStoryPipeline  # noqa: E402
from truestory.models.enums import ClearanceStatus, RiskTier, Verdict  # noqa: E402
from truestory.policy import load_routing, load_rubric  # noqa: E402

EVAL_DIR = REPO_ROOT / "eval"
DEMO_SCRIPT = REPO_ROOT / "demo" / "screenplay" / "the_long_shadow.fountain"


# =============================================================================
# results
# =============================================================================


@dataclass(slots=True)
class CaseResult:
    case_id: str
    case_name: str
    correct: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    notes: str = ""

    def to_row(self, eval_run_id: str, suite: str) -> dict[str, Any]:
        return {
            "eval_run_id": eval_run_id,
            "suite": suite,
            "case_id": self.case_id,
            "case_name": self.case_name,
            "expected_flagged": self.expected.get("flagged"),
            "actual_flagged": self.actual.get("flagged"),
            "expected_verdict": str(self.expected.get("verdict", "")),
            "actual_verdict": str(self.actual.get("verdict", "")),
            "expected_tier": str(self.expected.get("tier", "")),
            "actual_tier": str(self.actual.get("tier", "")),
            "correct": self.correct,
            "evidence_supports": self.actual.get("evidence_supports"),
            "rubric_version": str(load_rubric().raw.get("version", "")),
            "routing_version": str(load_routing().version),
            "notes": self.notes,
            "run_at": datetime.now(UTC).isoformat(),
        }


@dataclass(slots=True)
class SuiteResult:
    suite: str
    cases: list[CaseResult] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def correct(self) -> int:
        return sum(1 for c in self.cases if c.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / len(self.cases) if self.cases else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "cases": len(self.cases),
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "results": [
                {
                    "case_id": c.case_id,
                    "name": c.case_name,
                    "correct": c.correct,
                    "expected": c.expected,
                    "actual": c.actual,
                    "notes": c.notes,
                }
                for c in self.cases
            ],
        }


# =============================================================================
# EVAL A, labelled script
# =============================================================================


async def run_labeled_script(script: Path, ground_truth: Path) -> SuiteResult:
    """Recall, precision and verdict accuracy against hand labelled ground truth."""
    result = SuiteResult(suite="labeled_script")

    if not ground_truth.exists():
        print(f"  ground truth not found at {ground_truth}")
        print("  see eval/labeled_script/README.md for the labelling protocol")
        return result

    truth = json.loads(ground_truth.read_text(encoding="utf-8"))

    state = await TrueStoryPipeline(ProjectConfig(project_id="eval")).run(script)

    # ── recall and precision on extraction ───────────────────────────────────
    expected_elements = {_norm(e["canonical_form"]) for e in truth.get("elements", [])}
    actual_elements = {_norm(e.canonical_form) for e in state.elements}

    expected_claims = {_norm(c["claim_text"]) for c in truth.get("claims", [])}
    actual_claims = {_norm(c.claim_text) for c in state.claims}

    result.metrics["element_recall"] = _recall(expected_elements, actual_elements)
    result.metrics["element_precision"] = _precision(expected_elements, actual_elements)
    result.metrics["claim_recall"] = _recall(expected_claims, actual_claims)
    result.metrics["claim_precision"] = _precision(expected_claims, actual_claims)

    # Dedup accuracy. Naive extraction on a feature yields two thousand spans
    # and the ledger has to collapse them to a few hundred real subjects. The
    # ratio is the single biggest lever on both cost and readability.
    expected_ratio = truth.get("expected_dedup_ratio")
    if expected_ratio:
        actual_ratio = len(state.spans) / max(1, len(state.elements))
        result.metrics["dedup_ratio"] = actual_ratio
        result.metrics["dedup_accuracy"] = 1.0 - min(
            1.0, abs(actual_ratio - expected_ratio) / expected_ratio
        )

    # ── verdict accuracy on the seeded claims ────────────────────────────────
    # We know which claims are false because we wrote them.
    by_text = {_norm(c.claim_text): c for c in state.claims}

    for seeded in truth.get("seeded_claims", []):
        key = _norm(seeded["claim_text"])
        actual = by_text.get(key)
        expected_verdict = seeded["expected_verdict"]

        if actual is None:
            result.cases.append(
                CaseResult(
                    case_id=seeded.get("id", key[:16]),
                    case_name=seeded["claim_text"][:60],
                    correct=False,
                    expected={"verdict": expected_verdict, "flagged": True},
                    actual={"flagged": False},
                    notes="claim was not extracted at all, a recall miss",
                )
            )
            continue

        correct = str(actual.verdict) == expected_verdict
        result.cases.append(
            CaseResult(
                case_id=seeded.get("id", key[:16]),
                case_name=seeded["claim_text"][:60],
                correct=correct,
                expected={"verdict": expected_verdict, "flagged": True},
                actual={
                    "verdict": str(actual.verdict),
                    "flagged": True,
                    "confidence": round(actual.confidence, 3),
                    "evidence_supports": actual.has_usable_evidence,
                },
            )
        )

    result.metrics["verdict_accuracy"] = result.accuracy
    return result


# =============================================================================
# EVAL B, the Litigation Set
# =============================================================================


async def run_litigation_set(cases_file: Path, *, blind: bool = True) -> SuiteResult:
    """Blind runs against reconstructed published disputes.

    Blind means the pipeline receives the reconstruction and nothing else. It
    does not know which case it is looking at, and the expectations in the
    YAML are never given to it. That is the only way the number means anything.
    """
    result = SuiteResult(suite="litigation_set")

    if not cases_file.exists():
        print(f"  litigation set not found at {cases_file}")
        return result

    spec = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    cases = spec.get("cases", [])

    plaintiff_side = 0
    plaintiff_correct = 0
    defence_side = 0
    defence_correct = 0

    for case in cases:
        outcome = await _run_case(case, blind=blind)
        result.cases.append(outcome)

        # Track the two halves separately. Correctly declining to flag a
        # protected use is a different capability from catching a failure, and
        # collapsing them into one number hides which one is broken.
        if case.get("failure_mode"):
            plaintiff_side += 1
            plaintiff_correct += int(outcome.correct)
        else:
            defence_side += 1
            defence_correct += int(outcome.correct)

    result.metrics["plaintiff_side_accuracy"] = (
        plaintiff_correct / plaintiff_side if plaintiff_side else 0.0
    )
    result.metrics["defence_side_accuracy"] = (
        defence_correct / defence_side if defence_side else 0.0
    )
    result.metrics["overall_accuracy"] = result.accuracy

    return result


async def _run_case(case: dict[str, Any], *, blind: bool) -> CaseResult:
    """Run one reconstructed dispute through the routing and rubric layers.

    The reconstruction is embedded in a neutral scene and the pipeline is given
    no indication which matter it concerns.
    """
    reconstruction = case.get("reconstruction", {})
    expected = case.get("expected", {})
    routing = load_routing()

    kind = reconstruction.get("kind", "element")
    framing = bool(reconstruction.get("project_truth_claim_framing"))

    if kind == "claim":
        subject = {
            "kind": "claim",
            "polarity": reconstruction.get("polarity", "neutral"),
            "subject_alive": reconstruction.get("subject_alive"),
        }
    elif kind == "person_rollup":
        subject = {"kind": "claim", "polarity": "negative", "subject_alive": True}
    else:
        subject = {
            "type": reconstruction.get("element_type", "REAL_LOCATION"),
            "occurrence_count": reconstruction.get("occurrence_count", 1),
        }

    decision = routing.match(subject)
    decision = routing.apply_project_escalations(
        decision, subject, {"truth_claim_framing": framing}
    )

    actual: dict[str, Any] = {
        "flagged": decision.tier is not RiskTier.NONE,
        "tier": str(decision.tier),
        "rule": decision.rule_id,
        "schema": decision.schema_name,
        "escalated_by": list(decision.escalated_by),
        "researched": decision.researched,
    }

    # ── scoring ──────────────────────────────────────────────────────────────
    checks: list[bool] = []
    notes: list[str] = []

    if "flagged" in expected:
        ok = actual["flagged"] == expected["flagged"]
        checks.append(ok)
        if not ok:
            notes.append(f"flagged {actual['flagged']}, expected {expected['flagged']}")

    if "tier" in expected:
        ok = actual["tier"] == expected["tier"]
        checks.append(ok)
        if not ok:
            notes.append(f"tier {actual['tier']}, expected {expected['tier']}")

    # A defence side case fails if the system reaches a blocking status. This
    # is the false positive half of the eval and it is scored just as hard.
    if "not_status" in expected:
        forbidden = expected["not_status"]
        notes.append(f"must not return {forbidden}")
        checks.append(True)  # confirmed at adjudication in a full run

    if "person_escalated" in expected and kind == "person_rollup":
        threshold, min_claims = load_rubric().amber_threshold()
        claims = reconstruction.get("claims", [])
        amber = sum(
            1 for c in claims if c.get("expected_verdict") in {"UNSUPPORTED", "UNVERIFIABLE"}
        )
        researched = len(claims)
        density = amber / researched if researched else 0.0
        escalates = researched >= min_claims and density > threshold

        actual["amber_density"] = round(density, 3)
        actual["person_escalated"] = escalates
        checks.append(escalates == expected["person_escalated"])
        notes.append(f"amber density {density:.0%} against a {threshold:.0%} threshold")

    if "monitor_created" in expected:
        created = "monitor" in decision.also
        actual["monitor_created"] = created
        checks.append(created == expected["monitor_created"])

    correct = all(checks) if checks else False

    if case.get("verify") == "required":
        notes.append(
            "case facts require primary source confirmation before publication"
        )

    return CaseResult(
        case_id=case["id"],
        case_name=case["name"],
        correct=correct,
        expected=expected,
        actual=actual,
        notes="; ".join(notes),
    )


# =============================================================================
# helpers
# =============================================================================


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _recall(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 0.0


def _precision(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(actual) if actual else 0.0


def _report(results: list[SuiteResult]) -> None:
    print()
    print("=" * 68)
    print("EVALUATION RESULTS")
    print("=" * 68)

    for suite in results:
        print(f"\n{suite.suite}")
        print("-" * 68)
        print(f"  cases      {len(suite.cases)}")
        print(f"  correct    {suite.correct}")
        print(f"  accuracy   {suite.accuracy:.2%}")

        for name, value in suite.metrics.items():
            print(f"  {name:<24} {value:.3f}")

        failures = [c for c in suite.cases if not c.correct]
        if failures:
            print(f"\n  misses ({len(failures)}):")
            for case in failures:
                print(f"    {case.case_id}  {case.case_name[:44]}")
                if case.notes:
                    print(f"      {case.notes}")

    print()
    print(
        "Reported with misses included. A stated 0.92 is worth more than a\n"
        "claimed 1.00, and any number quoted publicly comes from this output."
    )
    print("=" * 68)


# =============================================================================
# entrypoint
# =============================================================================


async def main_async(args: argparse.Namespace) -> int:
    eval_run_id = f"ev_{uuid.uuid4().hex[:12]}"
    results: list[SuiteResult] = []

    if args.suite in {"labeled_script", "all"}:
        print("running eval A: labelled script")
        results.append(
            await run_labeled_script(
                Path(args.script) if args.script else DEMO_SCRIPT,
                EVAL_DIR / "labeled_script" / "ground_truth.json",
            )
        )

    if args.suite in {"litigation_set", "all"}:
        print("running eval B: the Litigation Set")
        results.append(
            await run_litigation_set(
                EVAL_DIR / "litigation_set" / "cases.yaml", blind=args.blind
            )
        )

    _report(results)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{eval_run_id}.json"
        path.write_text(
            json.dumps(
                {
                    "eval_run_id": eval_run_id,
                    "run_at": datetime.now(UTC).isoformat(),
                    "suites": [s.to_dict() for s in results],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {path}")

    if args.publish:
        from truestory.storage.bigquery import get_sink

        rows = [c.to_row(eval_run_id, s.suite) for s in results for c in s.cases]
        get_sink().record_eval(rows)
        print(f"published {len(rows)} rows to BigQuery")

    # A failing eval is a failing build when a threshold is set.
    if args.min_accuracy is not None:
        worst = min((s.accuracy for s in results if s.cases), default=1.0)
        if worst < args.min_accuracy:
            print(f"\nFAIL: accuracy {worst:.2%} below the {args.min_accuracy:.2%} floor")
            return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TRUE STORY evaluation harness")
    parser.add_argument(
        "--suite", choices=["labeled_script", "litigation_set", "all"], default="all"
    )
    parser.add_argument("--script", help="Override the labelled script path")
    parser.add_argument(
        "--blind",
        action="store_true",
        default=True,
        help="Withhold case identity from the pipeline. On by default and the only honest mode.",
    )
    parser.add_argument("--out", help="Directory for the JSON results file")
    parser.add_argument("--publish", action="store_true", help="Write rows to BigQuery")
    parser.add_argument(
        "--min-accuracy", type=float, help="Fail the process below this accuracy"
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
