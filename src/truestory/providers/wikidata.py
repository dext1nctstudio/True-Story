"""Wikidata as the identity anchor. Free, fast, and incapable of inventing.

Before a claim about a person is researched, one question has to be answered:
does the person exist. The system used to skip it, dispatch research at a named
invention, and attach whatever came back — which is how a screenplay character
called Dr Maya Rowan acquired four government sources and a swimmer's results
page as her evidence.

Wikidata answers that question deterministically. It is a structured knowledge
base with stable identifiers, it is queried without a key, it responds in a few
hundred milliseconds, and — the property that matters most here — it cannot
hallucinate. A name either resolves to an item or it does not.

What it is not is exhaustive. Plenty of real private individuals have no entry,
so absence is a signal rather than a verdict: `NOT_FOUND` sends the subject to
a grounded second opinion in `agents.identity`, and only the two together
conclude that a name is an invention.

    https://www.wikidata.org/w/api.php   (wbsearchentities, wbgetentities)
    https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("truestory.wikidata")

_API = "https://www.wikidata.org/w/api.php"

#: Wikimedia asks for a descriptive agent naming the tool and a contact.
_USER_AGENT = "truestory-clearance/0.1 (https://github.com/dext1nctstudio/True-Story)"

#: Property ids used here. Wikidata is stable on these.
_P_INSTANCE_OF = "P31"
_P_OFFICIAL_SITE = "P856"
_P_DATE_OF_DEATH = "P570"
_P_OCCUPATION = "P106"
_P_COUNTRY_CITIZEN = "P27"

#: Item ids for the "instance of" values that mean this is not a real person.
#: A fictional character has an entry too, and treating that as a real subject
#: would be its own kind of wrong.
_FICTIONAL_CLASSES = {
    "Q95074",  # fictional character
    "Q15632617",  # fictional human
    "Q3658341",  # literary character
    "Q15773347",  # film character
    "Q15773317",  # television character
}

_HUMAN_CLASSES = {"Q5"}  # human


@dataclass(slots=True)
class EntityCandidate:
    """One Wikidata item that a name might denote."""

    qid: str
    label: str
    description: str = ""
    instance_of: list[str] = field(default_factory=list)
    occupations: list[str] = field(default_factory=list)
    official_site: str | None = None
    deceased: bool | None = None
    #: Number of Wikipedia language editions carrying an article. The cheapest
    #: available proxy for prominence, which is what decides whether an audience
    #: would take a character to be this person.
    sitelinks: int = 0

    @property
    def url(self) -> str:
        return f"https://www.wikidata.org/wiki/{self.qid}"

    @property
    def is_human(self) -> bool:
        return bool(_HUMAN_CLASSES & set(self.instance_of))

    @property
    def is_fictional(self) -> bool:
        return bool(_FICTIONAL_CLASSES & set(self.instance_of))

    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "label": self.label,
            "description": self.description,
            "url": self.url,
            "instance_of": self.instance_of,
            "occupations": self.occupations,
            "official_site": self.official_site,
            "deceased": self.deceased,
            "sitelinks": self.sitelinks,
            "is_human": self.is_human,
            "is_fictional": self.is_fictional,
        }


class WikidataClient:
    """Name to structured identity. No key, no spend, no invention."""

    name = "wikidata"

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 12.0) -> None:
        self._client = client
        self._timeout = timeout
        self._cache: dict[str, list[EntityCandidate]] = {}
        self._lock = asyncio.Lock()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"user-agent": _USER_AGENT, "accept": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── the call ─────────────────────────────────────────────────────────────
    async def search(self, name: str, *, limit: int = 7) -> list[EntityCandidate]:
        """Items whose label or alias matches `name`, richest first.

        Returns an empty list on any failure. An identity anchor that takes the
        run down when Wikidata is slow would be a worse failure than the one it
        is here to prevent, and the caller treats empty as "no anchor" rather
        than as "does not exist".
        """
        key = " ".join(name.split()).lower()
        if not key:
            return []
        if key in self._cache:
            return self._cache[key]

        async with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                hits = await self._search_entities(name, limit)
                candidates = await self._hydrate([h["id"] for h in hits]) if hits else []
                by_id = {c.qid: c for c in candidates}
                ordered = [by_id[h["id"]] for h in hits if h["id"] in by_id]
                # Prominence first. An audience assumes the famous holder of a
                # name, not the obscure one, which is the whole basis of a
                # collision finding.
                ordered.sort(key=lambda c: c.sitelinks, reverse=True)
            except Exception as exc:
                log.info("wikidata lookup failed for %r: %s", name, exc)
                ordered = []
            self._cache[key] = ordered
            return ordered

    async def _search_entities(self, name: str, limit: int) -> list[dict[str, Any]]:
        response = await self._http().get(
            _API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "uselang": "en",
                "format": "json",
                "limit": limit,
                "type": "item",
            },
        )
        response.raise_for_status()
        return [h for h in response.json().get("search", []) if h.get("id")]

    async def _hydrate(self, qids: list[str]) -> list[EntityCandidate]:
        response = await self._http().get(
            _API,
            params={
                "action": "wbgetentities",
                "ids": "|".join(qids[:12]),
                "props": "labels|descriptions|claims|sitelinks",
                "languages": "en",
                "format": "json",
            },
        )
        response.raise_for_status()
        entities = response.json().get("entities", {})

        # Label lookups for the referenced items, so "instance of Q5" reads as
        # "human" in the report rather than as an opaque identifier.
        referenced: set[str] = set()
        for entity in entities.values():
            for prop in (_P_INSTANCE_OF, _P_OCCUPATION):
                referenced |= set(_id_values(entity, prop))
        labels = await self._labels(sorted(referenced)[:40]) if referenced else {}

        out: list[EntityCandidate] = []
        for qid, entity in entities.items():
            if "missing" in entity:
                continue
            instance_ids = _id_values(entity, _P_INSTANCE_OF)
            out.append(
                EntityCandidate(
                    qid=qid,
                    label=_first_label(entity),
                    description=(entity.get("descriptions", {}).get("en", {}) or {}).get(
                        "value", ""
                    ),
                    instance_of=instance_ids,
                    occupations=[labels.get(o, o) for o in _id_values(entity, _P_OCCUPATION)[:4]],
                    official_site=_first_string(entity, _P_OFFICIAL_SITE),
                    deceased=bool(entity.get("claims", {}).get(_P_DATE_OF_DEATH)),
                    sitelinks=len(entity.get("sitelinks", {}) or {}),
                )
            )
        return out

    async def _labels(self, qids: list[str]) -> dict[str, str]:
        if not qids:
            return {}
        try:
            response = await self._http().get(
                _API,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(qids),
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                },
            )
            response.raise_for_status()
            return {
                qid: (entity.get("labels", {}).get("en", {}) or {}).get("value", qid)
                for qid, entity in response.json().get("entities", {}).items()
            }
        except Exception:
            return {}


# =============================================================================
# helpers
# =============================================================================


def _first_label(entity: dict[str, Any]) -> str:
    return (entity.get("labels", {}).get("en", {}) or {}).get("value", entity.get("id", ""))


def _id_values(entity: dict[str, Any], prop: str) -> list[str]:
    out: list[str] = []
    for statement in entity.get("claims", {}).get(prop, []) or []:
        value = (
            statement.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(statement, dict)
            else None
        )
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return out


def _first_string(entity: dict[str, Any], prop: str) -> str | None:
    for statement in entity.get("claims", {}).get(prop, []) or []:
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str):
            return value
    return None
