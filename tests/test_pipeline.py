"""End to end pipeline behaviour, plus the budget governor and the ledger.

All of it in mock mode, so the suite is fast, free, and needs no credentials.
"""

from __future__ import annotations

import pytest

from truestory.agents.pipeline import ProjectConfig, TrueStoryPipeline
from truestory.models.enums import ElementType, Processor, RiskTier, RunStatus

# =============================================================================
# end to end
# =============================================================================


async def test_pipeline_completes_and_produces_every_artifact(tiny_script):
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)

    assert state.status is RunStatus.COMPLETE
    assert state.error is None
    assert state.summary is not None

    report = state.artifacts["report"]
    for artifact in (
        "overlay",
        "claim_register",
        "eo_report",
        "clearance_log_csv",
        "monitor_manifest",
        "coverage_statement",
    ):
        assert artifact in report, f"missing artifact: {artifact}"


async def test_truth_claim_framing_is_detected(tiny_script):
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    assert state.document.truth_claim_framing is True
    assert state.document.truth_claim_evidence


async def test_absence_of_framing_is_detected(no_framing_script):
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(no_framing_script)
    assert state.document.truth_claim_framing is False


async def test_inspired_by_is_not_a_truth_claim(tmp_path):
    """Inspiration is a weaker assertion and courts have treated the
    difference as meaningful. It must not fire the escalation."""
    path = tmp_path / "inspired.fountain"
    path.write_text(
        "TITLE CARD: INSPIRED BY A TRUE STORY.\n\nINT. ROOM - DAY\n\nA man waits.\n",
        encoding="utf-8",
    )
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(path)
    assert state.document.truth_claim_framing is False


async def test_opinions_are_never_researched(tiny_script):
    """Defamation law protects opinion, so it must cost nothing."""
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)

    opinions = [c for c in state.claims if c.is_opinion]
    for claim in opinions:
        assert not claim.evidence, "an opinion consumed research budget"
        assert claim.color() == "grey"


async def test_every_adjudicated_claim_has_evidence_or_is_opinion(tiny_script):
    """The P2 invariant, verified across a whole real run."""
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)

    for claim in state.claims:
        if claim.verdict is None or claim.is_opinion:
            continue
        assert claim.has_usable_evidence or claim.needs_counsel, (
            f"claim {claim.claim_id} carries verdict {claim.verdict} "
            "with neither usable evidence nor a counsel escalation"
        )


async def test_run_stays_within_budget(tiny_script):
    pipeline = TrueStoryPipeline(ProjectConfig(project_id="test", budget_usd=0.50))
    state = await pipeline.run(tiny_script)
    assert state.summary.cost_usd <= 0.50


async def test_progress_events_are_emitted_in_order(tiny_script):
    seen: list[str] = []

    async def capture(payload):
        seen.append(str(payload.get("event")))

    await TrueStoryPipeline(ProjectConfig(project_id="test"), on_progress=capture).run(tiny_script)

    for expected in ("ingest_complete", "claims_extracted", "ledger_built", "plan_ready"):
        assert expected in seen, f"missing progress event: {expected}"

    assert seen.index("ingest_complete") < seen.index("ledger_built")
    assert seen[-1] == "run_complete"


async def test_pipeline_is_deterministic_in_mock_mode(tiny_script):
    """Two runs over identical input must agree, or the demo flickers and the
    eval numbers are noise."""
    a = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    b = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)

    assert a.summary.total_claims == b.summary.total_claims
    assert a.summary.total_elements == b.summary.total_elements
    assert a.summary.green == b.summary.green
    assert a.summary.red == b.summary.red


async def test_content_addressing_survives_a_redraft(tiny_script, tmp_path):
    """A revision must reuse identifiers for everything that did not change.

    This is what makes draft over draft caching free, and it is the mechanism
    behind the roughly ninety five percent reduction on a typical redraft.
    """
    original = tiny_script.read_text(encoding="utf-8")
    revised = tmp_path / "revised.fountain"
    revised.write_text(original + "\nHe leaves the room.\n", encoding="utf-8")

    first = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    second = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(revised)

    shared = {e.element_id for e in first.elements} & {e.element_id for e in second.elements}
    assert shared, "no element identifiers survived the redraft"


# =============================================================================
# the ledger
# =============================================================================


async def test_ledger_collapses_spans_into_fewer_elements(demo_script):
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(demo_script)
    assert len(state.elements) < len(state.spans)


async def test_coreference_merges_short_and_full_names(demo_script):
    """ "Margaret" and "Margaret Holloway" are one research subject, not two."""
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(demo_script)

    forms = {e.canonical_form for e in state.elements}
    assert "Margaret Holloway" in forms
    assert "Margaret" not in forms, "the short form was not merged into the full name"


