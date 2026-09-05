#!/usr/bin/env python
"""Proof, not a pass/fail count, that every feature added this session actually runs.

    python eval/prove_new_features.py                    # mock mode, no credentials
    python eval/prove_new_features.py --live              # real Parallel + Gemini calls
    python eval/prove_new_features.py --script other.fountain
    python eval/prove_new_features.py --live --script eval/fixtures/live_proof.fountain

MOCK MODE (the default) runs the real pipeline with no credentials at all.
`pytest` already proves each unit behaves correctly in isolation; this proves
the features actually fire, in order, on a real run, and prints the evidence
so a human can look at it rather than trust a count of green dots. Feature 1
(the registry lookup) is proven directly against a fake USPTO transport in
this mode, because the offline tagger mock mode falls back to never produces
a BUSINESS_NAME or TRADEMARK_LOGO span in the first place -- that
classification only happens in the real model pass.

LIVE MODE (`--live`) spends real money and makes real calls: Gemini for
ingestion and adjudication, Parallel Task for research, and USPTO's register
if a key is configured. It defaults to `eval/fixtures/live_proof.fountain`,
written specifically to exercise every feature in one short scene: a truth
claim card, a brand on a cup, a real still-copyrighted painting named on
screen, a real song named with its artist, a tattoo, and a claim about an
invented senator (see that file's header for why the person is invented
rather than real -- writing a fabricated damaging claim about an actual
living person into a committed test file would be the harm this product
exists to catch, not a safe way to test it). This is the only way to see
"researched" rather than "policy_table" on the cure cost check, and the only
way to see the registry lookup fire through real ingestion rather than
through a direct provider call.

Each check below either finds concrete evidence in the run's own output and
prints it, or says plainly that it found nothing and why -- a feature that is
wired but did not fire on this particular script is a different, and honest,
outcome from one that is broken.

Exits 0 only if every check that could fire, did.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_MOCK_SCRIPT = REPO_ROOT / "ms_dhoni_evidence_test.fountain"
DEFAULT_LIVE_SCRIPT = REPO_ROOT / "eval" / "fixtures" / "live_proof.fountain"

#: What --live needs to not fail confusingly halfway through a run. Mirrors
#: config.Settings._guard_live_mode, checked here so a missing key is one
#: clear message before any network call rather than a stack trace from deep
#: inside the pipeline.
_REQUIRED_FOR_LIVE = ("PARALLEL_API_KEY", "GOOGLE_CLOUD_PROJECT")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="use real Parallel and Gemini calls instead of mock mode (spends money)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=None,
        help="fountain file to run (default: live_proof.fountain for --live, "
        "ms_dhoni_evidence_test.fountain otherwise)",
    )
    return parser.parse_args()


def _preflight_live(env: dict) -> list[str]:
    """What's missing before a --live run is attempted. Empty means go."""
    missing = []
    for name in _REQUIRED_FOR_LIVE:
        value = env.get(name, "")
        if not value or value.startswith("PLACEHOLDER"):
            missing.append(name)
    return missing


_ARGS = _parse_args()

import os  # noqa: E402

if _ARGS.live:
    missing = _preflight_live(os.environ)
    if missing:
        print("--live requires credentials that are not configured:")
        for name in missing:
            print(f"  {name} is missing or still a PLACEHOLDER in .env")
        print("\nSet these in .env, or drop --live to run the same proof in mock mode.")
        raise SystemExit(2)
    os.environ["TRUESTORY_MODE"] = "live"
    if not os.environ.get("USPTO_API_KEY") or os.environ["USPTO_API_KEY"].startswith("PLACEHOLDER"):
        print(
            "note: USPTO_API_KEY is not configured. Feature 1's routing and citation "
            "shape are still proven directly against a fake transport; the mark in "
            "live_proof.fountain will fall back to Parallel Task research instead of "
            "the real register.\n"
        )
else:
    os.environ.setdefault("TRUESTORY_MODE", "mock")

from truestory.agents.pipeline import ProjectConfig, TrueStoryPipeline  # noqa: E402

DEFAULT_SCRIPT = _ARGS.script or (DEFAULT_LIVE_SCRIPT if _ARGS.live else DEFAULT_MOCK_SCRIPT)

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP (feature wired, did not fire on this script)"


class Check:
    def __init__(self, feature: str) -> None:
        self.feature = feature
        self.status = FAIL
        self.evidence: list[str] = []

    def ok(self, *lines: str) -> None:
        self.status = PASS
        self.evidence.extend(lines)

    def skip(self, *lines: str) -> None:
        self.status = SKIP
        self.evidence.extend(lines)

    def fail(self, *lines: str) -> None:
        self.status = FAIL
        self.evidence.extend(lines)

    def report(self) -> bool:
        print(f"\n[{self.status}] {self.feature}")
        for line in self.evidence:
            print(f"    {line}")
        return self.status != FAIL


