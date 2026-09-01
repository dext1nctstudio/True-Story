"""Parallel Task provider. The core verification and clearance research path.

Task is a multi hop research agent that takes an objective and an output
schema and returns structured, cited findings. It is the single most used
provider in the system: every factual claim and every CRITICAL element goes
through it, tier routed to a processor depth.

Two implementation notes that matter for the demo:

  * The `-fast` processor variants cost the same as the standard ones and skip
    live crawling. Latency drops enough that the on camera run stays
    synchronous, which is why the overlay fills in live instead of showing a
    spinner. Set PARALLEL_USE_FAST_VARIANTS=false for batch work where depth
    matters more than latency.

  * Deep processors are dispatched with a webhook callback and the run state is
    parked in Firestore. `investigate` awaits inline for lite and base, and
    returns a PENDING envelope for core and above when async dispatch is on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from truestory.config import settings
from truestory.models.enums import Processor
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    ProviderError,
    ProviderOutOfService,
    RateLimited,
    ResearchProvider,
    ResearchRequest,
    _resolve_api_key,
)

#: Status codes that mean the account, not the request, is the problem. These
#: answer identically for every remaining subject, so they end the provider's
#: participation in the run instead of being recorded as a research result.
_OUT_OF_SERVICE = frozenset({401, 402, 403})


class ParallelTaskProvider(ResearchProvider):
    """Structured multi hop research with citations and calibrated confidence."""

    name = "parallel_task"
    supports_citations = True
    supports_async = True

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or _resolve_api_key()
        self.base_url = (base_url or settings.parallel_api_base).rstrip("/")
        self._client = client
        self._healthy = True

    # ── client ───────────────────────────────────────────────────────────────
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(settings.parallel_timeout_seconds),
                headers={
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "user-agent": "truestory/0.1 (clearance pipeline)",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            resp = await self._http().get("/v1/health", timeout=5.0)
            self._healthy = resp.status_code < 500
        except Exception:
            self._healthy = False
        return self._healthy

    # ── the call ─────────────────────────────────────────────────────────────
    async def investigate(self, request: ResearchRequest) -> Evidence:
        processor = settings.processor(str(request.processor))
        payload = self._build_payload(request, processor)

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1/tasks/runs", json=payload)

                if resp.status_code == 429:
                    raise RateLimited(self.name, float(resp.headers.get("retry-after", 30)))
                if resp.status_code in _OUT_OF_SERVICE:
                    # 402 drained, 401 rejected key, 403 revoked permission.
                    # None of these will answer differently for the next
                    # subject, so the provider leaves service now rather than
                    # failing every remaining subject the same way.
                    raise ProviderOutOfService(
                        self.name, f"HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                if resp.status_code >= 400:
                    raise ProviderError(
                        self.name,
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                        retryable=resp.status_code >= 500,
                    )

                body = resp.json()

            except (RateLimited, ProviderOutOfService):
                # Both propagate. Recording either as failed evidence would
                # bury an account level fault inside a per subject result,
                # which is exactly how a drained account came to read as a
                # silent public record.
                raise
            except httpx.TimeoutException:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    "timeout awaiting Parallel Task",
                )
            except ProviderError as exc:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    str(exc),
                )
            except Exception as exc:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    f"unexpected: {type(exc).__name__}: {exc}",
                )

        # Deep processors may return a handle rather than a result. The webhook
        # receiver completes the record when the callback lands.
        if body.get("status") in {"queued", "running"} and "run_id" in body:
            # ...but only if a callback can actually reach us. Every processor
            # answers 202/queued, so without a reachable webhook the whole
            # swarm parks on pending, reports a 100% failure rate and $0 spend,
            # and the report comes out empty. Collect the result inline instead.
            if self._webhook_reachable():
                return self._pending(request, body["run_id"], timing["latency_ms"])
            return await self._await_result(request, body["run_id"], timing["latency_ms"])

        return self.to_evidence(request, body, timing["latency_ms"])

    @staticmethod
    def _webhook_reachable() -> bool:
        """A callback URL that is absent, a placeholder, or local is no callback."""
        url = settings.parallel_webhook_url
        if not url or "PLACEHOLDER" in url:
            return False
        return not any(host in url for host in ("localhost", "127.0.0.1"))

    async def _await_result(
        self, request: ResearchRequest, run_id: str, dispatch_ms: int
    ) -> Evidence:
        """Block on Parallel's result endpoint, which long polls server side."""
        try:
            resp = await self._http().get(
                f"/v1/tasks/runs/{run_id}/result",
                params={"timeout": int(settings.parallel_timeout_seconds)},
                timeout=settings.parallel_timeout_seconds + 15,
            )
            if resp.status_code >= 400:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    f"result HTTP {resp.status_code}: {resp.text[:200]}",
                )
            return self.to_evidence(request, resp.json(), dispatch_ms)
        except httpx.TimeoutException:
            # Still running at the deadline: hand back the handle so the webhook
            # path can finish it if one is ever configured.
            return self._pending(request, run_id, dispatch_ms)
        except Exception as exc:
            return Evidence.failed(
                request.subject_id,
                request.question,
                self._qualified_name(request.processor),
                f"result fetch failed: {type(exc).__name__}: {exc}",
            )

    # ── payload ──────────────────────────────────────────────────────────────
    def _build_payload(self, request: ResearchRequest, processor: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "processor": processor,
            "input": request.question,
            "task_spec": {
                "output_schema": {
                    "type": "json",
                    "json_schema": request.output_schema,
                }
            },
            # Parallel validates metadata values as scalars, so a list here is
            # a 422 for every subject in the swarm rather than a bad field.
            "metadata": {
                "subject_id": request.subject_id,
                "schema": request.schema_name,
                "tier": str(request.tier),
                "jurisdictions": ",".join(request.jurisdictions),
                "env": settings.env_name,
            },
        }
        if request.idempotency_key:
            payload["metadata"]["idempotency_key"] = request.idempotency_key

        # Keep the crawler away from the hosts that cannot support a finding.
        # Machine generated encyclopedias restate their training data without
        # attribution and content farms restate each other; a claim about a
        # real person resting on either rests on nothing checkable. Top level
        # field, not inside task_spec.
        # https://docs.parallel.ai/resources/source-policy
        if _EXCLUDED_SOURCES:
            payload["source_policy"] = {"exclude_domains": list(_EXCLUDED_SOURCES)}

        # Async dispatch for the deep processors. The receiver verifies the
        # signature on every inbound callback before it touches run state.
        if (
            request.processor in (Processor.CORE, Processor.PRO, Processor.ULTRA)
            and settings.parallel_webhook_url
        ):
            payload["webhook"] = {
                "url": settings.parallel_webhook_url,
                "event_types": ["task_run.status"],
            }
        return payload

    def _pending(self, request: ResearchRequest, run_id: str, latency_ms: int) -> Evidence:
        return Evidence(
            evidence_id=Evidence.make_id(
                request.subject_id, request.question, self._qualified_name(request.processor)
            ),
            subject_id=request.subject_id,
            question=request.question,
            finding={"status": "pending", "provider_run_id": run_id},
            citations=[],
            reasoning="Dispatched to Parallel Task. Awaiting webhook callback.",
            confidence=0.0,
            provider=self._qualified_name(request.processor),
            schema_version=request.schema_name,
            latency_ms=latency_ms,
            cost_cents=request.processor.usd_per_run * 100,
        )

    # ── response mapping ─────────────────────────────────────────────────────
    def to_evidence(
        self,
        request: ResearchRequest,
        body: dict[str, Any],
        latency_ms: int = 0,
    ) -> Evidence:
        """Map a Task response onto the Evidence envelope.

        This is the seam where the Basis framework does its work. Parallel
        returns citations, reasoning, excerpts and a calibrated confidence per
        output field, which is why the mapping is close to one to one rather
        than a scraping exercise. A partner whose core differentiator is
        evidence is the right partner for a product whose output is a statement
        that a line about a real person is false.
        """
        output = body.get("output", {})
        content = output.get("content", output) if isinstance(output, dict) else {}
        basis = output.get("basis", []) if isinstance(output, dict) else []

        confidence = self._confidence_from_basis(basis)
        reasoning = self._reasoning_from_basis(basis)

        # Three places carry sources and all three are read, because losing any
        # one of them shows up as a subject with "no citable source" that had
        # in fact been researched successfully:
        #
        #   basis[]                     Parallel's per field citations
        #   content.sources[]           schemas that ask for sources directly
        #   content.*_facts[].source_url  claim_verification_v1, the workhorse
        #
        # The last one was never read at all, which is why claim verification
        # ran on basis alone and every thin basis became an amber line.
        harvested = _CitationBag()
        harvested.add_basis(basis)
        if isinstance(content, dict):
            harvested.add_sources(content.get("sources"))
            harvested.add_facts(content)
        citations = harvested.build()

        # A finding of "no record" has no sources by definition, and the ones
        # the API returns alongside it are what it looked at while finding
        # nothing. Measured on the live API: asked whether an invented person
        # was dismissed from an invented board, Parallel correctly answered
        # no_record and attached a citation to a teenage swimmer's results
        # page, because the basis explains fields like record_quality rather
        # than the verdict. Publishing that under the verdict is worse than
        # publishing nothing, so nothing is what it publishes.
        if _is_silence(content):
            citations = []

        return Evidence(
            evidence_id=Evidence.make_id(
                request.subject_id, request.question, self._qualified_name(request.processor)
            ),
            subject_id=request.subject_id,
            question=request.question,
            finding=content if isinstance(content, dict) else {"value": content},
            citations=citations,
            reasoning=reasoning,
            confidence=confidence,
            provider=self._qualified_name(request.processor),
            schema_version=request.schema_name,
            cost_cents=request.processor.usd_per_run * 100,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _confidence_from_basis(basis: list[dict[str, Any]]) -> float:
        """Take the weakest field level confidence, not the average.

        An answer is only as good as its least supported component, and
        averaging is how an unsupported field hides behind four solid ones.
        """
        scores: list[float] = []
        for field_basis in basis:
            raw = field_basis.get("confidence")
            if isinstance(raw, int | float):
                scores.append(float(raw))
            elif isinstance(raw, str):
                scores.append({"high": 0.9, "medium": 0.7, "low": 0.4}.get(raw.lower(), 0.5))
        return min(scores) if scores else 0.5

    @staticmethod
    def _reasoning_from_basis(basis: list[dict[str, Any]]) -> str:
        parts = [
            f"{fb.get('field', 'output')}: {fb['reasoning']}" for fb in basis if fb.get("reasoning")
        ]
        return "\n".join(parts) if parts else "No reasoning trace returned."


# =============================================================================
# citation harvesting
# =============================================================================


class _CitationBag:
    """Collect citations from every place a Task response hides them.

    Deduplicates on a normalised URL, and merges rather than discards: the
    basis entry usually carries the excerpt, the schema's own facts array
    usually carries the source type and the publication date, and the two
    describe the same page. Keeping whichever arrived first threw away half of
    each.
    """

    __slots__ = ("_by_url",)

    def __init__(self) -> None:
        self._by_url: dict[str, dict[str, Any]] = {}

    # ── inputs ───────────────────────────────────────────────────────────────
    def add_basis(self, basis: Any) -> None:
        """Parallel's per field citations: {field, citations:[{url, excerpts[]}]}.

        Only the fields that carry the answer count. A Task response returns a
        basis entry per output field, so `record_quality` and `temporal_scope`
        come back with citations of their own — and those are provenance for a
        piece of metadata, not evidence for the claim. Harvesting all of them
        was the single largest source of irrelevant citations in the product.
        """
        if not isinstance(basis, list):
            return
        for field_basis in basis:
            if not isinstance(field_basis, dict):
                continue
            if not _bears_on_the_answer(field_basis.get("field")):
                continue
            for cit in field_basis.get("citations") or []:
                if not isinstance(cit, dict):
                    continue
                self._merge(
                    url=cit.get("url"),
                    title=cit.get("title"),
                    # The field is `excerpts`, a list. Reading `excerpt` meant
                    # every citation in the evidence appendix was blank.
                    excerpt=_join_excerpts(cit.get("excerpts"), cit.get("excerpt")),
                    declared=cit.get("source_type"),
                    publisher=cit.get("publisher"),
                    published=cit.get("published_date") or cit.get("date"),
                )

    def add_sources(self, sources: Any) -> None:
        """A schema's own `sources` array. entity_v1 and friends."""
        if not isinstance(sources, list):
            return
        for src in sources:
            if not isinstance(src, dict):
                continue
            self._merge(
                url=src.get("url") or src.get("source_url"),
                title=src.get("title"),
                excerpt=_join_excerpts(src.get("excerpts"), src.get("excerpt")),
                declared=src.get("source_type"),
                publisher=src.get("publisher"),
                published=src.get("published_date") or src.get("date"),
            )

    def add_facts(self, content: dict[str, Any]) -> None:
        """Any `*_facts` array: the fact itself doubles as the excerpt.

        claim_verification_v1 puts the whole verification here — supporting and
        contradicting facts, each with its own source URL and declared type.
        This is the workhorse schema and its sources were being dropped.
        """
        for key, value in content.items():
            if not key.endswith(("_facts", "_findings", "_records")) or not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                self._merge(
                    url=item.get("source_url") or item.get("url"),
                    title=item.get("title"),
                    excerpt=item.get("excerpt") or item.get("fact"),
                    declared=item.get("source_type"),
                    publisher=item.get("publisher"),
                    published=item.get("date") or item.get("published_date"),
                )

    # ── output ───────────────────────────────────────────────────────────────
    def build(self) -> list[Citation]:
        """Classify every URL and return the citation list, best first."""
        citations = [
            Citation.classified(
                url=entry["url"],
                title=entry.get("title") or "",
                excerpt=entry.get("excerpt") or "",
                declared_type=entry.get("declared"),
                publisher=entry.get("publisher"),
                published_at=_parse_date(entry.get("published")),
            )
            for entry in self._by_url.values()
        ]
        # Strongest pedigree first, so the evidence panel opens on the docket
        # rather than on whichever aggregator happened to be returned first.
        citations.sort(key=lambda c: (-c.trust, c.url))
        return citations

    # ── internals ────────────────────────────────────────────────────────────
    def _merge(
        self,
        url: Any,
        title: Any = None,
        excerpt: Any = None,
        declared: Any = None,
        publisher: Any = None,
        published: Any = None,
    ) -> None:
        if not isinstance(url, str) or not url.strip():
            return
        key = _normalise_url(url)
        entry = self._by_url.setdefault(key, {"url": url.strip()})

        if title and not entry.get("title"):
            entry["title"] = str(title)[:300]
        # Longest excerpt wins: the evidence appendix quotes it, so more of the
        # passage relied on is strictly better.
        if excerpt and len(str(excerpt)) > len(str(entry.get("excerpt") or "")):
            entry["excerpt"] = str(excerpt)[:1200]
        if declared and not entry.get("declared"):
            entry["declared"] = str(declared)
        if publisher and not entry.get("publisher"):
            entry["publisher"] = str(publisher)
        if published and not entry.get("published"):
            entry["published"] = published


def _join_excerpts(excerpts: Any, singular: Any = None) -> str:
    """Parallel returns `excerpts: [str]`; older shapes returned `excerpt: str`."""
    if isinstance(excerpts, list):
        parts = [str(e).strip() for e in excerpts if str(e).strip()]
        if parts:
            return " … ".join(parts)[:1200]
    if isinstance(excerpts, str) and excerpts.strip():
        return excerpts.strip()[:1200]
    return str(singular).strip()[:1200] if isinstance(singular, str) else ""


def _normalise_url(url: str) -> str:
    """Fold the trivial variants so one page is not counted as three sources."""
    cleaned = url.strip().lower().split("#", 1)[0].rstrip("/")
    for prefix in ("https://", "http://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned[4:] if cleaned.startswith("www.") else cleaned


def _parse_date(value: Any) -> datetime | None:
    """Best effort ISO date. A source's age governs how far it is trusted."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


#: Hosts the research is told not to read. Capped at ten, which is the
#: documented limit, so this is the worst offenders rather than a blocklist:
#: everything else is handled downstream by classification and attribution.
_EXCLUDED_SOURCES: tuple[str, ...] = (
    "grokipedia.com",
    "wikiwand.com",
    "alchetron.com",
    "peoplepill.com",
    "famousbirthdays.com",
    "celebritynetworth.com",
    "ranker.com",
    "quora.com",
    "answers.com",
    "pinterest.com",
)

#: Output fields whose citations are evidence for the finding itself. Anything
#: else in a Task response is a field about the research rather than about the
#: subject, and its sources belong in neither the overlay nor the appendix.
_ANSWER_FIELDS = frozenset(
    {
        "verdict",
        "claim_restated",
        "supporting_facts",
        "contradicting_facts",
        "status",
        "recommended_action",
        "risk",
        "entity_exists",
        "canonical_name",
        "matching_persons",
        "real_persons_matching",
        "rights_holder",
        "copyright_status",
        "registration",
        "work_identified",
        "alive",
        "subject_alive",
    }
)

#: What a payload says when the record is silent. Silence is a finding; it is
#: not a finding with sources.
_SILENT_VERDICTS = frozenset({"no_record", "not_found", "unknown", "silent"})


def _bears_on_the_answer(field_name: Any) -> bool:
    if not isinstance(field_name, str) or not field_name:
        return False
    root = field_name.split(".", 1)[0].split("[", 1)[0].strip().lower()
    return root in _ANSWER_FIELDS


def _is_silence(content: Any) -> bool:
    """Whether the payload reported that the record holds nothing either way."""
    if not isinstance(content, dict):
        return False
    verdict = content.get("verdict")
    if not isinstance(verdict, str):
        return False
    if verdict.strip().lower() not in _SILENT_VERDICTS:
        return False
    # A payload that says "no record" while listing facts on either side is
    # contradicting itself; the facts win, because they are checkable.
    facts = 0
    for key, value in content.items():
        if key.endswith("_facts") and isinstance(value, list):
            facts += len(value)
    return facts == 0
