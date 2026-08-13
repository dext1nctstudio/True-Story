"""The vocabulary of the system.

Every string in this module is a term of art borrowed from the clearance trade
or from defamation law. Changing one changes the routing table, the report, and
the rubric at the same time, so they live here alone and are imported
everywhere else.
"""

from __future__ import annotations

from enum import StrEnum


class ElementType(StrEnum):
    """The clearance taxonomy.

    Assembled from the standard vendor breakdown, plus two additions specific
    to adapted reality productions and two on the roadmap for AI provenance.
    """

    # ── conventional clearance ───────────────────────────────────────────────
    PERSON_NAME_FICTIONAL = "PERSON_NAME_FICTIONAL"
    BUSINESS_NAME = "BUSINESS_NAME"
    BRAND_PRODUCT = "BRAND_PRODUCT"
    TRADEMARK_LOGO = "TRADEMARK_LOGO"
    ORGANIZATION = "ORGANIZATION"
    REAL_LOCATION = "REAL_LOCATION"
    PHONE_NUMBER = "PHONE_NUMBER"
    STREET_ADDRESS = "STREET_ADDRESS"
    URL_HANDLE = "URL_HANDLE"
    VEHICLE_PLATE = "VEHICLE_PLATE"
    MUSIC_CUE = "MUSIC_CUE"
    ARTWORK_VISUAL = "ARTWORK_VISUAL"
    TATTOO = "TATTOO"
    PRINT_QUOTE = "PRINT_QUOTE"
    FILM_CLIP = "FILM_CLIP"
    REAL_EVENT = "REAL_EVENT"
    DEFAMATORY_REF = "DEFAMATORY_REF"
    TRADE_LIBEL = "TRADE_LIBEL"
    SOURCE_MATERIAL = "SOURCE_MATERIAL"

    # ── adapted reality core ─────────────────────────────────────────────────
    REAL_PERSON_DEPICTED = "REAL_PERSON_DEPICTED"

    # Composite detector. Fires on an attribute cluster with no name present:
    # profession plus city plus physical description plus relationship. It
    # exists because the Baby Reindeer character was never named and that did
    # not help. Identifiability, not naming, is the legal trigger.
    REAL_PERSON_IDENTIFIABLE = "REAL_PERSON_IDENTIFIABLE"

    # ── project level ────────────────────────────────────────────────────────
    # One boolean that changes the risk tier of every person adjacent subject
    # in the script. Two federal courts treated the "true story" framing itself
    # as evidence bearing on reckless disregard.
    TRUTH_CLAIM_FRAMING = "TRUTH_CLAIM_FRAMING"

    # ── roadmap, AI provenance layer ─────────────────────────────────────────
    AI_GENERATED_ASSET = "AI_GENERATED_ASSET"
    DIGITAL_REPLICA = "DIGITAL_REPLICA"


#: Types whose risk tier is escalated when the project asserts a true story.
PERSON_ADJACENT: frozenset[ElementType] = frozenset(
    {
        ElementType.REAL_PERSON_DEPICTED,
        ElementType.REAL_PERSON_IDENTIFIABLE,
        ElementType.PERSON_NAME_FICTIONAL,
        ElementType.REAL_EVENT,
        ElementType.DEFAMATORY_REF,
        ElementType.TRADE_LIBEL,
    }
)

#: Types that carry factual claims and therefore route through ClaimExtractor.
CLAIM_BEARING: frozenset[ElementType] = frozenset(
    {
        ElementType.REAL_PERSON_DEPICTED,
        ElementType.REAL_PERSON_IDENTIFIABLE,
        ElementType.REAL_EVENT,
    }
)

#: Types resolved by deterministic rules with no research spend at all.
DETERMINISTIC_ONLY: frozenset[ElementType] = frozenset(
    {
        ElementType.PHONE_NUMBER,
        ElementType.VEHICLE_PLATE,
        ElementType.URL_HANDLE,
    }
)


class ClaimType(StrEnum):
    """What kind of assertion a claim makes.

    CHARACTERIZATION is the important one. Defamation law protects opinion, so
    a characterization resolves to an OPINION verdict, renders grey, and spends
    nothing. Domain knowledge acting as a classifier and as a budget control at
    the same time.
    """

    CONDUCT = "CONDUCT"
    STATUS = "STATUS"
    ACHIEVEMENT = "ACHIEVEMENT"
    QUOTE = "QUOTE"
    RELATIONSHIP = "RELATIONSHIP"
    EVENT_FACT = "EVENT_FACT"
    CHARACTERIZATION = "CHARACTERIZATION"


