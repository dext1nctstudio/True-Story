# Recorded provider fixtures

Real provider responses, recorded once and replayed forever. They are committed
on purpose, and `.gitignore` carries an explicit exception to keep them.

## What they buy

**A reviewable repository.** Anyone can clone this project with no credentials
and run the complete eight stage pipeline against these fixtures, producing a
real ledger, a real overlay and a real report in under a minute. That is worth
more than any amount of documentation.

**A reproducible evaluation.** The Litigation Set has to give the same answer
twice or the number means nothing. Fixtures remove the provider from the
variance.

**A free, deterministic demo.** Warm the cache once on a paid live run, and
every recorded take afterwards costs nothing and returns byte identical
results. This is standard production practice rather than a shortcut, and it
removes the single largest source of demo day fragility.

## Format

One JSON file per subject, or an array of records in one file. Each record:

```json
{
  "cache_key": "a1b2c3...",
  "subject_id": "cl_1234567890abcdef",
  "finding": { "verdict": "contradicted", "contradicting_facts": [] },
  "citations": [
    {
      "url": "https://example.org/record/1",
      "title": "Source title",
      "excerpt": "The passage relied on, quoted verbatim.",
      "source_type": "primary"
    }
  ],
  "reasoning": "Why the finding follows from those sources.",
  "confidence": 0.94,
  "latency_ms": 4200
}
```

`cache_key` is the hash of subject, question, schema, processor and
jurisdictions. `MockProvider` matches on it first and falls back to
`subject_id`.

## Recording new fixtures

```
TRUESTORY_MODE=live truestory warm-cache demo/screenplay/the_long_shadow.fountain
```

That writes to `.truestory_cache/`. Promote the entries you want to keep into
this directory, and review each one before committing.

## Review every fixture before committing

These files contain research findings about real subjects, and this repository
is public. Before a fixture lands here:

- Confirm it contains no identifying detail about a living private individual.
  The masking rules apply to what we commit exactly as they apply to what the
  product displays.
- Confirm the excerpts are short and attributed. They are quoted for evidentiary
  purposes and should stay proportionate to that.
- Confirm nothing in it asserts something about a real person that the cited
  source does not support. A fixture is a recording, not a claim we are making,
  but it will be read as one.

## What is here now

The directory is empty apart from this file. `MockProvider` synthesises
deterministic answers when no fixture matches, seeded on the cache key, so the
pipeline runs and every branch is exercised including contradiction, conflict,
low confidence and outright research failure. Those synthesised envelopes are
clearly labelled and carry no research value at all.

Recording the real fixture set is item 8 in the README TODO.
