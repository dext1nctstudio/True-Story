"""The thirteen domain tools.

Agents never see Parallel. They see verbs from the clearance trade:
`verify_factual_claim`, `check_music_rights`, `check_person_collision`. That
choice buys three things at once.

  * Vendor swappability. A tool named `parallel_task_run` couples the agent to
    a vendor. A tool named `verify_factual_claim` couples it to the problem,
    and the second one survives a vendor change.
  * Better tool selection. A model picks the right tool far more reliably when
    the name states the purpose rather than the transport.
  * A test seam. Every tool is a pure function of its arguments plus the
    registry, so the whole surface is exercisable against fixtures.

Each tool assembles its question from a fixed template. The templates are the
reason two runs of the same script produce identical cache keys, and they are
where the domain knowledge actually lives: what a clearance researcher would
think to ask, written down once.
"""

from __future__ import annotations

from typing import Any

from truestory.models.enums import Processor, RiskTier
from truestory.policy import load_routing, load_schema
from truestory.providers import ProviderRegistry, ResearchRequest

# =============================================================================
# question templates
# =============================================================================
# Deliberately verbose. A research API answers a precise question well and a
# vague one badly, and the difference between the two is worth more than any
# amount of downstream parsing.

_Q_CLAIM = (
    "Verify this factual claim about a real person or event against the public record.\n\n"
    "SUBJECT: {subject}\n"
    "CLAIM: {claim}\n"
    "JURISDICTIONS IN SCOPE: {jurisdictions}\n\n"
    "Determine whether the public record supports the claim exactly as stated, "
    "contradicts it, or is silent. Treat these as three distinct outcomes and do "
    "not treat silence as contradiction. Where the claim is time bounded, verify "
    "it for the period stated rather than for the subject's whole life. Prefer "
    "primary sources: registers, dockets, contemporaneous reporting, official "
    "records. Also establish whether the subject is living and whether they are a "
    "public figure, a limited purpose public figure, or a private individual."
)

_Q_QUOTE = (
    "Establish the provenance of this quotation.\n\n"
    "QUOTE: {quote}\n"
    "PURPORTED SPEAKER: {speaker}\n"
    "ERA: {era}\n\n"
    "Find the earliest documented source in which this speaker is recorded saying "
    "this, and give the wording of record, which is frequently not the wording in "
    "circulation. Determine whether the quotation is commonly misattributed and, "
    "if so, who actually said it. Assess how far the submitted wording sits from "
    "the documented wording."
)

_Q_COLLISION = (
    "Identify real people who could be confused with a fictional character.\n\n"
    "CHARACTER NAME: {name}\n"
    "CHARACTER PROFESSION: {profession}\n"
    "STORY LOCALE: {city}\n"
    "JURISDICTIONS: {jurisdictions}\n\n"
    "Find real, identifiable people bearing this name, and say for each whether "
    "they share the profession and the locale of the character. The combination "
    "of name plus profession plus locale is what turns a coincidence into a "
    "claim. Note prominence, since a well known person is more likely to be "
    "assumed to be the subject."
)

_Q_IDENTIFIABILITY = (
    "Determine whether an unnamed character is identifiable as a real person.\n\n"
    "ATTRIBUTE CLUSTER: {attributes}\n"
    "JURISDICTIONS: {jurisdictions}\n\n"
    "The character is not named. Establish whether this combination of attributes "
    "resolves to one or a small number of real, locatable people, and say which "
    "attributes did the narrowing. Report how much effort identification took, "
    "because trivial identification is the dangerous answer: if it took one query "
    "here, an audience will do it too."
)

_Q_ENTITY_REGISTRATION = (
    "Enumerate registered entities matching a name.\n\n"
    "NAME: {name}\n"
    "JURISDICTION: {jurisdiction}\n"
    "CLASSES OR SECTORS: {classes}\n\n"
    "List every registered business, company or organisation bearing this name in "
    "the jurisdiction, with the registry record for each."
)

