# FORTY-FIVE MINUTES

`forty_five_minutes.fountain` is the evaluation fixture the build specification
asked for and `the_long_shadow.fountain` could never be: **a script whose named
subjects are real, deceased, public, and abundantly documented.**

`the_long_shadow.fountain` is an excellent demonstration of the *interface*. It
cannot demonstrate the *engine*, because every character in it is invented, so
live research can only ever return `no_record`. A fact verification system whose
demo cannot produce a green verdict with receipts is showing its chrome. This
script exists so the pipeline can be pointed at the real web and be right, and
be caught when it is wrong.

Keep both. `the_long_shadow` remains the safe offline demo; this one is the
accuracy fixture and the on camera run.

---

## 1. Why these subjects

Every named person is a **deceased public figure**, which is the narrowest safe
category for a public fixture: no living private individual appears, and every
subject has a documented record dense enough that both a `VERIFIED` and a
`CONTRADICTED` verdict are reachable against the live record.

| Subject | Status | Why they are here |
|---|---|---|
| Jesse Owens (1913–1980) | Deceased public figure | Abundant record. Ohio post mortem publicity right runs 60 years, so the estate position is live and checkable, not academic |
| Larry Snyder (1896–1982) | Deceased public figure | His real Ohio State coach. Documented, but far thinner than Owens, which is the point |
| Marty Glickman (1917–2001) | Deceased public figure | The relay withdrawal is documented; the motive he alleged is contested. That split is the fixture |
| Luz Long (1913–1943) | Deceased public figure | The advice story rests on Owens' own later account. Structurally amber |
| Leni Riefenstahl (1902–2003) | Deceased public figure | *Olympia* footage. A real, hard, still live rights question |
| The heavy man in evening dress | **Never named** | Identifiable by role, event, year and act. This is the identifiability test |
| Harold Vance | **Invented** | The B7 regression test. Must be typed `PERSON_NAME_FICTIONAL` and must not be matched to any real person of that name |

The invented character is load bearing. README item 12 records that after the
B7 fix there was **no way to confirm the classifier still recognises a real
person when one is present**, because no test script contained one. This script
contains six real people and one invented one in the same room. If ingest types
Owens fictional, or types Vance real, that is now a visible, reproducible
failure rather than an unknown.

---

## 2. The dramatic spine

A newsreel writer is cutting commentary for footage of the 1936 Olympic Games.
He needs forty feet of words. Everyone in the room hands him a different version
of the same afternoon, and the version he prints is the one that outlives all
the others.

That is the product's thesis staged as a scene: **the repeated version outlives
the true one, and the gap between them is where the money is lost.** The
audience watches a falsehood get chosen for a commercial reason and go into a
final deliverable, which is the exact mechanism every case in the litigation set
turns on.

The structure is deliberate:

- **The argument.** Claims are asserted, contested and left unresolved on the page.
- **The button.** `NARRATOR (V.O.)` reads the finished commentary flat, and it
  contains the falsehoods that lost the argument.

So each seeded falsehood appears **twice**: once as contested dialogue, once as
flat assertion in a deliverable. The overlay should mark both, and the narration
block is where a viewer's eye lands, because there is nobody left in the room to
argue with it.

---

## 3. The seed table

Every seed maps to a real dispute or a documented historical error. `Verdict` is
the expectation; where the record is genuinely ambiguous the expectation is
amber, and a green there is a **failure**, not a bonus.

### 3.1 The money shot: contradicted

| # | Line | Verdict | The record | Maps to |
|---|---|---|---|---|
| **S-01** | "The Chancellor rose from his box, turned his back, and left the stadium rather than shake the hand of a Black American." | `CONTRADICTED` | Hitler left after the **first** day, before Owens had won anything, after the IOC required him to greet all winners or none. Owens' own repeated account was that Hitler waved. The athlete not greeted on day one was Cornelius Johnson | A myth repeated in film and print for eighty years. The single most cited example of "everyone knows it, and it is wrong" |
| **S-02** | "In forty-five minutes on this field, one man broke four world records." | `CONTRADICTED` | Four world records in roughly 45 minutes happened at the **Big Ten Championships, Ann Arbor, Michigan, 25 May 1935** — not Berlin, not 1936 | Right subject, right feat, wrong place and year. The class of error a human researcher skims straight past because the famous half is true |