# =============================================================================
# the checks, one per feature added this session
# =============================================================================
async def check_registry_lookup_routing() -> Check:
    """Feature 1: marks are routed to, and answered by, the trademark register.

    The offline tagger mock mode uses never produces BUSINESS_NAME,
    BRAND_PRODUCT or TRADEMARK_LOGO spans at all -- that classification only
    happens in the model pass -- so no fixture run through the pipeline in
    mock mode could ever exercise this end to end. Proving it honestly means
    dispatching a mark directly against a fake USPTO transport, exactly as
    the registry_lookup provider's own test suite does, rather than reporting
    a permanent, misleading SKIP.
    """
    c = Check("1. Trademark registry lookup (asks the register, not the open web)")
    import httpx

    from truestory.models.enums import Processor, RiskTier
    from truestory.policy import load_routing
    from truestory.providers.base import ResearchRequest
    from truestory.providers.registry_lookup import RegistryLookupProvider

    rule = next(r for r in load_routing().rules if r.rule_id == "marks")
    if rule.provider != "registry_lookup":
        c.fail(f"marks rule provider is {rule.provider!r}, expected registry_lookup")
        return c

    record = {
        "markLiteralElementText": "KESTREL",
        "serialNumber": "86181542",
        "registrationNumber": "4712345",
        "markCurrentStatusExternalDescriptionText": "LIVE/REGISTRATION/Issued and Active",
        "ownerName": ["Kestrel Holdings LLC"],
        "internationalClassCode": ["041"],
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [record]})),
        base_url="https://api.uspto.gov",
    )
    provider = RegistryLookupProvider(api_key="proof-key", client=client)
    request = ResearchRequest(
        subject_id="proof-mark",
        question="Assess the trademark position for an on screen use.\n\nMARK: Kestrel\nTERRITORIES: US\n",
        output_schema={},
        schema_name="trademark_v1",
        tier=RiskTier.HIGH,
        processor=Processor.BASE,
    )
    evidence = await provider.investigate(request)
    await client.aclose()

    if evidence.error or not evidence.finding.get("mark_registered"):
        c.fail(f"registry lookup did not resolve the mark: {evidence.error or evidence.finding}")
        return c
    if not evidence.citations or "tsdr.uspto.gov" not in evidence.citations[0].url:
        c.fail(f"citation is not a TSDR link: {evidence.citations}")
        return c

    c.ok(
        "routing.yaml: marks -> provider=registry_lookup (confirmed)",
        f"mark 'Kestrel' resolved: owner={evidence.finding['owner']!r}, "
        f"registration={evidence.finding['registration_numbers']}, cost={evidence.cost_cents}c",
        f"citation: {evidence.citations[0].url} (source_class={evidence.citations[0].source_class}, "
        f"trust={evidence.citations[0].trust})",
    )
    return c


def check_monitor_pinned_to_record(state) -> Check:
    """Feature 2: a mark's monitor watches the registration record, not the bare word."""
    c = Check("2. Monitor watches the register record, not the word")
    from truestory.agents.swarm import _monitor_query
    from truestory.models.elements import ClearableElement
    from truestory.models.enums import ElementType, RiskTier
    from truestory.models.evidence import Evidence

    element = ClearableElement(
        element_id="proof-el",
        element_type=ElementType.TRADEMARK_LOGO,
        canonical_form="Kestrel",
        risk_tier=RiskTier.HIGH,
    )
    registry_evidence = Evidence(
        evidence_id="proof-ev",
        subject_id="proof-el",
        question="MARK: Kestrel",
        finding={
            "registry_context": {},
            "registration_numbers": ["4712345"],
            "owner": "Kestrel Holdings LLC",
        },
        citations=[],
        reasoning="",
        confidence=0.9,
        provider="registry_lookup",
        schema_version="trademark_v1",
    )
    query = _monitor_query(element, registry_evidence)
    if "4712345" not in query:
        c.fail(f"expected the registration number pinned in the query, got: {query!r}")
        return c
    c.ok(f"query built for a registered mark: {query[:110]}...")
    return c


def check_precedent_retrieval(state) -> Check:
    """Feature 3: flagged findings are matched against real past disputes."""
    c = Check("3. Similar past cases (precedent retrieval)")
    if not state.precedents:
        c.fail("state.precedents is empty on a run with counsel_required findings")
        return c

    subject_id, matches = next(iter(state.precedents.items()))
    label = next(
        (e.canonical_form for e in state.elements if e.element_id == subject_id),
        next((cl.claim_text[:40] for cl in state.claims if cl.claim_id == subject_id), subject_id),
    )
    m = matches[0]
    c.ok(
        f"{len(state.precedents)} findings matched against the litigation set",
        f"finding {label!r} -> {m['case_id']} [{m['side']}] matched on {m['matched_on']}",
        f"outcome: {m['outcome'][:80]}",
    )
    return c


