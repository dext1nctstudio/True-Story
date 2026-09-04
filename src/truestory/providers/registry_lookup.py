"""Registry lookup provider. The register itself, rather than an article about it.

Every mark in a script currently reaches the report through prose. The routing
table sends `BUSINESS_NAME`, `TRADEMARK_LOGO` and `BRAND_PRODUCT` to Parallel
Task, Task reads the open web, and the answer arrives as a sentence with a
citation attached. On a live run those citations were `uspto.report`, a scraper
that restates the register, rather than the register.

That distinction is the whole product. `source_quality` already scores
`tsdr.uspto.gov` as a registry at trust 0.93 and a scraper as an ordinary web
page, so a report that says a mark is live on the strength of a scraper is
making a registry claim without a registry source, and an underwriter reading
the evidence appendix will see that immediately.

This provider asks the register.

WHAT IT ANSWERS, AND WHAT IT DOES NOT
    It answers the registration half of `trademark_v1`: mark of record, owner,
    registration numbers, live or dead, and the Nice classes. Those are facts
    with a custodian, and a custodian's answer needs no confidence calibration.

    It does not answer the `use_assessment` half. Whether an on screen use is
    artistically relevant, or explicitly misleading, or unflattering enough to
    attract a trade libel theory, is a judgement about a screenplay and belongs
    to the adjudicator. This provider returns the record and stops.

    The finding is therefore a partial `trademark_v1` document. It is honest
    about that: `use_assessment` is omitted rather than guessed, and the
    adjudicator fills it from the script.

WHY IT MAKES RUNS CHEAPER
    `unit_cost_cents` is zero. The register is free, the answer is
    deterministic, and the cache key is stable, so the marks rule stops
    spending a base processor per brand. On a script with forty pieces of
    signage that is most of the coverage half of the budget.

CREDENTIALS, AND WHAT HAPPENS WITHOUT THEM
    USPTO's structured search moved behind the Open Data Portal and now wants a
    free API key. Without one this provider reports itself unhealthy, the
    registry's existing fallback chain routes the subject to Parallel Task, and
    the run is exactly as good as it is today. Principle P5: a missing optional
    credential degrades a run, it does not fail one, and it never silently
    turns into a worse answer wearing a better source.

VERIFY: REQUIRED
    The Open Data Portal request and response shapes below were written against
    USPTO's published contract and have NOT been confirmed against a live keyed
    account in this repository. Field extraction is deliberately tolerant of
    several key spellings for that reason, and anything it cannot read becomes
    a failed envelope rather than a partial finding. Confirm against a real key
    before a deliverable relies on it. Same standard as `cases.yaml`.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

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
)

log = logging.getLogger("truestory.registry_lookup")

#: Territories this provider can actually reach. A mark question about anywhere
#: else is not answered badly, it is declined, and the registry falls back to
#: research that can at least read the national register's website.
#:
#: EUIPO and IPO both publish comparable APIs and each is a new adapter here,
#: not a change to any agent. That is principle P3 doing its job.
SUPPORTED_TERRITORIES: frozenset[str] = frozenset({"US", "USA", "UNITED STATES"})

#: Nice classes whose goods and services actually touch a film or television
#: production. A mark is nearly always registered somewhere; the question that
#: decides the recommendation is whether it is registered for anything the
#: production is doing.
#:
#:    9   recorded media, downloadable content
#:   16   printed matter, posters
#:   35   advertising and promotion
#:   38   broadcasting and transmission
#:   41   entertainment, film and television production
#:
#: A mark held only in class 25 for clothing is a different conversation from
#: the same word held in class 41, and this is the line between them. It is a
#: triage aid for the adjudicator, not a legal conclusion, and it is stated as
#: one in the finding.
PRODUCTION_ADJACENT_CLASSES: frozenset[int] = frozenset({9, 16, 35, 38, 41})

#: Status codes that mean the key, not the question, is the problem. Same
#: reasoning as `parallel_task._OUT_OF_SERVICE`: these answer identically for
#: every remaining mark in the script, so they end this provider's
#: participation in the run instead of being recorded as forty findings that
#: the register holds no mark.
_OUT_OF_SERVICE = frozenset({401, 402, 403})

#: The templated question built by `mcp.tools`. The mark is read out of it
#: rather than passed beside it, because `ResearchRequest.question` is
#: assembled from a fixed template and is already the determinism boundary for
#: the cache key. Anchored to the line start so a mark whose own name contains
#: the word "mark" cannot capture the wrong span.
_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "mark": re.compile(r"^(?:MARK|NAME):[ \t]*(.+)$", re.MULTILINE),
    "territories": re.compile(r"^TERRITORIES:[ \t]*(.+)$", re.MULTILINE),
    "jurisdiction": re.compile(r"^JURISDICTION:[ \t]*(.+)$", re.MULTILINE),
}

#: A live application is not a live registration and the difference decides
#: whether there is anyone to negotiate with today. Mapped onto the closed
#: enum `trademark_v1` already publishes.
#:
#: Order matters: this is scanned in sequence against the register's free text
#: status, and "cancelled" must be tested before any looser token that also
#: appears in a cancellation notice.
_STATUS_MAP: tuple[tuple[str, str], ...] = (
    ("abandoned", "dead"),
    ("cancelled", "dead"),
    ("canceled", "dead"),
    ("expired", "dead"),
    ("dead", "dead"),
    ("opposition", "opposed"),
    ("opposed", "opposed"),
    ("renewed", "live"),
    ("registered", "live"),
    ("live", "live"),
    ("published", "pending"),
    ("pending", "pending"),
)


def _first(record: dict[str, Any], *keys: str) -> Any:
    """Read whichever spelling of a field this response happens to use.

    The Open Data Portal has renamed these fields across versions and the same
    record is variously `markLiteralElementText`, `markElementText` and
    `wordMark`. Guessing one and getting a `None` back would render as a mark
    with no name, so all the known spellings are tried and the absence of every
    one of them is treated as a response this provider cannot read.
    """
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


class RegistryLookupProvider(ResearchProvider):
    """USPTO trademark register lookups, returned as `trademark_v1`."""

    name = "registry_lookup"
    supports_citations = True
    supports_async = False

    #: Free. This is the point.
    unit_cost_cents = 0.0

    def price_cents(self, processor: Processor) -> float:
        """Free at any depth. The register does not have processors."""
        return self.unit_cost_cents

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.uspto_api_key
        self.base_url = (base_url or settings.uspto_api_base).rstrip("/")
        self._client = client
        self._healthy: bool | None = None

    # ── client ───────────────────────────────────────────────────────────────
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(settings.uspto_timeout_seconds),
                headers={
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "accept": "application/json",
                    "user-agent": "truestory/0.1 (clearance pipeline)",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        """Unconfigured is unhealthy, deliberately.

        The registry's health check is what selects the fallback, so a provider
        with no key must report down here rather than accept the request and
        return an empty register. An empty register reads exactly like a clean
        one, which is failure B13 in `ProviderOutOfService` and the reason this
        check is not merely a liveness ping.
        """
        if not self.api_key or self.api_key.startswith("PLACEHOLDER"):
            self._healthy = False
            return False
        if self._healthy is not None:
            return self._healthy
        try:
            resp = await self._http().post(
                settings.uspto_search_path,
                json={"query": {"markLiteralElementText": "truestory"}},
                timeout=10.0,
            )
            # A 4xx that is not a rejected key is a healthy API declining a
            # request; only a server fault or a bad credential is a reason to
            # route this run's marks somewhere else.
            self._healthy = resp.status_code < 500 and resp.status_code not in _OUT_OF_SERVICE
        except Exception:
            self._healthy = False
        return self._healthy

    # ── the call ─────────────────────────────────────────────────────────────
    async def investigate(self, request: ResearchRequest) -> Evidence:
        mark = self._field(request.question, "mark")
        if not mark:
            return self._failed(request, "no mark found in the question template")

        territory = self._territory(request)
        if territory not in SUPPORTED_TERRITORIES:
            # Not a research failure and not reported as one. The register this
            # provider can read is the wrong register for this subject.
            return self._failed(request, f"territory {territory} is outside the USPTO register")

        with self._timed() as timing:
            try:
                records = await self._search(mark)
            except (RateLimited, ProviderOutOfService):
                # Both propagate for the same reason they do in parallel_task:
                # an account level fault recorded per subject becomes forty
                # findings that the register is silent.
                raise
            except httpx.TimeoutException:
                return self._failed(request, "timeout awaiting the USPTO register")
            except ProviderError as exc:
                return self._failed(request, str(exc))
            except Exception as exc:
                return self._failed(request, f"unexpected: {type(exc).__name__}: {exc}")

        return self.to_evidence(request, mark, records, timing["latency_ms"])

    async def _search(self, mark: str) -> list[dict[str, Any]]:
        """Exact word mark search against the Open Data Portal."""
        resp = await self._http().post(
            settings.uspto_search_path,
            json={
                "query": {"markLiteralElementText": mark},
                "pagination": {"offset": 0, "limit": 20},
            },
        )

        if resp.status_code == 429:
            raise RateLimited(self.name, float(resp.headers.get("retry-after", 30)))
        if resp.status_code in _OUT_OF_SERVICE:
            raise ProviderOutOfService(self.name, f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise ProviderError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:300]}",
                retryable=resp.status_code >= 500,
            )

        body = resp.json()
        if not isinstance(body, dict):
            raise ProviderError(self.name, "register returned a non object response")

        results = _first(body, "results", "trademarks", "items", "docs") or []
        if not isinstance(results, list):
            raise ProviderError(self.name, "register returned an unreadable results field")
        return [r for r in results if isinstance(r, dict)]

    # ── response mapping ─────────────────────────────────────────────────────
    def to_evidence(
        self,
        request: ResearchRequest,
        mark: str,
        records: list[dict[str, Any]],
        latency_ms: int = 0,
    ) -> Evidence:
        """Map register records onto the registration half of `trademark_v1`.

        A no record answer is a real answer here and it is the one place this
        provider is more trustworthy than research: the custodian of the
        register saying it holds no mark is not the same kind of statement as a
        crawler failing to find one, and it carries the register's own search
        URL as its citation so a reviewer can repeat the search.
        """
        parsed = [p for p in (self._parse_record(r) for r in records) if p]
        live = [p for p in parsed if p["status"] == "live"]

        classes = sorted({c for p in parsed for c in p["nice_classes"]})
        live_classes = sorted({c for p in live for c in p["nice_classes"]})
        production_adjacent = sorted(set(live_classes) & PRODUCTION_ADJACENT_CLASSES)

        # Owner and numbers describe the live registrations. A dead mark's
        # former owner is not who a production negotiates with, and folding the
        # two together is how a cleared mark acquires a claimant.
        primary = live[0] if live else (parsed[0] if parsed else None)

        finding: dict[str, Any] = {
            "mark_of_record": primary["mark"] if primary else None,
            "mark_registered": bool(live),
            "owner": primary["owner"] if primary else None,
            "registration_numbers": [
                p["registration_number"] for p in live if p["registration_number"]
            ],
            "nice_classes": live_classes or classes,
            "territories": ["US"],
            "status": primary["status"] if primary else None,
            # Not part of the schema's required output and not a legal
            # conclusion. It is the triage fact the adjudicator needs and the
            # one the open web never returns cleanly.
            "registry_context": {
                "queried_mark": mark,
                "records_found": len(parsed),
                "live_records": len(live),
                "production_adjacent_classes": production_adjacent,
                "class_overlap_with_production": bool(production_adjacent),
                "use_assessment_pending": True,
                "note": (
                    "Registration facts from the USPTO register. The expressive "
                    "use assessment is not made here and is left to adjudication."
                ),
            },
        }

        if not parsed:
            reasoning = (
                f"The USPTO register returns no record for the word mark {mark!r}. "
                "Searched the register directly rather than the open web."
            )
        else:
            overlap = (
                f"Live classes {live_classes} overlap production adjacent "
                f"classes {production_adjacent}."
                if production_adjacent
                else "No live class overlaps the classes a production operates in."
            )
            reasoning = (
                f"{len(parsed)} record(s) on the USPTO register for {mark!r}, "
                f"{len(live)} live. " + overlap
            )

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=finding,
            citations=self._citations(mark, parsed),
            reasoning=reasoning,
            # A custodian's own record is not a calibrated research answer and
            # does not pretend to be one. It is high because the source is the
            # register, and short of 1.0 because a word mark search does not
            # settle design marks, common law rights, or foreign registrations.
            confidence=0.92 if parsed else 0.85,
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=0.0,
            latency_ms=latency_ms,
        )

    def _parse_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """One register record, or None if this response cannot be read."""
        mark = _first(record, "markLiteralElementText", "markElementText", "wordMark", "mark")
        serial = _first(record, "serialNumber", "applicationNumber", "serial_number")
        if not mark or not serial:
            return None

        raw_status = str(
            _first(
                record,
                "markCurrentStatusExternalDescriptionText",
                "statusDescription",
                "status",
            )
            or ""
        ).lower()
        status = next(
            (mapped for token, mapped in _STATUS_MAP if token in raw_status),
            "unknown",
        )

        registration = str(_first(record, "registrationNumber", "registration_number") or "")

        return {
            "mark": str(mark),
            "serial_number": str(serial),
            "registration_number": registration or None,
            "owner": self._owner(record),
            "status": status,
            "raw_status": raw_status,
            "nice_classes": self._classes(record),
        }

    @staticmethod
    def _owner(record: dict[str, Any]) -> str | None:
        owners = _first(record, "ownerName", "owners", "partyName", "owner")
        if isinstance(owners, str):
            return owners
        if isinstance(owners, list) and owners:
            head = owners[0]
            if isinstance(head, str):
                return head
            if isinstance(head, dict):
                name = _first(head, "partyName", "ownerName", "name")
                return str(name) if name else None
        return None

    @staticmethod
    def _classes(record: dict[str, Any]) -> list[int]:
        """Nice classes as integers, however the response spells them.

        The register returns these as zero padded strings ("041") in some
        shapes and as integers in others, and a mixed list compares wrong
        against `PRODUCTION_ADJACENT_CLASSES` without ever raising.
        """
        raw = _first(record, "internationalClassCode", "classCodes", "niceClasses", "classes") or []
        if isinstance(raw, str | int):
            raw = [raw]
        if not isinstance(raw, list):
            return []

        out: list[int] = []
        for item in raw:
            if isinstance(item, dict):
                item = _first(item, "internationalClassCode", "classCode", "code")
            try:
                out.append(int(str(item).strip()))
            except (TypeError, ValueError):
                continue
        return sorted(set(out))

    def _citations(self, mark: str, parsed: list[dict[str, Any]]) -> list[Citation]:
        """Deep link every record into TSDR, and the search itself when empty.

        TSDR is the public status view and needs no key, so a citation this
        provider emits is a page a reviewer or an underwriter can open. That is
        the difference between this and the scraper it replaces: the citation
        classifies as a registry at trust 0.93 through `Citation.classified`,
        because it is one.
        """
        if not parsed:
            return [
                Citation.classified(
                    url=f"{settings.uspto_search_url}?q={quote_plus(mark)}",
                    title=f"USPTO trademark search: {mark}",
                    excerpt=f"No record on the USPTO register for the word mark {mark!r}.",
                    declared_type="primary",
                    publisher="United States Patent and Trademark Office",
                )
            ]

        citations = [
            Citation.classified(
                url=(
                    f"{settings.uspto_tsdr_url}/#caseNumber={p['serial_number']}"
                    "&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
                ),
                title=f"USPTO TSDR {p['serial_number']}: {p['mark']}",
                excerpt=self._record_excerpt(p),
                declared_type="primary",
                publisher="United States Patent and Trademark Office",
            )
            for p in parsed
        ]
        # Live records first: a reviewer opening the evidence panel should land
        # on a registration that still exists rather than on an abandoned one.
        order = {"live": 0, "pending": 1, "opposed": 2, "unknown": 3, "dead": 4}
        citations.sort(key=lambda c: order.get(_status_of(c.excerpt), 5))
        return citations[:10]

    @staticmethod
    def _record_excerpt(p: dict[str, Any]) -> str:
        parts = [f"{p['mark']} — serial {p['serial_number']}"]
        if p["registration_number"]:
            parts.append(f"registration {p['registration_number']}")
        parts.append(f"status {p['status']}")
        if p["owner"]:
            parts.append(f"owner {p['owner']}")
        if p["nice_classes"]:
            parts.append(f"classes {p['nice_classes']}")
        return ". ".join(parts) + "."

    # ── question parsing ─────────────────────────────────────────────────────
    @staticmethod
    def _field(question: str, name: str) -> str:
        match = _FIELD_PATTERNS[name].search(question or "")
        return match.group(1).strip() if match else ""

    def _territory(self, request: ResearchRequest) -> str:
        """Where the question is asked about, in preference order.

        The question's own TERRITORIES line wins over the run wide jurisdiction
        list, because a script set in London can still carry one American brand
        and the subject is more specific than the project.
        """
        stated = self._field(request.question, "territories") or self._field(
            request.question, "jurisdiction"
        )
        if stated:
            return stated.split(",")[0].strip().upper()
        if request.jurisdictions:
            return request.jurisdictions[0].strip().upper()
        return "US"

    def _failed(self, request: ResearchRequest, why: str) -> Evidence:
        return Evidence.failed(request.subject_id, request.question, self.name, why)


def _status_of(excerpt: str) -> str:
    """The status token this provider wrote into a citation excerpt."""
    match = re.search(r"status (\w+)", excerpt)
    return match.group(1) if match else "unknown"
