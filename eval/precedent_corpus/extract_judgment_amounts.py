"""Real damages figures, read out of published court opinions.

    python eval/precedent_corpus/extract_judgment_amounts.py
    python eval/precedent_corpus/extract_judgment_amounts.py --per-category 40

WHY THIS EXISTS
    `policy/exposure.yaml` prices the `adverse_judgment` outcome at
    $100,000-$5,000,000 in indemnity, and that range was written from general
    knowledge rather than measured. It is the largest invented number in the
    product.

    The standing objection to fixing it was that settlements are confidential,
    which is true and is not the whole picture. A settlement is private; a
    *judgment* is a public document, and when a court affirms or enters one it
    usually says the figure in the opinion text. That is a real, citable
    number, and it is exactly the number `adverse_judgment` is supposed to
    describe.

WHAT IT DOES
    For each clearance category this product actually routes on, searches
    CourtListener's opinion corpus, pulls the full text of each candidate,
    keeps only the passages where a dollar figure sits near damages language,
    and asks Gemini to read that passage and report what the figure actually
    was: the amount, whether it was compensatory, punitive or statutory, and
    critically whether the opinion *affirmed* it or reversed, vacated or
    remitted it.

    That last field is the one that makes the dataset worth having. A headline
    verdict that an appellate court threw out is not exposure, and a corpus
    that counted it would overstate every category it appeared in.

WHAT IT CANNOT DO, AND SAYS SO IN ITS OWN OUTPUT
    This is a survivorship-biased sample by construction. Cases that settle --
    the overwhelming majority -- never produce an opinion with a number in it,
    so nothing here describes the typical outcome. It describes the tail: what
    happens in the rare matter that goes all the way to a judgment somebody
    then wrote about.

    So it calibrates `adverse_judgment` and nothing else. The `settled` and
    `dismissed_early` severity rows stay exactly as uncertain as they were,
    and the outcome *weights* between the three are a separate question this
    does not touch.

    Requires COURTLISTENER_API_TOKEN. Opinion text is behind it; search is not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from truestory.config import settings  # noqa: E402
from truestory.providers import model_fallback  # noqa: E402

SEARCH_API = "https://www.courtlistener.com/api/rest/v4/search/"
OPINION_API = "https://www.courtlistener.com/api/rest/v4/opinions/{opinion_id}/"
USER_AGENT = "true-story-judgment-extraction/1.0"
DEFAULT_OUT = Path(__file__).with_name("judgment_amounts.json")

#: One query per severity bucket the exposure model actually prices. The
#: wording is deliberately about the *dispute*, not about the industry: a
#: right of publicity judgment against an advertiser is the same shape of
#: exposure as one against a production, and restricting to film language
#: shrinks an already thin sample to nothing.
CATEGORIES: dict[str, str] = {
    "defamation_person": "defamation damages awarded jury verdict television film portrayal",
    "right_of_publicity": "right of publicity misappropriation likeness damages awarded",
    "copyright_visual": "copyright infringement statutory damages awarded photograph artwork film",
    "trademark_use": "trademark infringement damages awarded motion picture television",
}

#: A dollar figure this close to damages language is worth a model read. Wider
#: than it looks: opinions routinely put the number a sentence or two away from
#: the word that gives it meaning.
_MONEY = re.compile(r"\$\s?[\d,]{4,}(?:\.\d{2})?(?:\s*(?:million|billion))?", re.I)
_DAMAGES_CONTEXT = re.compile(
    r"\b(damages?|award(?:ed|s)?|judgment|verdict|jury|compensatory|punitive|statutory)\b",
    re.I,
)

#: What the model is asked to return. Every field is something a reader could
#: check against the quoted passage, which is the same standard
#: verified_cases.yaml already holds its records to.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["figures", "reliable", "production_context", "context_note"],
    "properties": {
        "reliable": {
            "type": "boolean",
            "description": (
                "False when the passage does not actually state a damages figure "
                "this court awarded, affirmed or reviewed -- for example a "
                "settlement mentioned in passing, a jurisdictional threshold, a "
                "contract price, or a figure from an unrelated matter."
            ),
        },
        "production_context": {
            "type": "boolean",
            "description": (
                "True only when the defendant's use was expressive or editorial "
                "-- a film, television programme, book, article, documentary or "
                "similar work depicting a person, event, mark or work. False for "
                "counterfeiting, piracy, ordinary commercial competition, "
                "advertising, or a business to business dispute. A counterfeiter's "
                "judgment says nothing about what a production risks by showing a "
                "brand on a coffee cup."
            ),
        },
        "context_note": {
            "type": "string",
            "description": "One line: who the defendant was and what the use actually was.",
        },
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["amount_usd", "kind", "disposition", "quote"],
                "properties": {
                    "amount_usd": {"type": "number"},
                    "kind": {
                        "type": "string",
                        "enum": ["compensatory", "punitive", "statutory", "combined", "unclear"],
                    },
                    "disposition": {
                        "type": "string",
                        "enum": ["affirmed", "entered", "reversed", "vacated", "remitted", "unclear"],
                        "description": (
                            "What this opinion did with the figure. reversed, "
                            "vacated and remitted all mean the number did not "
                            "survive as stated."
                        ),
                    },
                    "quote": {
                        "type": "string",
                        "description": "Verbatim sentence from the passage stating the figure.",
                    },
                },
            },
        },
    },
}

_PROMPT = """You are reading a passage from a published court opinion.