_Q_TRADEMARK = (
    "Assess the trademark position for an on screen use.\n\n"
    "MARK: {mark}\n"
    "GOODS OR SERVICES CLASSES: {classes}\n"
    "TERRITORIES: {territories}\n"
    "HOW IT APPEARS ON SCREEN: {depiction}\n\n"
    "Establish the registration position and the owner. Then assess the use "
    "itself: whether it is artistically relevant to the work, whether it could be "
    "read as explicitly misleading about sponsorship or endorsement, and whether "
    "the depiction is unflattering enough to attract a disparagement or trade "
    "libel theory. Note whether this owner is known to pursue production uses."
)

_Q_MUSIC = (
    "Identify both sets of rights in a music cue.\n\n"
    "TITLE: {title}\n"
    "ARTIST: {artist}\n"
    "YEAR: {year}\n"
    "TERRITORIES: {territories}\n\n"
    "A cue carries two separate rights held by different parties: the composition, "
    "licensed as a synchronisation right, and the master recording, licensed as a "
    "master use right. Identify the holder and the licensing contact for each. "
    "Establish public domain status per territory rather than in general. Where "
    "known, give the typical licence term, since a term that expires quietly after "
    "delivery is how a show ends up in syndication with substituted music."
)

_Q_PUBLICITY = (
    "Establish the right of publicity position for a depicted person.\n\n"
    "PERSON: {person}\n"
    "DOMICILE: {domicile}\n\n"
    "Determine whether the person is living. If deceased, establish the year of "
    "death and the state or country of domicile at death, since post mortem "
    "publicity rights are governed by the law of the domicile and the term varies "
    "enormously between jurisdictions. Identify the estate representative where "
    "one exists, and note any history of the person or their estate litigating "
    "over portrayal."
)

_Q_VISUAL = (
    "Identify the rights position in a visual element appearing on screen.\n\n"
    "DESCRIPTION: {description}\n"
    "CREATOR HINT: {creator_hint}\n"
    "HOW IT APPEARS: {appearance}\n\n"
    "Determine whether this maps to an identifiable existing work, who created it, "
    "and who holds the rights, which for a tattoo is frequently neither the person "
    "wearing it nor the production. Establish copyright status and, if it has "
    "entered the public domain, the year. Assess prominence and recognisability on "
    "screen, but do not treat brief background appearance as settled fair use: "
    "courts have declined the de minimis defence on background artwork visible for "
    "seconds."
)

_Q_PUBLIC_DOMAIN = (
    "Establish the copyright position of underlying source material.\n\n"
    "WORK: {work}\n"
    "JURISDICTION: {jurisdiction}\n\n"
    "Determine publication year and country, copyright status per territory, and "
    "the rule producing the term. Identify every derivative layer separately, "
    "since translations, illustrations, annotations and later editions each carry "
    "their own term and their own holder, and a missed layer is a classic chain of "
    "title defect. For works of the renewal era, check whether renewal occurred."
)

_Q_ENTITY = (
    "Assess a real location or organisation appearing in a screenplay.\n\n"
    "NAME: {name}\n"
    "KIND: {kind}\n"
    "JURISDICTION: {jurisdiction}\n"
    "HOW IT IS DEPICTED: {depiction}\n\n"
    "Establish whether the entity exists and still operates. Assess whether the "
    "depiction is neutral or unflattering, and whether it associates the real "
    "place with criminal or discreditable conduct, which is the most common source "
    "of complaint from a current occupant."
)

_Q_INTERROGATE = (
    "Find sources bearing on a specific question a clearance reviewer has asked "
    "while reading one line of a screenplay.\n\n"
    "QUESTION: {question}\n"
    "SUBJECT: {subject}\n"
    "JURISDICTIONS: {jurisdictions}\n\n"
    "Return the passages that bear on the question directly, preferring records, "
    "registers, dockets and contemporaneous reporting over summaries of them. Do "
    "not resolve the question: return what the sources say and let the reviewer "
    "read them."
)