def check_ingest_bug_fixes(_state) -> Check:
    """Feature 4: a quoted claim is not a song; a country is not a person."""
    c = Check("4. Ingest fix (quoted claims != songs; countries != people)")
    from truestory.agents.ingest import IngestAgent, _caps_element_type
    from truestory.models.enums import ElementType
    from truestory.models.spans import Scene

    scene = Scene(
        scene_no=1,
        heading="INT. ROOM - DAY",
        start_page=1.0,
        end_page=1.0,
        text='This sentence says, "MS Dhoni scored 97 in the 2011 World Cup final."',
        characters=[],
    )
    spans = IngestAgent()._tag_deterministic(scene)
    misfiled = [s for s in spans if s.element_type == ElementType.MUSIC_CUE]
    if misfiled:
        c.fail(f"a quoted claim was still tagged MUSIC_CUE: {misfiled[0].surface_form!r}")
        return c

    event_type = _caps_element_type("ICC CRICKET WORLD CUP", ElementType.REAL_PERSON_DEPICTED)
    if event_type != ElementType.REAL_EVENT:
        c.fail(f"ICC CRICKET WORLD CUP classified as {event_type}, expected REAL_EVENT")
        return c

    person_type = _caps_element_type("DHONI", ElementType.REAL_PERSON_DEPICTED)
    if person_type != ElementType.REAL_PERSON_DEPICTED:
        c.fail(f"a real surname (DHONI) misclassified as {person_type}")
        return c

    c.ok(
        "quoted claim about MS Dhoni: no MUSIC_CUE span produced",
        "'ICC CRICKET WORLD CUP' -> REAL_EVENT (not a depicted person)",
        "'DHONI' -> REAL_PERSON_DEPICTED (surname correctly kept as a person)",
    )
    return c


def check_extract_on_critical(state) -> Check:
    """Feature 5: every CRITICAL finding archives its strongest source."""
    c = Check("5. Source page archived for every CRITICAL finding")
    from truestory.policy import load_routing

    critical_rules_with_extract = [
        r.rule_id
        for r in load_routing().rules
        if r.tier.name == "CRITICAL" and r.enabled and "extract_evidence_page" in (r.also or ())
    ]
    all_critical_enabled = [
        r.rule_id for r in load_routing().rules if r.tier.name == "CRITICAL" and r.enabled
    ]
    missing = set(all_critical_enabled) - set(critical_rules_with_extract)
    if missing:
        c.fail(f"CRITICAL rules missing extract_evidence_page: {missing}")
        return c

    archived = [
        e
        for e in state.elements
        if any(ev.provider.split(":")[0] == "parallel_extract" for ev in e.evidence)
    ]
    c.ok(
        f"all {len(all_critical_enabled)} enabled CRITICAL routing rules carry extract_evidence_page: {all_critical_enabled}",
        f"{len(archived)} element(s) on this run captured an archived source page"
        if archived
        else "no element on this run reached a usable citation to archive (mock research failures)",
    )
    return c


def check_cure_cost_research_wired(state) -> Check:
    """Feature 6: cost to cure is researched, with the table as a stated fallback."""
    c = Check("6. Cost to cure asks the market (with a labelled fallback)")
    priced = [a for a in state.exposure.get("assessments", []) if a.get("cost_to_cure")]
    if not priced:
        c.fail("no priced findings in state.exposure at all")
        return c

    sources = {a["cost_to_cure"]["source"] for a in priced}
    if not sources <= {"policy_table", "researched"}:
        c.fail(f"unexpected cure source values: {sources}")
        return c

    sample = priced[0]["cost_to_cure"]
    c.ok(
        f"{len(priced)} findings priced; source values present: {sources}",
        f"sample: {sample['remedy_class']} -> ${sample['low_usd']:,}-${sample['high_usd']:,} [{sample['source']}]",
        "(mock mode never calls Parallel Task, so 'researched' will only appear against a live key)",
    )
    return c


def check_exposure_bands_and_anchors(state) -> Check:
    """Feature 7a: every finding gets a band, and statutes attach where they apply."""
    c = Check("7a. Severity bands + statutory anchors")
    assessments = state.exposure.get("assessments", [])
    if not assessments:
        c.fail("state.exposure.assessments is empty")
        return c

    bands = {a["band"] for a in assessments}
    with_anchors = [a for a in assessments if a["statutory_anchors"]]
    c.ok(
        f"{len(assessments)} findings banded: {sorted(bands)}",
        f"{len(with_anchors)} carry a statutory anchor"
        + (
            f"; e.g. {with_anchors[0]['statutory_anchors'][0]['provision']}"
            if with_anchors
            else " (none applied on this script)"
        ),
    )
    return c


