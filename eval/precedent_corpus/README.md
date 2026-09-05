# Precedent data

This directory contains two different datasets. They must not be presented as
if they prove the same thing.

## Runtime precedent records

`verified_cases.yaml` is the reviewed corpus used by the product. Every record
has an actual case name, court, docket number, citation where available,
procedural posture, decision-level outcome, source link, pin cite, and short
judicial passage. `src/truestory/agents/precedent.py` combines factual/legal
shape with conservative keyword overlap against each record's issues, holding,
and sourced passage.

Refresh the CourtListener metadata and re-check passages with:

```powershell
python eval/precedent_corpus/sync_courtlistener.py
```

The command writes `courtlistener_records.json`, including whether each exact
record was located and whether its passage was found in court text during that
run. Public search works keylessly but is rate-limited. Set a free
`COURTLISTENER_API_TOKEN` to enable opinion detail, docket entries, and RECAP
document retrieval. A search hit alone never changes a record to verified.

The application performs retrieval over this local reviewed index rather than
making a CourtListener call in every user run. This gives reproducible reports,
avoids leaking screenplay content to a court-data provider, and prevents API
outages or changing search ranks from silently changing a clearance report.

## Broad docket research dataset

`dataset.json` is a separate set of 210 deduplicated federal dockets fetched by
`fetch_courtlistener.py`. It is useful for studying filing volume, venue, and
time to termination. It is not used as runtime precedent because keyword search
results have not been reviewed judgment by judgment.

It cannot establish settlement amounts or calibrate absolute loss estimates.
“Terminated” can mean settlement, merits dismissal, jurisdictional dismissal,
transfer, or abandonment. Those distinctions require docket-entry and document
review; settlement figures are often confidential even then.

## Verification rule

A runtime record is verified only when all of the following exist:

- exact court and docket identification;
- an opinion/order source URL;
- a short quoted judicial passage and pin cite;
- an explicit verification method and date;
- passage confirmation against retrieved court text or documented human review.

Verification means the metadata and quoted passage were checked. It does not
mean TRUE STORY predicts how a new dispute would be decided, and precedent
matches never change a finding's clearance status.