# The routing table asks for enumeration in three distinct situations, and they
# are three different questions against three different populations. Stating the
# entity type and the criteria is not optional courtesy to the API: FindAll
# requires both, and a namesake search that asks for "entities" gets companies.
_ENUMERATION_KINDS: dict[str, dict[str, Any]] = {
    # A real person is depicted. Who else bears this name, and could a reader
    # take the depiction to be about one of them?
    "findall_similar_persons": {
        "entity_type": "people",
        "schema": "person_collision_v1",
        "objective": (
            "Find real, identifiable people publicly known by the name {pattern}, "
            "who could be mistaken for the person of that name depicted in a film. "
            "Jurisdiction of interest: {jurisdiction}."
        ),
        "conditions": (
            ("bears_the_name", "The person is publicly known by the name {pattern}."),
            (
                "publicly_identifiable",
                "The person is identifiable from public sources, with a documented "
                "occupation, affiliation or public record. Exclude passing mentions.",
            ),
        ),
    },
    # The Baby Reindeer rule. The character was never named, and it did not help.
    "findall_matching_persons": {
        "entity_type": "people",
        "schema": "identifiability_v1",
        "objective": (
            "Find real people who match this cluster of attributes closely enough "
            "that an audience could identify them as its subject: {pattern}. "
            "Jurisdiction of interest: {jurisdiction}."
        ),
        "conditions": (
            (
                "matches_the_cluster",
                "The person matches the described combination of role, place, period "
                "and relationship: {pattern}.",
            ),
            (
                "identifiable_without_a_name",
                "The match rests on attributes an audience could search, not on a "
                "name, since no name is given.",
            ),
        ),
    },
    # Marks and business names. A register, not a reputation.
    "findall_registered_entities": {
        "entity_type": "companies",
        "schema": "person_collision_v1",
        "objective": (
            "Find registered businesses, trading names and registered trade marks "
            "using the name {pattern}, in {jurisdiction} and in any territory whose "
            "register reaches it."
        ),
        "conditions": (
            ("uses_the_name", "The entity trades under, or holds a mark for, {pattern}."),
            (
                "on_a_register",
                "The entity appears on a companies register, a trade mark register or "
                "an equivalent official record, rather than only in press coverage.",
            ),
        ),
    },
}


# =============================================================================
# tool implementations
# =============================================================================


