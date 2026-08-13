# The demo screenplay

`the_long_shadow.fountain` is an original short screenplay written for this
project. It exists so the demonstration runs on material we own outright.

## Why an original script

Three reasons, in order of importance.

**Rights.** Committing a real production's draft to a public repository is
itself a clearance problem, and building a clearance tool on an uncleared asset
would be difficult to defend in front of judges who work in this industry.

**Privacy.** The demo must never surface a living private individual. Margaret
Holloway, Arthur Penn and every other character here are invented. The
production the script depicts never happened, so no real person is depicted,
identified, or made the subject of any assertion.

**Control.** Every beat of the demonstration is scripted into the source
material itself, which means the recording is reproducible rather than lucky.

## What is seeded, and what each seed demonstrates

The script is engineered so the pipeline produces a legible, dense, honest
result. Roughly sixty percent verified, a meaningful amber band, and red rare
enough that every red line on screen is readable and damning.

| Seed | Where | Demonstrates |
|---|---|---|
| A truth claim title card | First line | The project level escalation firing on screen. Every person adjacent subject moves up one tier. |
| A contradicted factual claim | "The Air Ministry refused her a licence in 1931" | The red line with citations. One character asserts it, another contradicts it, and the record settles it. |
| A second contradicted claim | "Twice. They refused her twice." | Atomic decomposition. The count is a separate claim from the refusal, and each verifies independently. |
| Unsupported claims | "You've never flown a night leg alone" | Amber. Plausible, and the record says nothing either way. |
| A verifiable achievement | "first woman to hold a first class navigator's certificate" | Green with receipts. The system is not a paranoia engine. |
| A pure opinion | "She was an impossible woman" | Grey. Defamation law protects opinion, so it is classified, never researched, and never coloured. |
| An opinion argued about on the page | "That is not a fact, that is an opinion" | The distinction the product rests on, stated by a character. |
| A named music cue | "The Way You Look Tonight" | Two separate rights, composition and master, plus a monitor with an expiry window. |
| A described visible artwork | The Schneider Trophy poster on the hangar wall | The visual copyright path. Background set dressing is a rights question. |
| A fictional character name repeated | Margaret Holloway, throughout | Name collision research, and the verified rename remedy. |
| A faded photograph on a mantel | Cottage scene | A second visual element, deliberately low prominence. |

## The dramatic reason the seeds work

The seeds are not decoration bolted onto a scene. The script is *about* the
difference between what is true and what is repeated, which is why a journalist
who printed something wrong and spends forty years being unable to unprint it
is the spine of it. The contradicted claims are contradicted **on the page** by
another character, so a viewer understands the stakes before the system says a
word.

That is deliberate. A demonstration where the audience already knows the answer
before the machine gives it is a demonstration where they can judge whether the
machine is right.

## Expected output

Approximate, and it will move as the ingest and claim extraction quality
improves.

| Measure | Expectation |
|---|---|
| Scenes | 8 |
| Claims extracted | 40 to 70 |
| Clearance elements | 25 to 40 |
| Verdict mix | mostly verified, a visible amber band, two to four red |
| Counsel items | 5 to 15 |
| Monitors opened | 3 to 6 |
| Cost, live mode | well under one dollar at this length |

Run it:

```
make pipeline
truestory run demo/screenplay/the_long_shadow.fountain --report
```

## Ground truth

`eval/labeled_script/ground_truth.json` holds the hand labels for this script.
The protocol is two independent labellers, disagreements adjudicated, and the
adjudicated set becomes ground truth. See `eval/labeled_script/README.md`.

## A note on the subject matter

Any resemblance between the characters here and real aviators of the period is
unintended. The script deliberately avoids the biographical details of any real
person, and where a period detail is used it is generic to the era rather than
specific to an individual. If a future revision moves toward a real historical
figure, that figure must be deceased, must be a public figure, and the estate
posture and post mortem publicity term of the relevant jurisdiction must be
confirmed by counsel before the change is committed.