S-02 is the more valuable of the two. S-01 is a falsehood a careful reader might
catch. S-02 is one they will not, because nothing about the sentence is
implausible and only a source check separates it from the truth.

### 3.2 Green with receipts

| # | Line | Verdict | The record |
|---|---|---|---|
| **S-03** | "Four golds. The hundred metres, the two hundred, the long jump and the relay." | `VERIFIED` | Documented to exhaustion. The system must not flag this, and flagging it is a paranoia failure |
| **S-04** | "He could not live on the campus he won for. Four years he lived off it and ate where they would have him." | `VERIFIED` | Owens lived off campus and was subject to segregated accommodation and dining while at Ohio State |
| **S-05** | "They pulled us this morning. Me and Sam. Two hours before the heat." | `VERIFIED` | Glickman and Sam Stoller were withdrawn from the 4x100 relay on the morning of the heat |

S-03 and S-04 are the proof the tool is not a smoke alarm. **A run that returns
no green is a failed run**, and this is the fixture that can finally say so.

### 3.3 Amber, the category that settles

| # | Line | Verdict | Why it is not green |
|---|---|---|---|
| **S-06** | "He told him where to plant his foot. Walked over between the fouls and told him to jump from further back." | `UNSUPPORTED` | The Luz Long advice rests substantially on Owens' own later accounts. Not provably false, not independently documented. Structurally amber, and a green here means the adjudicator is treating a repeated anecdote as a record |
| **S-07** | "Ask the heavy man in evening dress. He is the one who does the asking of the Germans." | `UNSUPPORTED` → `NEEDS_COUNSEL` | The **withdrawal is documented** (S-05). The **motive is contested** and has been for decades. Atomic decomposition must split these: one green, one amber, same paragraph, same speaker |

S-07 is the highest value seed in the file. It is the **Richard Jewell** shape:
a real, identifiable person given an unproven motive in a production framed as
true. That shape has drawn a demand letter, a public dispute and a disclaimer in
living memory. If the pipeline returns one blended amber over S-05 and S-07
together instead of splitting them, the decomposition claim in README §2 is not
true and this fixture proves it.

### 3.4 Grey, and it must cost nothing

| # | Line | Verdict | Note |
|---|---|---|---|
| **S-08** | "He is a small man in a large chair." | `OPINION` | Pure characterisation. **Offline path misses this** — see below. Deliberate |
| **S-09** | "He was the worst of them, and a coward about it." | `OPINION` | Carries `worst`, which is in `_OPINION_MARKERS`, so **both** paths catch it and grey always renders on camera |
| **S-10** | "It is an opinion. You can print anything that is an opinion." | `OPINION` | The distinction stated aloud, so the audience learns the rule from the scene rather than the README |

**The three lines are calibrated deliberately, and the split is the point.**
`ClaimExtractor`'s offline path classifies opinion by matching against
`_OPINION_MARKERS`, an eighteen adjective `frozenset` in
[claims.py](../../src/truestory/agents/claims.py). Verified directly:

```
'She was an impossible woman.'         -> opinion: True    ("impossible" is listed)
'He is a small man in a large chair.'  -> opinion: False
'He was a coward about it.'            -> opinion: False
```

So S-09 is written to trip the word list and S-08 is written not to. On the
offline path exactly one of the three should go grey; under the Gemini path all
three should. **The gap between those two numbers is a direct measurement of
what the model adds over the keyword fallback**, and it is now a standing number
this fixture reports on every run rather than an open question.

The word list is also the finding underneath the finding: opinion versus fact
is the constitutional core of defamation law and the single largest budget
control in the product, and offline it is eighteen adjectives. That is fine as a
documented fallback and misleading as an unlabelled default.

**These exist because the current run filters zero opinions.** `make pipeline`
on `the_long_shadow` reports `0 opinions filtered` and `0 grey`, so the feature
README §2 calls "the most legally motivated rule in the system and its largest
budget control" renders as a zero on screen. Three unmistakable opinion lines
about an identifiable person make that number impossible to miss — in either
direction.

Expected research spend on S-08, S-09 and S-10: **zero cents**. Any spend is a
failure, and it is a cheap, precise assertion for a test.

### 3.5 The clearance elements