class ClearanceTools:
    """The domain tool surface, bound to one registry and one project context."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        jurisdictions: tuple[str, ...] = ("US",),
        truth_claim_framing: bool = False,
    ) -> None:
        self.registry = registry
        self.jurisdictions = jurisdictions
        self.truth_claim_framing = truth_claim_framing
        self.routing = load_routing()
        # Identity notes, keyed by subject id, set by the swarm before dispatch.
        # A question that names the entity it means is a different question from
        # one that names a string, and the difference showed up as a cricket
        # tournament being researched as a building code body.
        self._identities: dict[str, str] = {}

    # ── identity ─────────────────────────────────────────────────────────────
    def set_identity(self, subject_id: str, note: str) -> None:
        """Pin what this subject is, so the research asks about that thing."""
        if note:
            self._identities[subject_id] = note

    def _identity_block(self, subject_id: str) -> str:
        note = self._identities.get(subject_id)
        return f"{note}\n\n" if note else ""

    # ── plumbing ─────────────────────────────────────────────────────────────
    async def _run(
        self,
        subject_id: str,
        question: str,
        schema_name: str,
        subject: dict[str, Any],
        *,
        context: str = "",
        max_results: int = 10,
    ) -> dict[str, Any]:
        """Route, dispatch, and return a serialised Evidence envelope."""
        decision = self.routing.match(subject)
        decision = self.routing.apply_project_escalations(
            decision, subject, {"truth_claim_framing": self.truth_claim_framing}
        )

        request = ResearchRequest(
            subject_id=subject_id,
            # The identity is part of the question, not metadata beside it:
            # asking about a different entity is asking a different question,
            # and the cache key is right to treat it as one.
            question=self._identity_block(subject_id) + question,
            output_schema=load_schema(decision.schema_name or schema_name),
            schema_name=decision.schema_name or schema_name,
            tier=decision.tier,
            processor=decision.processor or Processor.LITE,
            jurisdictions=self.jurisdictions,
            context=context,
            max_results=max_results,
        )

        evidence = await self.registry.investigate(decision, request)
        payload = evidence.to_dict()
        payload["routing"] = {
            "rule": decision.rule_id,
            "tier": str(decision.tier),
            "escalated_by": list(decision.escalated_by),
        }
        return payload

    # ── claims ───────────────────────────────────────────────────────────────
    async def verify_factual_claim(
        self,
        subject_id: str,
        subject: str,
        claim: str,
        *,
        polarity: str = "neutral",
        subject_alive: bool | None = None,
        jurisdiction: str | None = None,
    ) -> dict[str, Any]:
        """Check one atomic factual claim about a real person or event.

        The workhorse. A negative claim about a living person routes to the
        deepest processor and cannot leave the pipeline green without a human
        agreeing, because that is the exact shape of every case in the
        Litigation Set.
        """
        return await self._run(
            subject_id=subject_id,
            question=_Q_CLAIM.format(
                subject=subject,
                claim=claim,
                jurisdictions=jurisdiction or ", ".join(self.jurisdictions),
            ),
            schema_name="claim_verification_v1",
            subject={
                "kind": "claim",
                "polarity": polarity,
                "subject_alive": subject_alive,
            },
        )

    async def attribute_quote(
        self, subject_id: str, quote: str, purported_speaker: str, era: str = "unknown"
    ) -> dict[str, Any]:
        """Find the earliest documented source for a quotation."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_QUOTE.format(quote=quote, speaker=purported_speaker, era=era),
            schema_name="quote_attribution_v1",
            subject={"kind": "claim", "type": "QUOTE"},
        )

    # ── persons ──────────────────────────────────────────────────────────────
    async def check_person_collision(
        self,
        subject_id: str,
        name: str,
        profession: str = "unknown",
        city: str = "unknown",
        *,
        occurrence_count: int = 1,
    ) -> dict[str, Any]:
        """Find real people who share a fictional character's name and context."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_COLLISION.format(
                name=name,
                profession=profession,
                city=city,
                jurisdictions=", ".join(self.jurisdictions),
            ),
            schema_name="person_collision_v1",
            subject={
                "type": "PERSON_NAME_FICTIONAL",
                "occurrence_count": occurrence_count,
            },
        )

    async def check_person_identifiability(
        self, subject_id: str, attributes: list[str]
    ) -> dict[str, Any]:
        """The Baby Reindeer tool. Does this attribute cluster resolve to a real person."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_IDENTIFIABILITY.format(
                attributes="; ".join(attributes),
                jurisdictions=", ".join(self.jurisdictions),
            ),
            schema_name="identifiability_v1",
            subject={"type": "REAL_PERSON_IDENTIFIABLE"},
            max_results=25,
        )

    async def check_publicity_rights(
        self, subject_id: str, person: str, domicile: str = "unknown"
    ) -> dict[str, Any]:
        """Living or deceased, domicile at death, and whether the term has run."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_PUBLICITY.format(person=person, domicile=domicile),
            schema_name="real_person_v2",
            subject={"type": "REAL_PERSON_DEPICTED"},
        )

    # ── marks and entities ───────────────────────────────────────────────────
    async def check_entity_registration(
        self, subject_id: str, name: str, jurisdiction: str, classes: str = "any"
    ) -> dict[str, Any]:
        """Enumerate every registered entity bearing a name in a jurisdiction."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_ENTITY_REGISTRATION.format(
                name=name, jurisdiction=jurisdiction, classes=classes
            ),
            schema_name="trademark_v1",
            subject={"type": "BUSINESS_NAME"},
            max_results=50,
        )

    async def check_trademark_status(
        self,
        subject_id: str,
        mark: str,
        classes: str = "any",
        territories: str = "US",
        depiction: str = "neutral background use",
    ) -> dict[str, Any]:
        """Registration position plus an assessment of the use itself."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_TRADEMARK.format(
                mark=mark, classes=classes, territories=territories, depiction=depiction
            ),
            schema_name="trademark_v1",
            subject={"type": "TRADEMARK_LOGO"},
        )

    async def check_entity(
        self,
        subject_id: str,
        name: str,
        kind: str = "venue",
        jurisdiction: str = "US",
        depiction: str = "neutral",
    ) -> dict[str, Any]:
        """Locations and organisations. The cheapest tier and the largest volume."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_ENTITY.format(
                name=name, kind=kind, jurisdiction=jurisdiction, depiction=depiction
            ),
            schema_name="entity_v1",
            subject={"type": "REAL_LOCATION"},
        )

    # ── rights ───────────────────────────────────────────────────────────────
    async def check_music_rights(
        self, subject_id: str, title: str, artist: str = "unknown", year: str = "unknown"
    ) -> dict[str, Any]:
        """Both rights in a cue, plus the term that drives the monitor cadence."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_MUSIC.format(
                title=title,
                artist=artist,
                year=year,
                territories=", ".join(self.jurisdictions),
            ),
            schema_name="music_rights_v1",
            subject={"type": "MUSIC_CUE"},
        )

    async def check_visual_copyright(
        self,
        subject_id: str,
        description: str,
        creator_hint: str = "unknown",
        appearance: str = "visible in background",
    ) -> dict[str, Any]:
        """Artwork, tattoos, posters and clips. A CRITICAL path for good reason."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_VISUAL.format(
                description=description, creator_hint=creator_hint, appearance=appearance
            ),
            schema_name="visual_copyright_v1",
            subject={"type": "ARTWORK_VISUAL"},
        )

    async def check_public_domain(
        self, subject_id: str, work: str, jurisdiction: str = "US"
    ) -> dict[str, Any]:
        """Underlying source material and every derivative layer on top of it."""
        return await self._run(
            subject_id=subject_id,
            question=_Q_PUBLIC_DOMAIN.format(work=work, jurisdiction=jurisdiction),
            schema_name="public_domain_v1",
            subject={"type": "SOURCE_MATERIAL"},
        )

    # ── enumeration and capture ──────────────────────────────────────────────
    async def enumerate_matching_entities(
        self,
        subject_id: str,
        pattern: str,
        jurisdiction: str = "US",
        kind: str = "findall_registered_entities",
    ) -> list[dict[str, Any]]:
        """Set valued research. One Evidence per matched entity.

        `kind` is the routing table's side effect name. The three are different
        questions against different populations, and collapsing them into one
        query was asking the crawler to find companies when the subject was a
        person. FindAll needs the entity type and the criteria stated, so they
        are stated here rather than left to the model.
        """
        spec = _ENUMERATION_KINDS.get(kind, _ENUMERATION_KINDS["findall_registered_entities"])
        provider = self.registry.get("parallel_findall")
        request = ResearchRequest(
            subject_id=subject_id,
            question=spec["objective"].format(pattern=pattern, jurisdiction=jurisdiction),
            output_schema=load_schema(spec["schema"]),
            schema_name=spec["schema"],
            tier=RiskTier.HIGH,
            processor=Processor.BASE,
            jurisdictions=(jurisdiction,),
            max_results=50,
            entity_type=spec["entity_type"],
            match_conditions=tuple(
                (name, description.format(pattern=pattern, jurisdiction=jurisdiction))
                for name, description in spec["conditions"]
            ),
        )
        results = await provider.enumerate(request)  # type: ignore[attr-defined]
        return [e.to_dict() for e in results]

    async def interrogate(
        self,
        subject_id: str,
        question: str,
        *,
        subject: str = "",
        max_results: int = 8,
    ) -> dict[str, Any]:
        """Answer one ad hoc question about a subject, now, with sources.

        The verification path is a multi hop research run against a schema, and
        it is the right shape for two hundred subjects and the wrong shape for
        the question a reviewer asks while looking at one line: "who else says
        this", "what is the source for the 1931 date", "is there anything more
        recent". That question wants a single round trip and excerpts, which is
        exactly what Search is for, at a tenth of a cent.

        The answer is deliberately capped at low confidence in the provider and
        never enters adjudication. It is a lead, not a finding, and the panel
        that shows it says so.
        """
        provider = self.registry.get("parallel_search")
        objective = _Q_INTERROGATE.format(
            question=question.strip(),
            subject=subject or "not stated",
            jurisdictions=", ".join(self.jurisdictions),
        )
        request = ResearchRequest(
            subject_id=subject_id,
            question=objective,
            output_schema={},
            schema_name="interrogation_v1",
            tier=RiskTier.LOW,
            processor=Processor.LITE,
            jurisdictions=self.jurisdictions,
            max_results=max_results,
            # The literal queries the API also wants, kept short: the objective
            # carries the framing, these carry the terms.
            search_queries=tuple(q for q in (question.strip(), subject.strip()) if q)[:2],
        )
        evidence = await provider.investigate(request)
        payload = evidence.to_dict()
        payload["interrogation"] = True
        return payload

    async def capture_evidence_page(self, subject_id: str, url: str) -> dict[str, Any]:
        """Preserve a registry, docket or archive page into the evidence pack.

        A finding that cites a page which later changes is worth much less at
        claim time than one that cites a page the production captured on the
        day it was read.
        """
        provider = self.registry.get("parallel_extract")
        request = ResearchRequest(
            subject_id=subject_id,
            question=url,
            output_schema={},
            schema_name="evidence_page_v1",
            tier=RiskTier.LOW,
            processor=Processor.LITE,
            context=url,
        )
        evidence = await provider.investigate(request)
        return evidence.to_dict()

    async def watch_subject(
        self,
        subject_id: str,
        query: str,
        cadence: str = "monthly",
        reason: str = "",
    ) -> dict[str, Any]:
        """Open a Living Clearance watch that outlives this run."""
        provider = self.registry.get("parallel_monitor")
        if hasattr(provider, "watch"):
            handle = await provider.watch(  # type: ignore[attr-defined]
                subject_id=subject_id, query=query, cadence=cadence, reason=reason
            )
            return handle.to_dict()

        request = ResearchRequest(
            subject_id=subject_id,
            question=query,
            output_schema={},
            schema_name="monitor_handle_v1",
            tier=RiskTier.LOW,
            processor=Processor.LITE,
            context=cadence,
        )
        evidence = await provider.investigate(request)
        return evidence.to_dict()


