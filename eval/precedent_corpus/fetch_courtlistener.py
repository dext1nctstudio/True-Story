"""Fetch real docket records from CourtListener to check the exposure model's
priors against something other than general knowledge.

WHAT THIS CAN AND CANNOT DO
    CourtListener's search endpoint is public and keyless, and it returns real
    federal docket metadata: case name, court, cause of action, date filed,
    date terminated. That is enough to measure two things honestly --

        * how many suits of a given shape are actually filed against
          productions, by claim type and venue
        * how long they take to resolve, and what fraction resolve at all
          within a study window

    It cannot supply what settled the case or for how much. Disposition detail
    (dismissed with prejudice, settled, jury verdict) lives in docket entries
    and full text, which CourtListener gates behind a free API token, and even
    with one, the dollar figure in a settled case is very often sealed. That
    is the same wall the exposure model's header names: outcomes are public
    to a point, amounts mostly are not.

    So this script does not calibrate the severity table (the dollar ranges).
    Nothing public can. What it can do is give the frequency and outcome_weights
    priors in policy/exposure.yaml a real reference point instead of none, by
    reporting resolution rates and timing pulled from actual dockets rather
    than reasoned from general knowledge.

USAGE
    python eval/precedent_corpus/fetch_courtlistener.py
    python eval/precedent_corpus/fetch_courtlistener.py --out eval/precedent_corpus/dataset.json

Writes one JSON file: every matched docket, deduplicated, with the query that
found it and a retrieval timestamp. Prints the honest summary stats to stdout.

Every record is public federal court data, but this script's own selection is
not a random sample of anything -- it is whatever a handful of search terms
happen to surface. The summary below says so, and so should anyone who cites
it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

API = "https://www.courtlistener.com/api/rest/v4/search/"

#: Search terms chosen to surface disputes over depicting real people, real
#: events, or real IP in a film or television production -- the shape of
#: subject this whole product clears. Each is a separate query because the
#: search API scores relevance per query and mixing unrelated concepts in one
#: string dilutes results toward whichever term is more common in the corpus.
QUERIES: dict[str, str] = {
    "claim_negative_living": '"based on a true story" defamation film',
    "publicity_rights": "right of publicity motion picture depiction",
    "anti_slapp_production": '"anti-SLAPP" defamation production company',
    "visual_copyright": "copyright infringement motion picture artwork",
    "trademark_expressive_use": "trademark infringement film Rogers test",
    "life_rights_dispute": "life story rights breach television series",
}

#: Federal civil litigation resolves in months to a few years. A docket still
#: open after this long is fairly counted as "not yet resolved" rather than
#: folded into a resolution rate that would understate how long these run.
STUDY_WINDOW_DAYS = 365 * 4


def _fetch_query(label: str, query: str, *, pages: int = 2) -> list[dict[str, Any]]:
    """Page through search results for one query. Public endpoint, no key."""
    results: list[dict[str, Any]] = []
    url = f"{API}?type=r&order_by=score+desc&q={urllib.parse.quote(query)}"

    for _ in range(pages):
        if not url:
            break
        req = urllib.request.Request(
            url, headers={"User-Agent": "truestory-precedent-research/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.load(resp)
        except urllib.error.URLError as exc:
            print(f"  ! {label}: fetch failed ({exc}), keeping what was collected", file=sys.stderr)
            break

        for row in body.get("results", []):
            row["_query_label"] = label
            row["_query"] = query
            results.append(row)

        url = body.get("next") or ""
        time.sleep(1.0)  # a public, keyless endpoint. Be a good citizen of it.

    return results


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per docket, keeping the first query that found it.

    The same suit surfaces under more than one query -- a defamation-over-a-
    biopic case is relevant to both "based on a true story" and "right of
    publicity" searches -- and counting it twice would inflate the filing
    volume for whichever shape happens to have overlapping terms.
    """
    seen: dict[int, dict[str, Any]] = {}
    for row in records:
        docket_id = row.get("docket_id")
        if docket_id is None or docket_id in seen:
            continue
        seen[docket_id] = row
    return list(seen.values())


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The honest statistics: resolution rate and timing. Nothing about cost."""
    today = datetime.now(UTC).date()
    by_query: Counter[str] = Counter()
    by_court: Counter[str] = Counter()
    resolved_days: list[int] = []
    unresolved = 0
    too_recent_to_judge = 0

    for row in records:
        by_query[row["_query_label"]] += 1
        by_court[row.get("court_citation_string") or row.get("court") or "unknown"] += 1

        filed = _parse_date(row.get("dateFiled"))
        terminated = _parse_date(row.get("dateTerminated"))

        if terminated and filed:
            resolved_days.append((terminated - filed).days)
        elif filed:
            age_days = (today - filed).days
            if age_days > STUDY_WINDOW_DAYS:
                unresolved += 1
            else:
                too_recent_to_judge += 1

    resolved_days.sort()
    n = len(resolved_days)
    median_days = resolved_days[n // 2] if n else None

    return {
        "total_dockets": len(records),
        "by_query": dict(by_query.most_common()),
        "by_court": dict(by_court.most_common(15)),
        "resolved_within_window": n,
        "median_days_to_resolution": median_days,
        "still_open_past_4_years": unresolved,
        "too_recent_to_classify": too_recent_to_judge,
        "resolution_rate_of_classifiable": (
            round(n / (n + unresolved), 3) if (n + unresolved) else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "dataset.json"),
        help="where to write the collected dataset",
    )
    parser.add_argument("--pages", type=int, default=2, help="result pages per query")
    args = parser.parse_args()

    all_records: list[dict[str, Any]] = []
    print("Fetching from CourtListener (public, keyless, real federal dockets)...")
    for label, query in QUERIES.items():
        print(f"  {label}: {query!r}")
        rows = _fetch_query(label, query, pages=args.pages)
        print(f"    -> {len(rows)} results")
        all_records.extend(rows)

    deduped = _dedupe(all_records)
    summary = _summarise(deduped)

    out = {
        "source": "https://www.courtlistener.com/api/rest/v4/search/",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "queries": QUERIES,
        "note": (
            "Not a random sample. This is whatever the queries above surfaced, "
            "and is biased toward however CourtListener's relevance ranking "
            "scores these terms. Disposition detail and dollar amounts are not "
            "in this dataset -- see the module docstring for why."
        ),
        "summary": summary,
        "records": [
            {
                "docket_id": r.get("docket_id"),
                "case_name": r.get("caseName"),
                "court": r.get("court_citation_string") or r.get("court"),
                "cause": r.get("cause"),
                "date_filed": r.get("dateFiled"),
                "date_terminated": r.get("dateTerminated"),
                "docket_number": r.get("docketNumber"),
                "url": (
                    f"https://www.courtlistener.com{r['docket_absolute_url']}"
                    if r.get("docket_absolute_url")
                    else None
                ),
                "matched_query": r["_query_label"],
            }
            for r in deduped
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nWrote {len(deduped)} deduplicated dockets to {out_path}")
    print("\n--- summary ---")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