Report only damages figures this opinion actually states were awarded, entered,
affirmed, reversed, vacated or remitted. Ignore any dollar amount that is not a
damages figure in this case: settlement amounts mentioned in passing, amounts in
controversy, contract sums, attorney fee figures, and figures from other cases
cited as authority.

For each figure, quote verbatim the sentence that states it. If the passage
contains no damages figure for this case, set reliable to false and return an
empty list. A wrong number here is worse than no number.

PASSAGE (around the figure):
{passage}

HOW THIS OPINION ENDS (its disposition -- affirmed, reversed, vacated, remanded):
{conclusion}

Also decide whether this was an expressive or editorial use -- a film, show,
book, article or documentary depicting something -- or instead counterfeiting,
piracy, ordinary commercial competition or advertising. Only the first kind
tells us anything about what a production risks. A nine million dollar
counterfeiting judgment is a real number about a different activity.

The passage will often be procedural history describing what a *trial* court or
jury did. The disposition field must describe what THIS opinion did with that
figure, which is what the ending above tells you. A jury award recited in the
history of an opinion that then reverses is `reversed`, not `entered`.
"""


#: CourtListener is a free public service run by a non profit. A 429 is it
#: asking to be left alone, so the answer is to wait rather than to retry
#: immediately and be told again.
_MIN_INTERVAL = 1.2
_last_request = 0.0


def _get(url: str, token: str, *, attempts: int = 4) -> dict[str, Any] | None:
    global _last_request

    for attempt in range(attempts):
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)

        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Authorization": f"Token {token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                _last_request = time.monotonic()
                return json.load(response)
        except urllib.error.HTTPError as exc:
            _last_request = time.monotonic()
            if exc.code == 429:
                backoff = 5 * (attempt + 1)
                print(f"    rate limited, waiting {backoff}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            print(f"    ! fetch failed: {exc}", file=sys.stderr)
            return None
        except urllib.error.URLError as exc:
            _last_request = time.monotonic()
            print(f"    ! fetch failed: {exc}", file=sys.stderr)
            return None
        except (TimeoutError, OSError) as exc:
            # A read that times out mid body arrives as a bare socket error
            # rather than a URLError, and killed a whole run before this.
            # Worth one retry: it is a slow response, not a refusal.
            _last_request = time.monotonic()
            print(f"    ! read timed out: {exc}", file=sys.stderr)
            if attempt + 1 >= attempts:
                return None
            time.sleep(3)
            continue

    print("    ! gave up after repeated rate limiting", file=sys.stderr)
    return None


def _strip_html(raw: str) -> str:
    return re.sub(r"<[^>]+>", " ", raw)


def _opinion_text(opinion_id: int, token: str) -> str:
    body = _get(OPINION_API.format(opinion_id=opinion_id), token)
    if not body:
        return ""
    for field in ("plain_text", "html_with_citations", "html", "html_lawbox", "xml_harvard"):
        value = body.get(field)
        if value:
            return _strip_html(value) if field != "plain_text" else value
    return ""


def _passages(text: str, window: int = 1200, limit: int = 3) -> list[str]:
    """Excerpts around dollar figures that sit near damages language.

    Sending a whole opinion would cost more and read worse: the model is being
    asked to attribute one number to one holding, and eighty thousand
    characters of procedural history is not evidence for that.
    """
    out: list[str] = []
    for match in _MONEY.finditer(text):
        start = max(0, match.start() - window // 2)
        chunk = text[start : match.end() + window // 2]
        if not _DAMAGES_CONTEXT.search(chunk):
            continue
        if any(chunk[:200] in seen for seen in out):
            continue
        out.append(" ".join(chunk.split()))
        if len(out) >= limit:
            break
    return out


async def _read_passage(client: Any, passage: str, conclusion: str) -> dict[str, Any] | None:
    from google.genai import types

    try:
        response = await model_fallback.generate(
            client,
            settings.model_attribution,
            contents=_PROMPT.format(passage=passage[:9000], conclusion=conclusion[:3000]),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0.0,
            ),
        )
    except Exception as exc:
        print(f"    ! model call failed: {exc}", file=sys.stderr)
        return None

    raw = getattr(response, "text", "") or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=20, help="candidate opinions per category")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    token = settings.courtlistener_api_token
    if not token or token.startswith("PLACEHOLDER"):
        print("COURTLISTENER_API_TOKEN is required: opinion text sits behind it.", file=sys.stderr)
        return 2

    from google import genai

    client = genai.Client(
        vertexai=settings.use_vertex,
        project=settings.gcp_project or None,
        location=settings.gcp_location,
    )

    records: list[dict[str, Any]] = []
    # (case, amount, kind). The same award recited in a district opinion and
    # again in the appeal is one data point, not two.
    seen_figures: set[tuple[str, int, Any]] = set()
    for category, query in CATEGORIES.items():
        print(f"\n{category}: {query!r}")
        url = f"{SEARCH_API}?type=o&order_by=score+desc&q={urllib.parse.quote(query)}"
        body = _get(url, token)
        results = (body or {}).get("results", [])[: args.per_category]
        print(f"  {len(results)} candidate opinions")

        for row in results:
            opinions = row.get("opinions") or []
            if not opinions:
                continue
            text = _opinion_text(opinions[0]["id"], token)
            time.sleep(0.4)  # a shared public service; do not hammer it
            if not text:
                continue
            passages = _passages(text)
            if not passages:
                continue

            # The last stretch of an opinion is where "we affirm" or "we
            # reverse" lives, and disposition cannot be read without it.
            conclusion = " ".join(text[-4000:].split())

            for passage in passages:
                read = await _read_passage(client, passage, conclusion)
                if not read or not read.get("reliable"):
                    continue
                in_context = bool(read.get("production_context"))
                for figure in read.get("figures") or []:
                    fingerprint = (
                        (row.get("caseName") or "").strip().lower(),
                        round(float(figure.get("amount_usd") or 0)),
                        figure.get("kind"),
                    )
                    if fingerprint in seen_figures:
                        continue
                    seen_figures.add(fingerprint)
                    records.append(
                        {
                            "category": category,
                            "production_context": in_context,
                            "context_note": read.get("context_note", ""),
                            "case_name": row.get("caseName"),
                            "court": row.get("court_citation_string") or row.get("court"),
                            "date_filed": row.get("dateFiled"),
                            "citation": (row.get("citation") or [None])[0],
                            "opinion_url": (
                                f"https://www.courtlistener.com{row['absolute_url']}"
                                if row.get("absolute_url")
                                else None
                            ),
                            **figure,
                        }
                    )
            print(f"    {row.get('caseName', '?')[:60]}: {len(records)} figures so far")

    # Only figures that survived the appeal are exposure. Everything else is
    # recorded so a reader can see what was excluded and why.
    # Two filters, and the second matters as much as the first. A judgment that
    # was reversed is not exposure, and a judgment against a counterfeiter is
    # not exposure *for a production* -- it is a real number about a different
    # activity, which is more misleading than an invented one because it
    # arrives with a citation attached.
    survived = [
        r
        for r in records
        if r["disposition"] in ("affirmed", "entered") and r["production_context"]
    ]
    by_category: dict[str, list[float]] = {}
    for row in survived:
        by_category.setdefault(row["category"], []).append(float(row["amount_usd"]))

    summary: dict[str, Any] = {"categories": {}}
    for category, amounts in by_category.items():
        amounts.sort()
        summary["categories"][category] = {
            "n": len(amounts),
            "min_usd": amounts[0],
            "median_usd": amounts[len(amounts) // 2],
            "max_usd": amounts[-1],
        }

    out = {
        "source": "CourtListener opinion corpus, full text read under COURTLISTENER_API_TOKEN",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "queries": CATEGORIES,
        "caveat": (
            "Published judgments only. Cases that settle produce no opinion and "
            "no figure, and they are the overwhelming majority, so this is the "
            "litigated tail rather than a typical outcome. Calibrates the "
            "adverse_judgment severity row in policy/exposure.yaml and nothing "
            "else: the settled and dismissed_early rows, and the weights "
            "between all three, are not evidenced here."
        ),
        "figures_found": len(records),
        "figures_kept": len(survived),
        "excluded_reversed": sum(
            1 for r in records if r["disposition"] not in ("affirmed", "entered")
        ),
        "excluded_not_production_context": sum(
            1
            for r in records
            if r["disposition"] in ("affirmed", "entered") and not r["production_context"]
        ),
        "summary": summary,
        "records": records,
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nwrote {len(records)} figures ({len(survived)} survived) to {args.out}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