#: Tool name to method, used by the MCP server to build its manifest.
TOOL_MANIFEST: dict[str, str] = {
    "verify_factual_claim": "Verify one atomic factual claim about a real person or event against the public record.",
    "attribute_quote": "Find the earliest documented source for a quotation attributed to a real person.",
    "check_person_collision": "Find real people who share a fictional character's name, profession and locale.",
    "check_person_identifiability": "Determine whether an unnamed character's attribute cluster resolves to a real person.",
    "check_entity_registration": "Enumerate registered businesses or organisations bearing a name in a jurisdiction.",
    "check_trademark_status": "Assess registration and expressive use position for a mark appearing on screen.",
    "check_entity": "Assess a real location or organisation depicted in the script.",
    "check_music_rights": "Identify composition and master rights holders, territories and licence term for a cue.",
    "check_publicity_rights": "Establish living status, domicile at death and post mortem publicity term for a depicted person.",
    "check_visual_copyright": "Identify rights in artwork, tattoos, posters or clips visible on screen.",
    "check_public_domain": "Establish copyright status of underlying source material and every derivative layer.",
    "enumerate_matching_entities": "Set valued enumeration returning one evidence record per matched entity.",
    "capture_evidence_page": "Capture a registry or docket page verbatim into the evidence pack.",
    "watch_subject": "Open a recurring Living Clearance watch on a subject.",
}
