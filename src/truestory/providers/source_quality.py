"""Source pedigree. What a citation is actually worth.

Until this module existed, `Citation.source_type` was whatever the caller put
there, and the caller put "secondary" because that is the default in
`_citations_from_basis`. Parallel's Basis citations carry a URL and excerpts
and nothing else, so every citation in a live run arrived typed "secondary".

Two things broke as a direct result:

  * `contradicted_requires_primary_source` in the rubric could never be
    satisfied, so every CONTRADICTED verdict was silently downgraded to
    UNSUPPORTED. The product's headline output — the red line — was
    unreachable in live mode.
  * A Wikipedia paragraph and a federal docket counted the same, so the
    confidence attached to a verdict said nothing about the record behind it.

So classification happens here, from the URL, against a curated table. The
rules are deliberately conservative and stated once:

  known host  -> the table decides, in both directions. A courtlistener docket
                 declared "secondary" is promoted; a Wikipedia page declared
                 "primary" is demoted. A researcher's opinion of its own
                 source does not outrank the registry it came from.
  unknown host-> the declared type stands, and `verified` is False so the
                 adjudicator can tell the difference between a source we
                 classified and one we merely accepted.

Independence uses the registrable domain (eTLD+1), because three URLs on one
site are one source wearing three hats, and "corroborated by three sources" is
the single most common way a research pipeline lies to its user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

# =============================================================================
# the tables
# =============================================================================
# Membership is by registrable domain or by suffix. Keep entries lowercase and
# without a leading dot; `_host_matches` handles subdomains.

#: Courts, dockets, legislatures, regulators, registries. The record itself.
PRIMARY_SUFFIXES: tuple[str, ...] = (
    ".gov",
    ".mil",
    ".gov.uk",
    ".gov.au",
    ".gov.ca",
    ".gc.ca",
    ".gov.in",
    ".gov.ie",
    ".gov.nz",
    ".gov.za",
    ".gouv.fr",
    ".govt.nz",
    ".europa.eu",
    ".int",
)

PRIMARY_DOMAINS: frozenset[str] = frozenset(
    {
        # courts and dockets
        "courtlistener.com",
        "pacer.gov",
        "supremecourt.gov",
        "uscourts.gov",
        "law.justia.com",
        "casetext.com",
        "canlii.org",
        "bailii.org",
        "austlii.edu.au",
        "judiciary.uk",
        "find-case-law.service.gov.uk",
        "curia.europa.eu",
        "hudoc.echr.coe.int",
        # intellectual property registries
        "uspto.gov",
        "tsdr.uspto.gov",
        "copyright.gov",
        "publicrecords.copyright.gov",
        "wipo.int",
        "euipo.europa.eu",
        "ipo.gov.uk",
        "ipaustralia.gov.au",
        # corporate registries
        "sec.gov",
        "companieshouse.gov.uk",
        "find-and-update.company-information.service.gov.uk",
        "bizfileonline.sos.ca.gov",
        "beta.companieshouse.gov.uk",
        "e-justice.europa.eu",
        # statute, register, archive
        "govinfo.gov",
        "federalregister.gov",
        "ecfr.gov",
        "congress.gov",
        "legislation.gov.uk",
        "loc.gov",
        "archives.gov",
        "nationalarchives.gov.uk",
        "catalog.archives.gov",
        # vital records, contemporaneous archives
        "chroniclingamerica.loc.gov",
        "trove.nla.gov.au",
        "britishnewspaperarchive.co.uk",
        "newspapers.com",
        "timesmachine.nytimes.com",
        "archive.org",
        # music and rights registries
        "iswcnet.cisac.org",
        "repertoire.bmi.com",
        "ascap.com",
        "prsformusic.com",
        "sesac.com",
        "musicbrainz.org",
        "isrc.ifpi.org",
        # scholarly records of record
        "doi.org",
        "pubmed.ncbi.nlm.nih.gov",
        # Statistical registers. For a sporting or box office fact the record of
        # record is the scorecard, not a docket, and treating those as merely
        # "secondary" made a correctly contradicted claim get downgraded for
        # want of a court document that could never exist for it.
        "espncricinfo.com",
        "icc-cricket.com",
        "cricketarchive.com",
        "olympics.com",
        "olympedia.org",
        "fifa.com",
        "uefa.com",
        "fiba.basketball",
        "formula1.com",
        "baseball-reference.com",
        "basketball-reference.com",
        "pro-football-reference.com",
        "boxofficemojo.com",
        "the-numbers.com",
        "afi.com",
        "catalog.afi.com",
        "oscars.org",
        "bafta.org",
        "grammy.com",
    }
)

#: Reporting about a record. Useful, corroborative, never the record.
NEWS_DOMAINS: frozenset[str] = frozenset(
    {
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "nytimes.com",
        "washingtonpost.com",
        "wsj.com",
        "ft.com",
        "theguardian.com",
        "thetimes.co.uk",
        "telegraph.co.uk",
        "independent.co.uk",
        "latimes.com",
        "chicagotribune.com",
        "bostonglobe.com",
        "npr.org",
        "pbs.org",
        "cnn.com",
        "nbcnews.com",
        "cbsnews.com",
        "abcnews.go.com",
        "aljazeera.com",
        "economist.com",
        "newyorker.com",
        "theatlantic.com",
        "propublica.org",
        "politico.com",
        "axios.com",
        "bloomberg.com",
        "forbes.com",
        "time.com",
        "usatoday.com",
        "sfgate.com",
        "nypost.com",
        "smh.com.au",
        "theage.com.au",
        "thehindu.com",
        "indianexpress.com",
        "scmp.com",
        # A clearance product for "based on a true story" work is not a product
        # for American stories. Leaving these out classified most of the record
        # for an India set script as "unrecognised host", which understated
        # every corroboration score on the run and is simply wrong: these are
        # national newspapers and wire services.
        "hindustantimes.com",
        "indiatoday.in",
        "ndtv.com",
        "livemint.com",
        "business-standard.com",
        "thequint.com",
        "theprint.in",
        "outlookindia.com",
        "deccanherald.com",
        "telegraphindia.com",
        "tribuneindia.com",
        "firstpost.com",
        "news18.com",
        "aninews.in",
        "ptinews.com",
        "dawn.com",
        "thedailystar.net",
        "straitstimes.com",
        "japantimes.co.jp",
        "abc.net.au",
        "cbc.ca",
        "rte.ie",
        "irishtimes.com",
        "lemonde.fr",
        "spiegel.de",
        "elpais.com",
        "afp.com",
        "dw.com",
        "france24.com",
        "cnbc.com",
        "cricbuzz.com",
        "sport.sky.com",
        "skysports.com",
    }
)

#: Trade press. Authoritative on the industry, secondary on the facts.
TRADE_DOMAINS: frozenset[str] = frozenset(
    {
        "variety.com",
        "hollywoodreporter.com",
        "deadline.com",
        "billboard.com",
        "indiewire.com",
        "thewrap.com",
        "screendaily.com",
        "backstage.com",
        "musicbusinessworldwide.com",
        "law360.com",
        "abajournal.com",
        "reuters.com",
    }
)

#: Encyclopedias, aggregators and databases. A starting point, never a finish.
TERTIARY_DOMAINS: frozenset[str] = frozenset(
    {
        "wikipedia.org",
        "wikimedia.org",
        "wikidata.org",
        "wiktionary.org",
        "britannica.com",
        "imdb.com",
        "fandom.com",
        "wikia.com",
        "biography.com",
        "findagrave.com",
        "ancestry.com",
        "geni.com",
        "everipedia.org",
        "dbpedia.org",
        "allmusic.com",
        "discogs.com",
        "genius.com",
        "rottentomatoes.com",
        "metacritic.com",
        "letterboxd.com",
        "opencorporates.com",
        "crunchbase.com",
        "zoominfo.com",
    }
)

#: User generated, algorithmically generated, or otherwise unattributable.
#: Never sufficient on its own, and never the basis of a CONTRADICTED verdict.
LOW_TRUST_DOMAINS: frozenset[str] = frozenset(
    {
        "reddit.com",
        "quora.com",
        "medium.com",
        "substack.com",
        "blogspot.com",
        "wordpress.com",
        "tumblr.com",
        "x.com",
        "twitter.com",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "threads.net",
        "youtube.com",
        "pinterest.com",
        "answers.com",
        "ranker.com",
        "celebritynetworth.com",
        "biographyscoop.com",
        "wikitree.com",
        "ask.com",
        "ehow.com",
        "buzzfeed.com",
        "dailymail.co.uk",
        "thesun.co.uk",
        "mirror.co.uk",
        "tmz.com",
        "radaronline.com",
        "pagesix.com",
        "distractify.com",
        "screenrant.com",
        "cheatsheet.com",
        "nickiswift.com",
        "looper.com",
        "grunge.com",
        # Machine generated encyclopedias and Wikipedia mirrors. These read as
        # reference works and are not one: they restate, unattributed, whatever
        # they were trained on, so a claim resting on them rests on nothing
        # that can be checked. Parallel returned grokipedia.com as the basis
        # for a cricket scoreline during testing.
        "grokipedia.com",
        "dbpedia.org",
        "wikiwand.com",
        "alchetron.com",
        "everipedia.org",
        "prabook.com",
        "peoplepill.com",
        "famousbirthdays.com",
        "wikibio.in",
        "biographypedia.org",
    }
)

#: Multi part public suffixes we care about, longest first. Not the full PSL:
#: this list only has to be right for the domains a clearance run actually
#: touches, and a wrong answer degrades to "treat as its own source", which is
#: the conservative direction.
_MULTI_SUFFIXES: tuple[str, ...] = (
    "gov.uk",
    "co.uk",
    "org.uk",
    "ac.uk",
    "me.uk",
    "net.uk",
    "sch.uk",
    "nhs.uk",
    "police.uk",
    "gov.au",
    "com.au",
    "net.au",
    "org.au",
    "edu.au",
    "gov.nz",
    "co.nz",
    "org.nz",
    "gov.in",
    "co.in",
    "net.in",
    "org.in",
    "gov.za",
    "co.za",
    "gov.br",
    "com.br",
    "gov.sg",
    "com.sg",
    "co.jp",
    "or.jp",
    "ne.jp",
    "go.jp",
    "com.mx",
    "gob.mx",
    "com.hk",
    "com.tr",
    "com.cn",
    "gov.cn",
    "co.kr",
    "go.kr",
)


class SourceClass:
    """What kind of thing the host is. Wider than `source_type`, and reported."""

    OFFICIAL = "official"  # government, court, statute, regulator
    REGISTRY = "registry"  # trademark, corporate, rights registry
    ARCHIVE = "archive"  # contemporaneous document, scanned record
    NEWS = "news"  # reporting of record
    TRADE = "trade"  # industry press
    REFERENCE = "reference"  # encyclopedia, database, aggregator
    USER = "user"  # forum, social, self published
    UNKNOWN = "unknown"


#: source class -> (source_type, trust). Trust is used to weight corroboration
#: and to cap confidence; it is not shown to the user as a number.
_CLASS_PROFILE: dict[str, tuple[str, float]] = {
    SourceClass.OFFICIAL: ("primary", 0.97),
    SourceClass.REGISTRY: ("primary", 0.93),
    SourceClass.ARCHIVE: ("primary", 0.88),
    SourceClass.NEWS: ("secondary", 0.74),
    SourceClass.TRADE: ("secondary", 0.68),
    SourceClass.REFERENCE: ("tertiary", 0.42),
    SourceClass.USER: ("tertiary", 0.15),
    SourceClass.UNKNOWN: ("secondary", 0.50),
}

_ARCHIVE_DOMAINS: frozenset[str] = frozenset(
    {
        "archive.org",
        "newspapers.com",
        "britishnewspaperarchive.co.uk",
        "timesmachine.nytimes.com",
        "trove.nla.gov.au",
        "chroniclingamerica.loc.gov",
    }
)

#: Databases that are the record of record inside one domain of fact. A cricket
#: scorecard, an Olympic result and a title's release data are not "reporting":
#: they are the register, and treating them as secondary meant a correctly
#: contradicted sporting claim was downgraded for want of a court document that
#: could not exist for it.
STATISTICAL_REGISTERS: frozenset[str] = frozenset(
    {
        "espncricinfo.com",
        "icc-cricket.com",
        "cricketarchive.com",
        "olympics.com",
        "olympedia.org",
        "fifa.com",
        "uefa.com",
        "fiba.basketball",
        "formula1.com",
        "baseball-reference.com",
        "basketball-reference.com",
        "pro-football-reference.com",
        "boxofficemojo.com",
        "the-numbers.com",
        "catalog.afi.com",
        "afi.com",
        "oscars.org",
        "bafta.org",
        "grammy.com",
        # National governing bodies publishing their own records.
        "bcci.tv",
        "ecb.co.uk",
        "cricketaustralia.com.au",
    }
)

_REGISTRY_DOMAINS: frozenset[str] = frozenset(
    {
        "uspto.gov",
        "tsdr.uspto.gov",
        "copyright.gov",
        "publicrecords.copyright.gov",
        "wipo.int",
        "euipo.europa.eu",
        "ipo.gov.uk",
        "ipaustralia.gov.au",
        "companieshouse.gov.uk",
        "find-and-update.company-information.service.gov.uk",
        "iswcnet.cisac.org",
        "repertoire.bmi.com",
        "ascap.com",
        "prsformusic.com",
        "sesac.com",
        "musicbrainz.org",
        "isrc.ifpi.org",
        "sec.gov",
    }
)


@dataclass(frozen=True, slots=True)
class SourceAssessment:
    """One citation, classified."""

    host: str
    domain: str  # registrable domain, the unit of independence
    source_class: str
    source_type: str  # primary | secondary | tertiary
    trust: float  # 0..1
    verified: bool  # False means the host was not in any table

    @property
    def is_primary(self) -> bool:
        return self.source_type == "primary"

    @property
    def is_low_trust(self) -> bool:
        return self.source_class == SourceClass.USER


# =============================================================================
# url handling
# =============================================================================

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def host_of(url: str) -> str:
    """Bare hostname, lowercased, `www.` stripped. Empty when unparseable."""
    if not url:
        return ""
    candidate = url.strip()
    if "//" not in candidate:
        candidate = f"https://{candidate}"
    try:
        host = (urlsplit(candidate).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def registrable_domain(url_or_host: str) -> str:
    """eTLD+1, the unit that decides whether two citations are independent.

    Three pages on one newspaper are one source. Getting this wrong is how a
    pipeline reports "corroborated across three sources" about a single blog.
    """
    host = url_or_host if "." in url_or_host and "/" not in url_or_host else host_of(url_or_host)
    if not host or _IP_RE.match(host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    for suffix in _MULTI_SUFFIXES:
        if host.endswith(f".{suffix}"):
            head = host[: -len(suffix) - 1].split(".")
            return f"{head[-1]}.{suffix}" if head else host
    return ".".join(parts[-2:])


def _host_matches(host: str, domains: frozenset[str]) -> bool:
    """True when the host is, or sits under, one of `domains`."""
    if not host:
        return False
    if host in domains or registrable_domain(host) in domains:
        return True
    return any(host.endswith(f".{d}") for d in domains)


# =============================================================================
# classification
# =============================================================================


def classify_host(host: str) -> tuple[str, bool]:
    """Return (source_class, verified). `verified` is False for unknown hosts."""
    if not host:
        return SourceClass.UNKNOWN, False

    # Order matters: an archive on a .gov host is still an archive, and a
    # registry on a .gov host is still a registry, because the two carry
    # different weight from a plain government page.
    if _host_matches(host, _ARCHIVE_DOMAINS):
        return SourceClass.ARCHIVE, True
    if _host_matches(host, _REGISTRY_DOMAINS) or _host_matches(host, STATISTICAL_REGISTERS):
        return SourceClass.REGISTRY, True
    if _host_matches(host, LOW_TRUST_DOMAINS):
        return SourceClass.USER, True
    if _host_matches(host, TERTIARY_DOMAINS):
        return SourceClass.REFERENCE, True
    if _host_matches(host, PRIMARY_DOMAINS) or host.endswith(PRIMARY_SUFFIXES):
        return SourceClass.OFFICIAL, True
    if _host_matches(host, TRADE_DOMAINS):
        return SourceClass.TRADE, True
    if _host_matches(host, NEWS_DOMAINS):
        return SourceClass.NEWS, True
    return SourceClass.UNKNOWN, False


def assess(url: str, declared: str | None = None) -> SourceAssessment:
    """Classify one citation URL.

    A known host overrides whatever the researcher declared, in both
    directions. An unknown host keeps the declared value and is marked
    unverified, so a downstream rule can require a classified primary source
    rather than an asserted one.
    """
    host = host_of(url)
    domain = registrable_domain(host)
    source_class, verified = classify_host(host)
    source_type, trust = _CLASS_PROFILE[source_class]

    if not verified:
        declared_clean = (declared or "").strip().lower()
        if declared_clean in {"primary", "secondary", "tertiary"}:
            source_type = declared_clean
            # An unclassifiable host asserting itself a primary record is worth
            # a little more than nothing and a lot less than a docket.
            trust = {"primary": 0.55, "secondary": 0.45, "tertiary": 0.3}[declared_clean]

    return SourceAssessment(
        host=host,
        domain=domain,
        source_class=source_class,
        source_type=source_type,
        trust=trust,
        verified=verified,
    )


def independent_domains(urls: list[str]) -> set[str]:
    """The distinct registrable domains behind a set of citations."""
    return {d for d in (registrable_domain(u) for u in urls if u) if d}


def staleness_days(published_at: datetime | None, accessed_at: datetime | None) -> int | None:
    """How old the source is, in days, preferring publication over retrieval."""
    stamp = published_at or accessed_at
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - stamp).days)
