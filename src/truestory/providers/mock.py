"""MockProvider. Fixtures, CI, and zero dollars.

The default mode of the whole system. A fresh clone with no credentials runs
the complete eight stage pipeline against this provider and produces a real
report, which is what makes the repository reviewable by anyone in under five
minutes.

Fixtures are recorded provider responses stored under eval/fixtures. When no
fixture matches, the provider synthesises a plausible, clearly labelled answer
so that the pipeline exercises every branch, including the ones nobody wants:
contradictions, conflicts, low confidence, and outright research failure.

Nothing here ever reaches a deliverable. Every synthesised envelope carries
`provider="mock"`, and the report generator refuses to render a final E&O
package from a run whose evidence is mock sourced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from truestory.config import FIXTURE_DIR
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import EnumerationProvider, ResearchRequest


class MockProvider(EnumerationProvider):
    name = "mock"
    supports_citations = True
    supports_async = False
    unit_cost_cents = 0.0

    def __init__(self, fixture_dir: Path | None = None, *, synthesise: bool = True) -> None:
        self.fixture_dir = fixture_dir or FIXTURE_DIR
        self.synthesise = synthesise
        self._index: dict[str, dict[str, Any]] | None = None

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self._index is not None:
            return self._index
        index: dict[str, dict[str, Any]] = {}
        if self.fixture_dir.exists():
            for path in self.fixture_dir.rglob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for record in data if isinstance(data, list) else [data]:
                    key = record.get("cache_key") or record.get("subject_id")
                    if key:
                        index[str(key)] = record
        self._index = index
        return index

    def _lookup(self, request: ResearchRequest) -> dict[str, Any] | None:
        index = self._load_index()
        return index.get(request.cache_key()) or index.get(request.subject_id)

    # ── the call ─────────────────────────────────────────────────────────────
    async def investigate(self, request: ResearchRequest) -> Evidence:
        fixture = self._lookup(request)
        if fixture is not None:
            return self._from_fixture(request, fixture)
        if not self.synthesise:
            return Evidence.failed(
                request.subject_id, request.question, self.name, "no fixture recorded"
            )
        return self._synthesise(request)

    async def enumerate(self, request: ResearchRequest) -> list[Evidence]:
        fixture = self._lookup(request)
        if fixture and isinstance(fixture.get("matches"), list):
            return [
                self._from_fixture(request, {**fixture, "finding": m})
                for m in fixture["matches"]
            ]
        return [self._synthesise(request)]

    async def watch(
        self,
        subject_id: str,
        query: str,
        cadence: str = "monthly",
        *,
        reason: str = "",
        expiry_hint: Any = None,
        output_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Mirror the Monitor interface so Living Clearance is demonstrable offline.

        Without this, the monitor manifest comes back empty in mock mode and
        the subsystem that justifies the subscription model is invisible to
        anyone reviewing the repository without credentials.
        """
        import hashlib

        from truestory.models.evidence import MonitorHandle

        digest = hashlib.sha256(f"{subject_id}|{query}".encode()).hexdigest()[:16]
        return MonitorHandle(
            monitor_id=f"mon_{digest}",
            subject_id=subject_id,
            provider_monitor_id=f"mock_{digest}",
            query=query,
            cadence=cadence,
            reason=reason or "Synthesised watch, mock provider.",
            expiry_hint=expiry_hint,
            active=True,
        )

    # ── construction ─────────────────────────────────────────────────────────
    def _from_fixture(self, request: ResearchRequest, fixture: dict[str, Any]) -> Evidence:
        citations = [
            Citation(
                url=c.get("url", "https://example.invalid/fixture"),
                title=c.get("title", "Recorded fixture source"),
                excerpt=c.get("excerpt", ""),
                source_type=c.get("source_type", "primary"),
            )
            for c in fixture.get("citations", [])
        ] or [_fixture_citation()]

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=fixture.get("finding", fixture),
            citations=citations,
            reasoning=fixture.get("reasoning", "Recorded fixture response."),
            confidence=float(fixture.get("confidence", 0.85)),
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=0.0,
            latency_ms=int(fixture.get("latency_ms", 40)),
        )

    def _synthesise(self, request: ResearchRequest) -> Evidence:
        """Deterministic pseudo answers, spread across every outcome branch.

        Seeded on the cache key, so the same subject produces the same answer
        on every run. Without that, the overlay would flicker between takes and
        the eval numbers would be noise.
        """
        seed = int(hashlib.sha256(request.cache_key().encode()).hexdigest()[:8], 16)
        bucket = seed % 100

        # Roughly the distribution the demo screenplay is engineered to
        # produce: mostly green, a meaningful amber band, red rare and
        # therefore legible, plus a small tail of genuine failure so the
        # coverage warning path is exercised in development.
        if bucket < 62:
            verdict, confidence, quality = "supported", 0.91, "strong"
        elif bucket < 80:
            verdict, confidence, quality = "no_record", 0.58, "thin"
        elif bucket < 88:
            verdict, confidence, quality = "contradicted", 0.94, "strong"
        elif bucket < 95:
            verdict, confidence, quality = "supported", 0.71, "moderate"
        else:
            return Evidence.failed(
                request.subject_id,
                request.question,
                self.name,
                "synthesised research failure, exercises the coverage warning path",
            )

        finding = _synthetic_finding(request.schema_name, verdict, quality, seed)

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=finding,
            citations=[
                Citation(
                    url=f"https://example.invalid/record/{seed % 9999}",
                    title="Synthesised record, mock provider",
                    excerpt=(
                        "This envelope was produced by MockProvider and carries no "
                        "research value. It exists so the pipeline can be exercised "
                        "end to end with no credentials and no spend."
                    ),
                    source_type="primary",
                ),
                _fixture_citation(),
            ],
            reasoning=(
                "Synthesised by MockProvider. Not a research finding. "
                "Set TRUESTORY_MODE=live for real verification."
            ),
            confidence=confidence,
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=0.0,
            latency_ms=25 + (seed % 120),
        )


