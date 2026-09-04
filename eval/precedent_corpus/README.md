# Precedent corpus: real docket data

`dataset.json` is 210 real, deduplicated federal court dockets, fetched live
from [CourtListener](https://www.courtlistener.com)'s public search API —
public record, not synthetic, not scraped from summaries. Regenerate with:

```
python eval/precedent_corpus/fetch_courtlistener.py
```

It found `Fiona Harvey v. Netflix, Inc.` — the actual Baby Reindeer
lawsuit — on the first query, filed 2024-06-06. That's a genuine confirmation
the search terms surface the right shape of case, not noise.

## What this data can support

**That suits of this shape get filed, in real volume, in the venues you'd
expect.** 210 dockets, dominated by C.D. Cal. (39) and S.D.N.Y. (28) — exactly
where entertainment litigation concentrates. This is a sanity check that the
exposure model's base rates aren't absurd on their face, nothing more.

**How long a filed claim actually takes.** Median 400 days from filing to
termination, across 132 dockets old enough to classify. That's a real,
citable number nothing in `policy/exposure.yaml` currently uses, because the
exposure model has no time dimension yet.

## What it cannot support, and why

**It cannot calibrate the dollar ranges in `policy/exposure.yaml`.**
CourtListener's docket detail — the field that would say what a case actually
settled for — sits behind a free API token, and even with one, settlement
amounts are very often sealed by the parties regardless. This is the same
wall the exposure model's own header names. Nothing changes that by scraping
harder.

**It cannot calibrate `outcome_weights` (dismissed / settled / adverse
judgment).** The 97% "resolution rate" in the summary is a real number and a
misleading one to use directly: "terminated" in a docket covers a voluntary
dismissal after settlement, a jurisdictional dismissal, a transfer to state
court, and a case simply abandoned — all indistinguishably. Telling those
apart requires reading docket entries, which needs the same paid-or-tokened
access as the dollar figures. Reporting 97% as if it means "97% of these
claims resolve favourably for the defendant" would be a worse error than
having no data, because it would look calibrated and isn't.

**It is not a random sample.** Six keyword queries against a search-ranked
index is not a representative draw from "all clearance-shaped litigation." A
suit that happens to match none of the six phrasings is invisible here.

## What `policy/exposure.yaml` does with it

Nothing changes automatically. `quantitative.calibrated` stays `false`. This
dataset is cited as an external reference in the policy file's header — real
data that exists and is now in the repository — not folded into the model's
numbers, because folding it in would overclaim what it supports.

## The actual next step, if this is worth pursuing further

A free CourtListener API token (same registration shape as the USPTO key
already in `.env.example`) unlocks docket entries and full text. With one, a
second pass over a sample of these 210 dockets could read the actual
termination filings and classify real dispositions — dismissed on anti-SLAPP,
settled, tried — which is the piece that would genuinely move
`outcome_weights` from a reasoned prior to a measured one. Dollar amounts
would likely still be mostly redacted; disposition category would not be.