| # | Element | Type | The real question |
|---|---|---|---|
| **S-11** | "Are those the adidas?" / "They are Dassler's." | `TRADEMARK_LOGO` | Double catch. A live mark, **and** an anachronism: adidas was founded 1949; in 1936 it was Gebrüder Dassler Schuhfabrik. The line is corrected on the page, so a run that flags only the trademark and misses the period error has found half of it |
| **S-12** | Riefenstahl's *Olympia* negative, cut into the newsreel | `FILM_CLIP` | A real and still live clearance problem. Riefenstahl died 2003; German term is life plus 70 |
| **S-13** | "Pennies from Heaven" on a gramophone | `MUSIC_CUE` | Two rights, composition and master, and the monitor with an expiry window. 1936, Johnston and Burke |
| **S-14** | The front page, "full frame, six seconds" | `SOURCE_MATERIAL` | The trap. A 1936 US newspaper is **not** public domain in 2026: published works run 95 years from publication, so 1936 clears in 2032. "It is from 1936" is the wrong instinct and the tool should say so |
| **S-15** | "the Chancellor and I, we understood one another" | `QUOTE` | Attributed to Owens, denied by him on the page, undocumented. The `quote_attribution_v1` path, with `quote_documented: false` |
| **S-16** | The heavy man in evening dress | `REAL_PERSON_IDENTIFIABLE` | Never named. Role plus event plus year plus act resolves to one person. **Naming is not the trigger; identifiability is** |
| **S-17** | Harold Vance | `PERSON_NAME_FICTIONAL` | The B7 regression test. Must not acquire a real person's biography |
| **S-18** | TITLE CARD: THIS IS A TRUE STORY | `TRUTH_CLAIM_FRAMING` | Project level escalation, every person adjacent subject up one tier |

S-14 is the quiet favourite. It is a rights error a smart person makes *because*
they are being careful, and it is settled by one date arithmetic that a research
call returns instantly.

---

## 4. What this fixture is for

Three jobs, in order.

**1. It unblocks accuracy work.** README items 9 and 10 are both marked broken
and both are blocked on the same missing thing: a script with real subjects.
Ground truth for this file is `eval/labeled_script/ground_truth_forty_five_minutes.json`.

**2. It is the on camera run.** S-02 is the demo's best ten seconds: a sentence
nobody in the room doubts, marked red, with the Ann Arbor sources attached. That
is a thing a judge has not seen another submission do.

**3. It is the B7 regression test.** Six real people and one invented one, in
one room. Run it before every submission build.

---

## 5. Verification status, stated honestly

Consistent with README §14 and litigation set item 11, **every historical and
legal fact in this document is `verify: required`.** They are recorded here as
the fixture's design intent and as the expected verdicts, not as findings this
project has independently confirmed.

The two person rule applies before any number derived from this script is quoted
publicly. In particular:

- The **Ann Arbor** date, venue and record count (S-02) is the fixture's central
  assertion and must be confirmed against a primary or archival source, because
  the entire demo turns on it.
- The **post mortem publicity term** for Ohio and the Owens estate posture
  (S-03, S-04) needs confirming before any run against this script is shown as a
  rights position rather than a research result.
- The **Riefenstahl** and **newspaper** term calculations (S-12, S-14) are the
  arithmetic as understood; the applicable term and territory should be checked.

Nothing in this file is legal advice, and nothing asserted by a character in the
screenplay is a statement of fact by its authors.

---

## 6. Running it

```bash
truestory run demo/screenplay/forty_five_minutes.fountain --report
TRUESTORY_MODE=live truestory run demo/screenplay/forty_five_minutes.fountain
```

Expected shape of a healthy live run:

| Measure | Expectation | Failure signal |
|---|---|---|
| Green verdicts | 3 or more, with citations | Zero green means research is not landing |
| Red verdicts | 2, S-01 and S-02 | Missing S-02 is the one that matters |
| Grey | 3, at zero cost | Zero grey means the opinion filter is not firing |
| Amber | S-06 and S-07 present and **separate** | One blended amber breaks the decomposition claim |
| Vance | `PERSON_NAME_FICTIONAL` | Anything else is a B7 regression |
| Owens | real, identity confirmed | Fictional is the over correction B7 warned about |