def _fixture_citation() -> Citation:
    return Citation(
        url="https://example.invalid/mock",
        title="MockProvider",
        excerpt="Offline fixture. No real source was consulted.",
        source_type="tertiary",
    )


def _synthetic_finding(
    schema_name: str, verdict: str, quality: str, seed: int
) -> dict[str, Any]:
    """Shape the synthetic payload to the schema the caller asked for."""
    if schema_name == "claim_verification_v1":
        supporting = (
            [
                {
                    "fact": "Synthesised supporting fact.",
                    "source_url": f"https://example.invalid/record/{seed % 9999}",
                    "source_type": "primary",
                }
            ]
            if verdict == "supported"
            else []
        )
        contradicting = (
            [
                {
                    "fact": "Synthesised contradicting fact.",
                    "source_url": f"https://example.invalid/record/{(seed + 7) % 9999}",
                    "source_type": "primary",
                }
            ]
            if verdict == "contradicted"
            else []
        )
        return {
            "claim_restated": "Synthesised restatement of the submitted claim.",
            "verdict": verdict,
            "supporting_facts": supporting,
            "contradicting_facts": contradicting,
            "subject_alive": bool(seed % 3),
            "subject_public_figure_status": ["public", "limited_purpose", "private"][seed % 3],
            "record_quality": quality,
        }

    if schema_name == "person_collision_v1":
        count = seed % 4
        return {
            "real_persons_matching": [
                {
                    "name": f"Synthesised Person {i + 1}",
                    "city": "Springfield",
                    "profession": "physician",
                    "prominence": "low",
                    "source_url": f"https://example.invalid/person/{seed + i}",
                }
                for i in range(count)
            ],
            "same_profession_same_locale": count > 1,
            "collision_risk": ["none", "low", "medium", "high"][count],
            "recommended_action": "clear" if count == 0 else "rename",
            "alternate_names": [
                {"name": "Marlowe", "syllable_match": True, "period_plausible": True},
                {"name": "Hallam", "syllable_match": True, "period_plausible": True},
                {"name": "Renwick", "syllable_match": True, "period_plausible": True},
            ],
        }

    if schema_name == "music_rights_v1":
        return {
            "public_domain_status": "in_copyright" if seed % 2 else "pd",
            "composition_rights_holder": "Synthesised Publishing",
            "master_rights_holder": "Synthesised Records",
            "publication_year": 1958 + (seed % 20),
            "territories_verified": ["US"],
            "typical_license_term_years": 10,
        }

    if schema_name == "identifiability_v1":
        matches = seed % 3
        return {
            "identifiable": matches > 0,
            "attribute_cluster": ["profession", "city", "relationship"],
            "discriminating_attributes": ["profession", "city"],
            "matching_persons": [
                {"match_strength": "strong", "profession": "solicitor", "city": "Camden"}
                for _ in range(matches)
            ],
            "identifiability_risk": ["none", "medium", "high"][matches],
            "recommended_action": "clear" if matches == 0 else "alter_discriminating_attributes",
        }

    return {"synthesised": True, "verdict": verdict, "record_quality": quality}
