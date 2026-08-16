# Eval A: the labelled script

Ground truth for `demo/screenplay/the_long_shadow.fountain`, and the protocol
that produces it.

## Why hand labelling

Recall is the number that matters most and it is the number a system cannot
measure about itself. If the pipeline never extracted a claim, the pipeline has
no idea the claim existed. The only way to know what was missed is for a human
to have written down what was there.

## Protocol

1. **Two labellers work independently.** They do not see each other's file and
   they do not see the pipeline output. Independence is the whole point: a
   labeller who has read the machine's answer will anchor to it.

2. **Each labels every clearable element and every factual claim.** Element
   labels record the type, the canonical form, and every page it appears on.
   Claim labels record the atomic assertion, its type, its polarity, and the
   subject it concerns.

3. **Disagreements are adjudicated by a third person.** Both original labels
   are kept in the file, because the disagreement rate is itself a finding: a
   category the two humans could not agree on is not a category the machine
   should be scored harshly on.

4. **The adjudicated set becomes ground truth.** It is committed here and
   versioned, so a change in the score can be traced to a change in the system
   rather than a change in the yardstick.

## What is measured

| Metric | Meaning |
|---|---|
| `element_recall` | Share of labelled elements the pipeline found. The most important number in this suite. |
| `element_precision` | Share of found elements that were real. A false positive costs a cheap lookup, so recall is weighted higher. |
| `claim_recall` | Share of labelled claims extracted. |
| `claim_precision` | Share of extracted claims that are real, atomic claims. |
| `dedup_ratio` | Spans divided by elements. Naive extraction on a feature yields two thousand spans and the ledger must collapse them to a few hundred subjects. |
| `dedup_accuracy` | How close the achieved ratio is to the labelled one. |
| `verdict_accuracy` | Verdicts on the seeded claims, where we know the answer because we wrote the falsehoods. |

## The seeded claims

The demo screenplay contains deliberately planted claims whose truth value we
control. They are listed in `ground_truth.json` under `seeded_claims` with the
verdict the pipeline should reach. This is the only part of the evaluation
where the correct answer is knowable with certainty rather than by agreement,
which makes it the strongest signal in the suite.

## Reporting

Report the misses. A stated recall of 0.92 is worth more than a claimed 1.00,
and every number quoted publicly comes from the harness output rather than from
a summary of it.

```
make eval
python eval/run_eval.py --suite labeled_script --out eval/results
```

## Status

`ground_truth.json` in this directory is a **scaffold**. It carries the correct
shape and a small number of real entries so the harness runs end to end, and it
is not a complete two person labelling of the screenplay. Completing it is item
9 of the README build status, and until it is done the recall figures this suite
reports are not publishable. Today the suite reports zero claim recall, because
the offline extractor does not recover the seeded claims.