class Polarity(StrEnum):
    """Reputational valence of a claim about a person.

    `NEGATIVE` plus a living subject is the escalation cocktail: those route to
    the core processor and to mandatory counsel review if they do not verify.
    """

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Verdict(StrEnum):
    """The five outcomes of verifying a factual claim.

    The distinction between UNSUPPORTED and CONTRADICTED is load bearing.
    UNSUPPORTED is not FALSE. Collapsing the two would be exactly the careless
    assertion about a real person that this system exists to prevent, so the
    UI language and the report language preserve it everywhere.
    """

    VERIFIED = "VERIFIED"  # supported by the record            -> green
    UNSUPPORTED = "UNSUPPORTED"  # no record either way          -> amber
    CONTRADICTED = "CONTRADICTED"  # record shows otherwise      -> red
    UNVERIFIABLE = "UNVERIFIABLE"  # private fact, no public record -> amber, counsel
    OPINION = "OPINION"  # not a factual assertion             -> grey, no research


class ClearanceStatus(StrEnum):
    """The outcome of clearing a non claim element.

    CLEAR_WITH_CONDITIONS is not a hedge. It is the correct answer for First
    Amendment protected expressive use, which is why the defence side cases in
    the Litigation Set matter as much as the plaintiff side ones. A system that
    flags everything is useless.
    """

    CLEAR = "CLEAR"
    CLEAR_WITH_CONDITIONS = "CLEAR_WITH_CONDITIONS"
    NOT_CLEAR = "NOT_CLEAR"
    NEEDS_LICENSE = "NEEDS_LICENSE"
    NEEDS_COUNSEL = "NEEDS_COUNSEL"
    PENDING = "PENDING"
    RESEARCH_FAILED = "RESEARCH_FAILED"


class RiskTier(StrEnum):
    """Routing tier. Drives processor selection and budget reservation."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _TIER_RANK[self]

    def escalate(self, steps: int = 1) -> RiskTier:
        """Move up the ladder, saturating at CRITICAL.

        This implements the truth claim framing rule from routing.yaml. One
        method call standing in for a legal doctrine two federal courts applied.
        """
        target = min(self.rank + steps, _TIER_RANK[RiskTier.CRITICAL])
        return _RANK_TIER[target]

    def degrade(self, steps: int = 1) -> RiskTier:
        """Move down the ladder, flooring at NONE. Used by BudgetGovernor."""
        target = max(self.rank - steps, 0)
        return _RANK_TIER[target]


_TIER_RANK: dict[RiskTier, int] = {
    RiskTier.NONE: 0,
    RiskTier.LOW: 1,
    RiskTier.MEDIUM: 2,
    RiskTier.HIGH: 3,
    RiskTier.CRITICAL: 4,
}
_RANK_TIER: dict[int, RiskTier] = {v: k for k, v in _TIER_RANK.items()}


class Processor(StrEnum):
    """Parallel Task processor depth. Cost and thoroughness rise together."""

    LITE = "lite"
    BASE = "base"
    CORE = "core"
    PRO = "pro"
    ULTRA = "ultra"

    @property
    def usd_per_run(self) -> float:
        """Published list price per run.

        Re verify against docs.parallel.ai before finalising routing. Several
        of these figures date to the Task API launch post.
        """
        return _PROCESSOR_PRICE[self]

    def cheaper(self) -> Processor | None:
        order = [Processor.ULTRA, Processor.PRO, Processor.CORE, Processor.BASE, Processor.LITE]
        idx = order.index(self)
        return order[idx + 1] if idx + 1 < len(order) else None


_PROCESSOR_PRICE: dict[Processor, float] = {
    Processor.LITE: 0.005,
    Processor.BASE: 0.010,
    Processor.CORE: 0.025,
    Processor.PRO: 0.100,
    Processor.ULTRA: 0.300,
}


class Modality(StrEnum):
    """Where a span was found. Dialogue and action carry different legal risk."""

    SCRIPT_DIALOGUE = "script_dialogue"
    SCRIPT_ACTION = "script_action"
    SCRIPT_HEADING = "script_heading"
    SCRIPT_PARENTHETICAL = "script_parenthetical"
    TITLE_CARD = "title_card"
    STORYBOARD_STILL = "storyboard_still"


class PublicFigureStatus(StrEnum):
    """Drives the actual malice standard and the masking policy."""

    PUBLIC = "public"
    LIMITED_PURPOSE = "limited_purpose"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class Role(StrEnum):
    """Custom IAM roles. Each maps to a Firestore security rule and a UI shape."""

    COUNSEL = "truestory.counsel"
    PRODUCER = "truestory.producer"
    WRITER = "truestory.writer"
    UNDERWRITER = "truestory.underwriter"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    INGESTING = "INGESTING"
    EXTRACTING_CLAIMS = "EXTRACTING_CLAIMS"
    BUILDING_LEDGER = "BUILDING_LEDGER"
    ROUTING = "ROUTING"
    RESEARCHING = "RESEARCHING"
    ADJUDICATING = "ADJUDICATING"
    REMEDIATING = "REMEDIATING"
    REPORTING = "REPORTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


#: Verdict to overlay colour. The UI imports this rather than inventing its own.
VERDICT_COLOR: dict[Verdict, str] = {
    Verdict.VERIFIED: "green",
    Verdict.UNSUPPORTED: "amber",
    Verdict.CONTRADICTED: "red",
    Verdict.UNVERIFIABLE: "amber",
    Verdict.OPINION: "grey",
}
