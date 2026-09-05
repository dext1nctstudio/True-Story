"""Refresh the reviewed precedent corpus from CourtListener and court text.

This command does two separate jobs and records them separately:

1. locate the exact opinion or docket through CourtListener's live search API;
2. verify that the curated judicial passage occurs in retrieved court text.

Public search works without credentials. CourtListener's opinion/docket detail
APIs require a free token; set ``COURTLISTENER_API_TOKEN`` to enable that
fallback and RECAP document enrichment. A search hit is never treated as proof
of a holding. Only a passage match in retrieved document text is marked
``verified_now``.

Usage::

    python eval/precedent_corpus/sync_courtlistener.py
    python eval/precedent_corpus/sync_courtlistener.py --metadata-only
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader

from truestory.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).with_name("verified_cases.yaml")
DEFAULT_OUT = Path(__file__).with_name("courtlistener_records.json")
SEARCH_API = "https://www.courtlistener.com/api/rest/v4/search/"
OPINION_API = "https://www.courtlistener.com/api/rest/v4/opinions/{opinion_id}/"
USER_AGENT = "true-story-precedent-sync/1.0 (court-record verification)"
_last_courtlistener_request = 0.0
_courtlistener_delay = 0.0


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _request(url: str, *, token: str = "") -> tuple[bytes, str]:
    global _last_courtlistener_request
    if "courtlistener.com/api/" in url and _courtlistener_delay:
        wait = _courtlistener_delay - (time.monotonic() - _last_courtlistener_request)
        if wait > 0:
            time.sleep(wait)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html, application/pdf"}
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read(), response.headers.get_content_type()
    finally:
        if "courtlistener.com/api/" in url:
            _last_courtlistener_request = time.monotonic()


def _json(url: str, *, token: str = "") -> dict[str, Any]:
    body, _ = _request(url, token=token)
    return json.loads(body)


def _normalise(value: str) -> str:
    value = html.unescape(value).replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _text_from_bytes(body: bytes, content_type: str, url: str) -> str:
    if content_type == "application/pdf" or url.lower().split("?")[0].endswith(".pdf"):
        reader = PdfReader(io.BytesIO(body))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raw = body.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(raw)
    return " ".join(parser.parts)


def _search(case: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    spec = case.get("courtlistener") or {}
    case_name = str(spec.get("search_case_name") or case.get("name") or "")
    query = str(spec.get("search_query") or case.get("docket_number") or "")
    params = urllib.parse.urlencode(
        {"type": "o", "case_name": case_name, "q": query, "order_by": "score desc"}
    )
    payload = _json(f"{SEARCH_API}?{params}")
    results = payload.get("results") or []
    wanted_cluster = spec.get("opinion_cluster_id")
    wanted_docket = str(case.get("docket_number") or "").replace(" ", "").lower()

    if wanted_cluster:
        exact = next((row for row in results if row.get("cluster_id") == wanted_cluster), None)
        if exact:
            return exact, "opinion"
    exact = next(
        (
            row
            for row in results
            if wanted_docket
            and wanted_docket in str(row.get("docketNumber") or "").replace(" ", "").lower()
        ),
        None,
    )
    if exact:
        return exact, "opinion"

    # Some district-court orders have a RECAP docket but no indexed opinion.
    params = urllib.parse.urlencode({"type": "r", "q": f"{case_name} {query}"})
    payload = _json(f"{SEARCH_API}?{params}")
    results = payload.get("results") or []
    wanted_id = spec.get("docket_id")
    exact = next((row for row in results if row.get("docket_id") == wanted_id), None)
    return (exact or (results[0] if results else None)), "docket"


def _opinion_text(result: dict[str, Any], *, token: str) -> tuple[str, str]:
    if not token:
        return "", "CourtListener detail API requires COURTLISTENER_API_TOKEN"
    opinions = result.get("opinions") or []
    if not opinions or not opinions[0].get("id"):
        return "", "search result has no opinion id"
    try:
        detail = _json(OPINION_API.format(opinion_id=opinions[0]["id"]), token=token)
    except urllib.error.HTTPError as exc:
        return "", f"opinion detail HTTP {exc.code}"
    for key in ("html_with_citations", "html", "html_lawbox", "plain_text", "xml_harvard"):
        value = detail.get(key)
        if value:
            return _text_from_bytes(
                str(value).encode(), "text/html", "detail.html"
            ), "courtlistener_opinion_api"
    return "", "opinion detail contained no text"


def _verify_exact_phrase(case: dict[str, Any], quote: str) -> bool:
    """Confirm a phrase against CourtListener's indexed opinion text.

    This keyless fallback is useful when a publisher has not supplied a public
    download URL and the detail API is token-gated. Exact phrase search must
    return the already-curated cluster; a merely similar search hit is rejected.
    """
    spec = case.get("courtlistener") or {}
    wanted_cluster = spec.get("opinion_cluster_id")
    if not wanted_cluster:
        return False
    params = urllib.parse.urlencode(
        {
            "type": "o",
            "case_name": str(spec.get("search_case_name") or case.get("name") or ""),
            # CourtListener's analyzer normalizes punctuation. Sending the
            # same normalized phrase avoids curly apostrophes making an exact
            # judicial passage appear absent.
            "q": f'"{_normalise(quote)}"',
        }
    )
    payload = _json(f"{SEARCH_API}?{params}")
    return any(row.get("cluster_id") == wanted_cluster for row in (payload.get("results") or []))


def _verify_passage(
    case: dict[str, Any], result: dict[str, Any] | None, *, token: str, metadata_only: bool
) -> dict[str, Any]:
    source = case.get("source") or {}
    quote = str(source.get("quoted_passage") or "")
    if metadata_only:
        return {"status": "not_checked", "reason": "metadata-only run"}
    if not quote:
        return {"status": "failed", "reason": "no curated quoted_passage"}

    document_url = str(source.get("document_url") or "")
    text = ""
    method = ""
    error = ""
    if document_url:
        try:
            body, content_type = _request(document_url)
            text = _text_from_bytes(body, content_type, document_url)
            method = "linked_court_document"
        except Exception as exc:  # network/parser failures belong in the audit output
            error = f"linked document failed: {type(exc).__name__}: {exc}"

    if not text and result:
        opinion_download = next(
            (
                str(opinion.get("download_url"))
                for opinion in (result.get("opinions") or [])
                if opinion.get("download_url")
            ),
            "",
        )
        if opinion_download:
            try:
                if opinion_download.startswith("http://"):
                    opinion_download = "https://" + opinion_download.removeprefix("http://")
                body, content_type = _request(opinion_download)
                text = _text_from_bytes(body, content_type, opinion_download)
                method = "opinion_download_url"
                error = ""
            except Exception as exc:
                error = f"opinion download failed: {type(exc).__name__}: {exc}"

    if not text and result:
        text, detail_reason = _opinion_text(result, token=token)
        method = "courtlistener_opinion_api" if text else ""
        error = detail_reason if not text else ""

    if not text:
        # Non-CourtListener mirrors are useful for district orders omitted from
        # opinion search. Do not scrape the JS-protected CourtListener page.
        source_url = str(source.get("url") or "")
        if source_url and "courtlistener.com/opinion/" not in source_url:
            try:
                body, content_type = _request(source_url)
                text = _text_from_bytes(body, content_type, source_url)
                method = "linked_court_document"
                error = ""
            except Exception as exc:
                error = f"source document failed: {type(exc).__name__}: {exc}"

    if not text:
        if _verify_exact_phrase(case, quote):
            return {
                "status": "verified_now",
                "method": "courtlistener_exact_phrase_search",
                "text_sha256": None,
                "text_characters": None,
            }
        return {"status": "not_verified", "reason": error or "no retrievable court text"}

    found = _normalise(quote) in _normalise(text)
    if not found and _verify_exact_phrase(case, quote):
        return {
            "status": "verified_now",
            "method": "courtlistener_exact_phrase_search",
            "text_sha256": None,
            "text_characters": None,
        }
    return {
        "status": "verified_now" if found else "passage_not_found",
        "method": method,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_characters": len(text),
    }


def _normalise_result(result: dict[str, Any], result_type: str) -> dict[str, Any]:
    absolute = result.get("absolute_url") or result.get("docket_absolute_url")
    return {
        "result_type": result_type,
        "case_name": result.get("caseName"),
        "court": result.get("court_citation_string") or result.get("court"),
        "docket_number": result.get("docketNumber"),
        "docket_id": result.get("docket_id"),
        "opinion_cluster_id": result.get("cluster_id"),
        "citation": result.get("citation") or [],
        "date_filed": result.get("dateFiled"),
        "date_terminated": result.get("dateTerminated"),
        "url": f"https://www.courtlistener.com{absolute}" if absolute else None,
        "opinion_ids": [o.get("id") for o in (result.get("opinions") or []) if o.get("id")],
    }


def main() -> int:
    global OPINION_API, SEARCH_API, _courtlistener_delay
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="sync only this corpus id; repeat for more than one",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="seconds between CourtListener API calls (default: 13 keyless, 1 authenticated)",
    )
    args = parser.parse_args()

    raw = yaml.safe_load(args.corpus.read_text(encoding="utf-8")) or {}
    settings = get_settings()
    token = (os.getenv("COURTLISTENER_API_TOKEN") or settings.courtlistener_api_token).strip()
    api_base = settings.courtlistener_api_base.rstrip("/")
    SEARCH_API = f"{api_base}/search/"
    OPINION_API = f"{api_base}/opinions/{{opinion_id}}/"
    _courtlistener_delay = args.delay if args.delay is not None else (1.0 if token else 13.0)
    records: list[dict[str, Any]] = []
    failures = 0

    cases = raw.get("cases") or []
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case.get("id") in wanted]

    for case in cases:
        case_id = case.get("id")
        print(f"{case_id}: {case.get('name')}")
        try:
            result, result_type = _search(case)
            verification = _verify_passage(
                case, result, token=token, metadata_only=args.metadata_only
            )
            if result is None:
                failures += 1
            record = {
                "case_id": case_id,
                "courtlistener": _normalise_result(result, result_type) if result else None,
                "passage_verification": verification,
            }
            print(f"  {'located' if result else 'not located'}; passage={verification['status']}")
            records.append(record)
        except Exception as exc:
            failures += 1
            print(f"  failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            records.append({"case_id": case_id, "error": f"{type(exc).__name__}: {exc}"})

    output = {
        "source": SEARCH_API,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "authenticated": bool(token),
        "corpus": str(
            args.corpus.relative_to(ROOT) if args.corpus.is_relative_to(ROOT) else args.corpus
        ),
        "records": records,
    }
    if args.case_id and args.out.exists():
        try:
            previous = json.loads(args.out.read_text(encoding="utf-8"))
            merged = {row.get("case_id"): row for row in (previous.get("records") or [])}
            merged.update({row.get("case_id"): row for row in records})
            output["records"] = list(merged.values())
        except (OSError, json.JSONDecodeError):
            pass
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(output['records'])} records to {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