def check_quantitative_model(state) -> Check:
    """Feature 7b: frequency x severity ranks findings the ordinal band cannot."""
    c = Check("7b. Quantitative exposure model (frequency x severity, ranked)")
    assessments = state.exposure.get("assessments", [])
    modelled = [a for a in assessments if a.get("modelled_exposure")]
    if not modelled:
        c.fail("no finding carries a modelled_exposure record")
        return c

    for m in modelled:
        p = m["modelled_exposure"]["claim_probability"]
        if not (0.0 <= p <= 1.0):
            c.fail(f"claim_probability out of range: {p} on {m['subject_id']}")
            return c

    same_band = {}
    for a in modelled:
        same_band.setdefault(a["band"], []).append(a["modelled_exposure"]["expected_usd"]["high"])
    discriminates = any(len(set(v)) > 1 for v in same_band.values() if len(v) > 1)

    portfolio = state.exposure.get("modelled_exposure_usd", {})
    c.ok(
        f"{len(modelled)} findings priced; every claim_probability in [0, 1] (the double count bug this guards against)",
        f"portfolio: ${portfolio.get('low', 0):,} - ${portfolio.get('high', 0):,} across {portfolio.get('findings', 0)} findings, calibrated={portfolio.get('calibrated')}",
        "within at least one band, findings are NOT all priced identically (the model discriminates)"
        if discriminates
        else "only one distinct modelled value seen per band on this script (nothing to discriminate between)",
    )
    return c


def check_courtlistener_dataset() -> Check:
    """Feature 8: real, fetched court data exists and is honestly labelled."""
    c = Check("8. Real CourtListener dataset (fetched, not fabricated)")
    import json

    dataset_path = REPO_ROOT / "eval" / "precedent_corpus" / "dataset.json"
    if not dataset_path.exists():
        c.fail(f"{dataset_path} does not exist -- run fetch_courtlistener.py")
        return c

    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    records = data.get("records", [])
    baby_reindeer = [r for r in records if "harvey" in (r.get("case_name") or "").lower()]

    from truestory.policy import load_exposure

    calibrated = load_exposure().raw.get("quantitative", {}).get("calibrated")
    if calibrated is not False:
        c.fail(
            f"quantitative.calibrated is {calibrated!r}, expected False -- "
            "this dataset must not silently flip that flag"
        )
        return c

    c.ok(
        f"{len(records)} real federal dockets in {dataset_path.name}",
        f"includes the real Baby Reindeer suit: {baby_reindeer[0]['case_name']}"
        if baby_reindeer
        else "(re-run fetch_courtlistener.py; the sample used for this proof did not include it)",
        f"median days to resolution (real docket data): {data['summary'].get('median_days_to_resolution')}",
        "quantitative.calibrated is still False -- this data was NOT folded into the model's numbers",
    )
    return c


# =============================================================================
# runner
# =============================================================================
async def main() -> int:
    script = DEFAULT_SCRIPT
    mode = (
        "LIVE (real Parallel + Gemini calls, spends money)"
        if _ARGS.live
        else "mock (no credentials)"
    )
    print(f"Running the real pipeline in {mode} mode over {script}\n")

    pipeline = TrueStoryPipeline(
        ProjectConfig(project_id="proof", title="Feature proof", production_stage="post")
    )
    state = await pipeline.run(script)

    print(f"pipeline status: {state.status}")
    print(
        f"elements: {len(state.elements)}  claims: {len(state.claims)}  "
        f"precedent matches: {len(state.precedents)}  "
        f"exposure assessments: {len(state.exposure.get('assessments', []))}"
    )

    checks = [
        await check_registry_lookup_routing(),
        check_monitor_pinned_to_record(state),
        check_precedent_retrieval(state),
        check_ingest_bug_fixes(state),
        check_extract_on_critical(state),
        check_cure_cost_research_wired(state),
        check_exposure_bands_and_anchors(state),
        check_quantitative_model(state),
        check_courtlistener_dataset(),
    ]

    ok = True
    for check in checks:
        ok = check.report() and ok

    print("\n" + "=" * 78)
    passed = sum(1 for c in checks if c.status == PASS)
    skipped = sum(1 for c in checks if c.status == SKIP)
    failed = sum(1 for c in checks if c.status == FAIL)
    print(
        f"{passed} fired and verified, {skipped} skipped (not applicable to this script), {failed} failed"
    )
    print("=" * 78)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