async def test_no_duplicate_canonical_subjects(demo_script):
    """Retyping during enrichment must not leave the same subject twice."""
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(demo_script)

    keys = [(e.element_type, e.canonical_form) for e in state.elements]
    assert len(keys) == len(set(keys)), "the ledger contains duplicate subjects"


def test_normalisation_strips_honorifics_and_cue_decorations():
    from truestory.agents.ledger import normalise

    assert normalise("DR. MIGUEL REYES") == normalise("Miguel Reyes")
    assert normalise("ARTHUR (CONT'D)") == normalise("Arthur")
    assert normalise("Detective Sarah Chen") == normalise("SARAH CHEN")


def test_business_suffixes_are_stripped_for_comparison():
    from truestory.agents.ledger import canonicalise

    assert canonicalise("Kestrel Holdings, Inc.", ElementType.BUSINESS_NAME) == "Kestrel Holdings"


# =============================================================================
# the budget governor
# =============================================================================


def test_budget_degrades_depth_before_failing():
    """Principle P4. A shallower cited answer beats no answer."""
    from truestory.providers.budget import BudgetGovernor

    governor = BudgetGovernor(ceiling_usd=0.10, reserve_critical_usd=0.05)
    governor.record(4.0, RiskTier.HIGH, "parallel_task")  # 4 cents spent of 10

    resolved = governor.resolve(Processor.CORE, RiskTier.HIGH)
    assert resolved.usd_per_run < Processor.CORE.usd_per_run
    assert governor.ledger.degradations == 1
    assert governor.coverage_warnings(), "a degradation must warn the report"


def test_critical_work_is_never_degraded():
    """A script full of cheap background elements must not starve the one line
    that gets the production sued."""
    from truestory.providers.budget import BudgetGovernor

    governor = BudgetGovernor(ceiling_usd=1.00, reserve_critical_usd=0.50)
    governor.record(60.0, RiskTier.MEDIUM, "parallel_task")  # general pool gone

    assert governor.general_remaining_cents == 0.0
    assert governor.resolve(Processor.CORE, RiskTier.CRITICAL) is Processor.CORE


def test_budget_exhaustion_raises_rather_than_silently_skipping():
    from truestory.providers.budget import BudgetExhausted, BudgetGovernor

    governor = BudgetGovernor(ceiling_usd=0.01, reserve_critical_usd=0.0)
    governor.record(1.0, RiskTier.CRITICAL, "parallel_task")

    with pytest.raises(BudgetExhausted):
        governor.resolve(Processor.CORE, RiskTier.CRITICAL)


def test_projection_runs_before_any_spend():
    """The number that lands on screen before the swarm dispatches."""
    from truestory.providers.budget import BudgetGovernor

    governor = BudgetGovernor(ceiling_usd=5.00)
    plan = [(Processor.LITE, RiskTier.MEDIUM)] * 120
    plan += [(Processor.BASE, RiskTier.HIGH)] * 55
    plan += [(Processor.CORE, RiskTier.CRITICAL)] * 25

    projection = governor.project(plan)
    assert projection["subjects"] == 200
    assert projection["within_budget"]
    assert 1.0 < projection["projected_usd"] < 3.0


# =============================================================================
# report artifacts
# =============================================================================


async def test_clearance_log_is_valid_csv(tiny_script):
    import csv
    import io

    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    text = state.artifacts["report"]["clearance_log_csv"]

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "element_id"
    assert len(rows) == len(state.elements) + 1


async def test_report_states_its_own_coverage_quality(tiny_script):
    """Principle P5. An underwriter prefers a caveated report to a confident
    wrong one."""
    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    coverage = state.artifacts["report"]["coverage_statement"]

    assert coverage["coverage_quality"] in {"complete", "qualified", "substantially qualified"}
    assert "not legal advice" in coverage["disclaimer"].lower()


async def test_pdf_renders(tiny_script):
    from truestory.reports.eo_report import render_pdf

    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    pdf = render_pdf(state.artifacts["report"]["eo_report"])

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


async def test_underwriter_copy_is_watermarked(tiny_script):
    from truestory.reports.eo_report import render_pdf

    state = await TrueStoryPipeline(ProjectConfig(project_id="test")).run(tiny_script)
    plain = render_pdf(state.artifacts["report"]["eo_report"])
    marked = render_pdf(state.artifacts["report"]["eo_report"], watermark="UNDERWRITER COPY")

    assert marked != plain
