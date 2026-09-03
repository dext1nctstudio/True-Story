<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="web/public/logo-light.png">
  <source media="(prefers-color-scheme: light)" srcset="web/public/logo.png">
  <img src="web/public/logo.png" alt="TRUE STORY — Fact &amp; Rights Engine" width="560">
</picture>

<br>

**A fact and rights engine for "based on a true story" productions.**

[![ci](https://github.com/dext1nctstudio/True-Story/actions/workflows/ci.yml/badge.svg)](https://github.com/dext1nctstudio/True-Story/actions/workflows/ci.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![runs offline](https://img.shields.io/badge/runs-offline%2C%20no%20credentials-2ec5b6.svg)](#4-quick-start)

</div>

---

Reads a screenplay. Checks every factual claim about every real person against
the live public record. Marks each line green, amber or red with the sources
attached. Underneath, it clears every name, brand, song, artwork and location
that could trigger a lawsuit, documented to the standard insurance carriers
require before a film can be distributed. Then it keeps watching, because facts,
licences and litigation all change after the report is filed.

Built for the Agentic Cinema hackathon, Parallel track. Gemini, Google Cloud
Agent Development Kit, Vertex AI Agent Engine, and five of Parallel's six web
APIs.

> [!IMPORTANT]
> **Decision support for a clearance attorney. Not legal advice.** Every
> clearance report in this industry is reviewed by a qualified attorney before a
> policy is bound. This system automates the research and the document, not the
> judgement.

---

## Table of contents

1. [The problem](#1-the-problem)
2. [A day with the tool](#2-a-day-with-the-tool)
3. [What it does](#3-what-it-does)
4. [Quick start](#4-quick-start)
5. [Architecture](#5-architecture)
6. [The agentic system](#6-the-agentic-system)
7. [Where the domain knowledge lives](#7-where-the-domain-knowledge-lives)
8. [Research: Parallel, and the fallback](#8-research-parallel-and-the-fallback)
9. [Google Cloud services in runtime use](#9-google-cloud-services-in-runtime-use)
10. [Four roles, four workspaces](#10-four-roles-four-workspaces)
11. [Cost](#11-cost)
12. [Evaluation](#12-evaluation)
13. [Repository layout](#13-repository-layout)
14. [Configuration](#14-configuration)
15. [Deployment](#15-deployment)
16. [Guardrails](#16-guardrails)
17. [Project status](#17-project-status)
18. [Licence](#18-licence)

---

## 1. The problem

"Based on a true story" are the five most valuable words in television, and the
five most dangerous. When a production tells a story about real people, every
line of dialogue is a claim about someone's life. Get one line wrong and the
consequences are now famous: streamers have faced nine figure defamation claims,
settled suits over a single sentence, and settled others days before trial. In
each case the problem was the same thing. A statement about a real person that
nobody had checked against the record.

The existing fix is a cottage industry of a few dozen expert researchers serving
a global content machine. A feature clearance report costs one to three thousand
dollars and takes three to seven business days. Every revised draft, every one
off name change, every art department signage request generates follow up
billing. And the report is a photograph: it says nothing about what happens to
those rights over the commercial life of the title.

Three structural facts make this a real workflow rather than a hypothetical:

- **It is mandatory.** No clearance, no errors and omissions policy. No policy,
  no distribution.
- **The work is structured web research at scale.** Hundreds of independent,
  cited, confidence scored lookups about the real world.
- **The output is a document, not a chat.** The industry runs on a specific
  report format that carriers already accept.

---

## 2. A day with the tool

> A narrative walkthrough of the product as four people actually use it. Every
> screen, action and artifact named here exists in the repository.

**09:12 — the writer sends a draft.**
Nina has finished the fourth draft of *Forty-Five Minutes*, a limited series
about a 1971 hearing. She drags the `.fountain` file onto the workspace. No
forms, no configuration. A run id comes back and the page starts filling in
line by line rather than showing a spinner: ingest finds 7 scenes and 23 spans,
and flags that the script opens on a title card reading *"This is a true
story."* That single detection escalates every person adjacent element in the
production by one full risk tier, and the interface says so at the top of the
script.

**09:14 — the script comes back coloured.**
Twenty-nine claims were decomposed from those spans. One line —
*"A twice convicted stalker, sentenced to five years"* — is not one claim, it is
three, and each is checked independently. Two come back green with citations.
The third comes back **red**: the record says the sentence was eighteen months.
Nina sees the contradiction, the two sources that establish it, and the excerpt
from each. Beside it, *"He was a difficult man"* is grey and cost nothing —
it is opinion, it is protected speech, and the system never researched it.

**09:20 — she takes the offered fix.**
The red line carries a proposed rewrite. Nina does not have to trust it: the
rewrite was pushed back through the identical research path under the identical
schema, and only a proposal that came back **verified** is offered at all. She
clicks apply. The redline is written to her draft.

**11:40 — counsel opens the docket.**
Priya is production counsel and the accountable human. Her workspace is not
Nina's. She opens a docket of runs, then the annotated script with the evidence
rail beside it, and works the escalations. One character is unnamed —
*"the ministry clerk who signed the refusal"* — and the identifiability check
has resolved it to a real living individual on profession plus city plus
relationship. Naming is not the legal trigger; identifiability is. The interface
renders `3 matching individuals · 4 sources · withheld pending counsel review`.
Priya unmasks it. She has to state a reason, and the reveal leaves a permanent
audit record naming her.

She also sees a person-level escalation that no single line would have produced:
four separate amber claims about one named living subject. Amber is not
"probably fine" — amber is the category that settles. Past a density threshold,
the *person* escalates even though no individual claim did.

**14:05 — the producer checks exposure, not evidence.**
Marcus opens the same run and gets a different product: exposure by person and
by page, spend against a manual report, counsel workload, and every live watch.
He is deliberately **not** given the research. A producer reading raw findings
about a named living person creates a discovery problem rather than solving one,
and the server enforces that, not the client.

**16:30 — the carrier receives a package.**
The underwriter gets the filed document and nothing else: the E&O report, the
clearance log as CSV, and the evidence appendix, watermarked and read only. No
working draft, no live cost, no unresolved items. A carrier is handed a filed
document, not a workspace.

**Eight months later — the tool speaks again.**
A music licence in episode three lapses. A monitor that has been running since
the report was filed fires a webhook, and the alert reaches the production
before the rights problem reaches distribution. That is the part a
three-thousand-dollar PDF cannot do: a clearance report is a photograph, and
rights are a film.

---

## 3. What it does

Drop in a draft. In minutes, for a couple of dollars:

**Every factual claim about every real person is decomposed and checked.**
"A twice convicted stalker sentenced to five years" is not one claim, it is
three, and each verifies independently. That is exactly how a complaint itemises
alleged falsehoods, and it is the difference between "this scene is risky" and
"this sentence is contradicted by the record, here are the sources".

**Opinion is filtered out and never researched.** "He was a difficult man" is
protected speech. It is classified, coloured grey, and costs nothing. The most
legally motivated rule in the system is also its largest budget control.

**Unnamed characters are checked for identifiability.** Profession plus city
plus description plus relationship resolves to a real person whether or not a
name appears. Naming is not the legal trigger; identifiability is.

**A truth claim changes everything downstream.** If the production tells its
audience the story is true, every person adjacent element is escalated one full
risk tier, because courts have treated that framing itself as bearing on whether
a production acted with reckless disregard for falsity. That is one rule in a
configuration file implementing a doctrine two federal courts applied.

**Unsupported claims are counted per person, not just per line.** Amber is not
"probably fine". Amber is the category that settles: not provably false, and
therefore not defensible either. Once the density of unsupported conduct claims
about a named living person crosses a threshold, the *person* escalates.

**Rights are cleared, not just facts.** Names, brands, songs, artworks,
trademarks, locations and public domain status, each with its own output schema
and its own tool.

**Fixes are proposed and then verified.** A contradicted line gets a rewrite,
the rewrite goes back through the identical research path under the identical
schema, and only a proposal that comes back verified is offered as a fix.

**Private individuals are masked by default.** Reveal is role gated, requires a
stated reason, and is permanently audited.

**Everything is priced before and metered during.** A pre-flight estimator and a
live cost meter share the same arithmetic, so the marketing number and the meter
number cannot drift.

**And then it keeps watching.** A clearance report is a photograph. Rights are a
film. Music licences expire quietly years after delivery, depicted people die
and publicity rights change by state, new suits get filed, new records surface.
Monitors run for the commercial life of the title.

---

## 4. Quick start

Runs with **no credentials, no network and no spend**. That is the default, not
a demo mode.

```bash
git clone https://github.com/dext1nctstudio/True-Story.git
cd True-Story

make install          # pip install -e ".[dev]", and copies .env.example to .env
make pipeline         # full eight stage run over the demo screenplay
```

Representative output of that command:

```
  ingest    7 scenes, 23 spans TRUE STORY ASSERTED
  claims    29 extracted, 0 opinions filtered
  ledger    13 elements (1.77x reduction)
  routing   39 subjects, projected $0.90
  verdicts  16 green · 8 amber · 2 red · 0 grey · 34 counsel
  remedies  2 verified of 2 proposed
```

The projection is what the same run would cost against live Parallel. Mock mode
itself spends nothing, and the counsel figure counts escalations and
confirmations together; the run summary separates them.

> [!NOTE]
> **Two numbers in that block are known defects, not results.**
> `0 opinions filtered` and `0 grey` should not both be zero on a script
> containing "She was an impossible woman", and the contradicted claims this run
> prints are dialogue fragments rather than assertions. Both trace to one block
> in claim scoping and are tracked as **B9** and **B10** in the
> [engineering log](docs/ENGINEERING_LOG.md) rather than left for a reader to
> discover.

The fixture with real subjects is the other run worth doing:

```bash
truestory run demo/screenplay/forty_five_minutes.fountain
```

Three pages, six real deceased public figures and one invented character, with
eighteen catalogued seeds and expected verdicts.

Then the rest:

```bash
make test             # 384 tests, no network, no spend
make eval             # recall and precision against hand labelled ground truth
make eval-litigation  # blind runs against reconstructed published disputes
make dev              # REST API and live stream on :8080
make dev-web          # the verdict overlay on :3000
truestory doctor      # exactly what is wired and what is not
```

Produce the artifacts:

```bash
truestory run demo/screenplay/the_long_shadow.fountain --report
```

Writes the verdict overlay, the claim register, the errors and omissions report
as JSON and PDF, the clearance log as CSV, and the monitor manifest.

Ask the router why it made a decision:

```bash
truestory explain REAL_PERSON_DEPICTED
truestory explain claim --polarity negative --alive --framing
```

> [!NOTE]
> **Mock mode is honest about itself.** Every finding is synthesised offline,
> clearly labelled, and carries no research value. The offline extractor has far
> lower recall than the model pass and says so. It exists so a reviewer can
> exercise the whole system in under a minute, not so the numbers look good.

---

## 5. Architecture

```
                    ┌────────────────────────────────────────┐
                    │              HUMAN ACTORS              │
                    ├────────────────────────────────────────┤
  Screenwriter ─────▶ uploads a draft, sees the overlay,     │
                    │ receives verified rewrites             │
  Showrunner ───────▶ claim dashboard, risk posture, alerts  │
  Counsel ──────────▶ reviews escalations, unmasks, signs off│
  Underwriter ──────▶ receives the clearance package         │
                    └───────────────┬────────────────────────┘
                                    │
                    ┌───────────────▼────────────────────────┐
                    │             TRUE STORY                 │
                    │      ADK on Vertex AI Agent Engine     │
                    └───┬───────────┬───────────┬────────────┘
                        │           │           │
         ┌──────────────▼──┐  ┌─────▼─────┐  ┌──▼──────────────────┐
         │  Parallel Web   │  │  Gemini   │  │  Google Cloud       │
         │  Search Extract │  │ (Vertex)  │  │  Firestore BigQuery │
         │  Task  FindAll  │  │ long ctx  │  │  Cloud Run  Pub/Sub │
         │  Monitor        │  │ multimodal│  │  IAM  Secret Manager│
         └─────────────────┘  └───────────┘  └─────────────────────┘
```

Layered strictly downward, and nothing imports upward:

```
api / webhooks / cli        service tier, thin
  -> agents                 ADK orchestration, eight stages
    -> mcp                  domain tool boundary
      -> providers          ResearchProvider registry, vendor swappable
        -> models           frozen dataclasses, the contracts
          -> policy         routing table, rubric, jurisdictions
```

`models` and `policy` depend on nothing. Not Google Cloud, not Parallel, not a
web framework. That is why the whole pipeline runs offline and why CI needs no
cloud project.

Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 6. The agentic system

### Eight stages, one fixed order

```
TrueStoryPipeline = SequentialAgent(
    IngestAgent      -> LlmAgent      script text to typed spans        [LLM 1]
    ClaimExtractor   -> LlmAgent      spans to atomic factual claims    [LLM 2]
    LedgerAgent      -> deterministic coreference and deduplication
    RiskRouter       -> deterministic policy table lookup
    ResearchSwarm    -> ParallelAgent bounded, metered fan out
    Adjudicator      -> LlmAgent      evidence to verdicts, forced      [LLM 3]
    RemedyLoop       -> LoopAgent     propose, verify, max three        [LLM 4]
    ReportAgent      -> deterministic templated artifacts
)
```

The executable pipeline is
[`agents/pipeline.py`](src/truestory/agents/pipeline.py), and it runs anywhere,
including with no credentials at all. `build_adk_pipeline` wraps the same stages
in ADK workflow agents for deployment to Vertex AI Agent Engine, so the deployed
topology and the local one are the same eight stages rather than two divergent
code paths.

### Why workflow agents rather than one model with a bag of tools

**Four of eight stages use a language model. That is the design.** A legal
product cannot have a model improvising control flow. Stage order is fixed by
the domain, concurrency is infrastructure, and loop termination is objective.
Every prompt in the system lives in one file,
[`agents/prompts.py`](src/truestory/agents/prompts.py), so the count is visible
and a fifth decision point cannot appear quietly.

| Primitive | Used for | Why not a model |
|---|---|---|
| `SequentialAgent` | The spine | Stage order is fixed by the domain |
| `ParallelAgent` | Research fan out | Concurrency is infrastructure |
| `LoopAgent` | Remedy, at most three | Termination is objective: does it verify |
| `LlmAgent` | Ingest, extract, adjudicate, propose | The only four places judgement is required |

### The tool boundary

Fifteen domain tools in [`mcp/tools.py`](src/truestory/mcp/tools.py) —
`verify_factual_claim`, `attribute_quote`, `check_person_collision`,
`check_person_identifiability`, `check_publicity_rights`,
`check_entity_registration`, `check_trademark_status`, `check_entity`,
`check_music_rights`, `check_visual_copyright`, `check_public_domain`,
`enumerate_matching_entities`, `interrogate`, `capture_evidence_page` and
`watch_subject` — served over MCP so the same boundary is available to the
pipeline and to an external agent. The AgentCard in
[`a2a/agent_card.json`](a2a/agent_card.json) ships as a specification.

### Three safeguards worth reading the code for

**No verdict without evidence.** The Adjudicator can only speak by calling
`record_verdict`, which requires a non empty list of evidence identifiers. That
is a schema constraint under forced function calling, not a prompt instruction.
Underneath it, `FactualClaim.record_verdict` raises if the invariant is
violated. Both layers are exercised in
[tests/test_evidence_invariant.py](tests/test_evidence_invariant.py).

**Unsupported is not false.** The distinction between an assertion the record
contradicts and one the record cannot speak to is preserved in the enum, the
rubric wording, the UI copy, the API and the PDF. Collapsing it would be exactly
the careless assertion about a real person that this product exists to prevent.

**A research failure is never a finding.** When the research path cannot answer —
a drained account, an expired credential, a timeout — the run says so rather
than rendering the same "no record found either way" a genuinely silent public
record produces. Held by
[tests/test_research_failure_is_not_a_finding.py](tests/test_research_failure_is_not_a_finding.py)
and [tests/test_nameguard.py](tests/test_nameguard.py), which sweeps every
English pronoun and twenty six pieces of screenplay formatting against twenty
real subjects.

---

## 7. Where the domain knowledge lives

Not in prompts. In three files a clearance attorney can read, argue with, and
change without touching Python.

**[`policy/routing.yaml`](policy/routing.yaml)** — the RiskRouter, in its
entirety:

```yaml
  - id: claim_negative_living
    match: { kind: claim, polarity: negative, subject_alive: true }
    tier: CRITICAL
    processor: core
    schema: claim_verification_v1
    post: { if_not_verified: NEEDS_COUNSEL }
```

**[`policy/rubric.yaml`](policy/rubric.yaml)** — deterministic post checks and
the fixed wording a verdict is allowed to use.

**[`policy/jurisdictions.yaml`](policy/jurisdictions.yaml)** — territory rules
and post mortem publicity terms.

Eleven JSON output schemas in [`schemas/`](schemas/) shape every research
response, which is why a verdict comes back with supporting and contradicting
facts already separated rather than blended into prose. `claim_verification_v1`
is the workhorse, and it deliberately distinguishes `no_record` from
`contradicted`.

---

## 8. Research: Parallel, and the fallback

Five of six Parallel APIs, each doing a distinct job.

| API | Job here | Code |
|---|---|---|
| **Task** | Core verification and clearance research, tier routed by depth | [parallel_task.py](src/truestory/providers/parallel_task.py) |
| **Search** | The interrogation path. One round trip for "why is this line red" | [parallel_search.py](src/truestory/providers/parallel_search.py) |
| **FindAll** | Set valued questions. Every entity bearing this name; every person matching this cluster | [parallel_findall.py](src/truestory/providers/parallel_findall.py) |
| **Extract** | Capturing the page so a quote can be checked against the source, and preserving it for the appendix | [parallel_extract.py](src/truestory/providers/parallel_extract.py) |
| **Monitor** | Living Clearance. Facts, licences and litigation after the report is filed | [parallel_monitor.py](src/truestory/providers/parallel_monitor.py) |

`source_policy` is set on every Task request to keep the crawler away from
machine generated encyclopaedias and content farms, which restate their training
data without attribution and cannot support a claim about a real person.

**Why this partner fits this product.** Every response carries citations,
reasoning, excerpts and calibrated confidence per output field, which maps onto
the `Evidence` envelope close to one to one. For a system whose output is "this
line about a real person is false", that is not a convenience feature. A verdict
without a citation is legally worthless, so a provider that cannot produce
citations is structurally disqualified from critical work by
`ResearchProvider.supports_citations`, enforced in the registry rather than left
to a reviewer to notice.

### The fallback, and why it is two calls

Parallel is the primary research path and is always called first. This is about
what happens to the subjects it does not reach. Its Task API is asynchronous and
its latency under load is measured in minutes; a clearance run dispatches a
hundred or more subjects, and some fraction will still be running when any
reasonable deadline passes.

So a subject the primary could not answer is offered to Gemini with Google
Search grounding, and **the fallback runs as two calls in a fixed order**:

```
RETRIEVE    search the web, plain language, no schema
              -> grounded text + citations from grounding metadata
STRUCTURE   shape only the retrieved text, no search tool
              -> the output schema, under controlled generation
```

**The split is the guardrail, not an implementation detail.** Asking for the
Search tool and a JSON object in one call does not fail; it silently stops
searching. Measured here: 2 to 6 grounding chunks when asked plainly, **zero**
with a schema attached — while the model went on answering confidently from
memory. Splitting them means retrieval cannot invent a citation, because
citations come from grounding metadata rather than the model's prose, and
structuring cannot invent a fact, because it is handed the retrieved text and
told it is the only permitted input.

Three things then hold the result honest:

- **A source-less finding is restricted in code.** If retrieval returned nothing,
  the only verdicts permitted are `no_record` and `not_a_factual_claim`. A
  `supported` or `contradicted` is downgraded, and any facts the model listed are
  dropped, because they came from memory rather than from a page.
- **Every fallback answer is stamped.** `is_fallback` caps effective confidence
  at 0.6 and puts a coverage warning on the report front page.
- **The count is reported.** `ProviderRegistry.recoveries` records which subjects
  leaned on the fallback, so a run that used it heavily says so instead of
  presenting recovered answers as primary ones.

Parallel does the research. Gemini covers what Parallel did not reach, visibly,
at a stated discount in confidence.

---

## 9. Google Cloud services in runtime use

Imported and called in code, not named in a README. Every one is created in
[infra/](infra/).

| Service | Used for |
|---|---|
| **Vertex AI (Gemini)** | Ingest, claim extraction, adjudication, remedy proposal |
| **Agent Engine** | Hosts the ADK pipeline |
| **Cloud Run** | Tool server, webhook receiver, web app |
| **Firestore** | Run state, and real time listeners drive the live stream |
| **BigQuery** | Cost telemetry, eval results, precedent corpus with vector search |
| **Cloud Storage** | Scripts, captured evidence pages, reports |
| **Pub/Sub** | Alert fan out from the monitor callback path |
| **Cloud Tasks** | Retry and backoff. **Provisioned in Terraform, no client code yet** |
| **Cloud Scheduler** | The stale run sweep. **The job is provisioned; `/internal/sweep` is still a stub** |
| **Secret Manager** | Research key and webhook signing secret |
| **Cloud IAM** | Four custom roles, four service accounts |
| **Cloud Logging and Trace** | Adjudication audit trail, per stage spans |

---

## 10. Four roles, four workspaces

The role control selects a workspace, not a filter. Each role has its own
landing surface, rail, actions and accent, because these are four different
jobs, and [`web/lib/roles.ts`](web/lib/roles.ts) mirrors `VIEW_MATRIX` in
[`api/security.py`](src/truestory/api/security.py) so a role never renders a
panel the server would refuse.

| Role | Opens on | Gets | Does not get |
|---|---|---|---|
| **Counsel** | The docket, then the annotated script | Evidence, register, queue, overrides, unmask, cost | — |
| **Producer** | Production risk | Exposure by person and by page, spend against a manual report, counsel workload, watches | The research itself |
| **Writer** | Lines to look at | Their draft, verdicts, verified rewrites | Cost, evidence, register, queue |
| **Underwriter** | The filed package | Report, clearance log, evidence appendix, watermarked | The working draft, live cost, open items |

A role is also a link: `?role=truestory.producer` opens that workspace, so "here
is what the carrier sees" is a URL rather than a set of instructions.

Each role maps to a Firestore security rule **and** to the application view
matrix, so a role means the same thing in both places. There is no global
override role. Per project isolation lives in the Firestore rules rather than
only in application code, because an authorisation check that exists solely in a
service is one deploy away from being bypassed.

**Privacy by default.** This system's output is assertions about real people.
Built carelessly it is a defamation engine pointed at the people it protects. So
a living private individual is masked, always. The interface renders
`3 matching individuals · 4 sources · withheld pending counsel review`, which is
itself the useful signal. Revealing requires the counsel role, a stated reason,
and leaves a permanent audit record naming the principal.

---

## 11. Cost

Research and model spend are different invoices and are never blended into one
number, because a blended figure cannot be checked against either.

| Bill | Priced | Governed by the per script ceiling |
|---|---|---|
| Parallel Task, Search, Extract, FindAll, Monitor | per run, per URL, per match, per check | yes |
| Gemini | per token, with a cached input tier | no, deliberately |

Charging model tokens against the research ceiling would silently reduce the
research a script can buy, so they are metered separately and reported side by
side.

Every rate resolves from one place and is served over the API, so nothing in the
UI restates a price of its own:

```bash
curl localhost:8080/v1/pricing         # published unit prices, with the date they were verified
curl localhost:8080/v1/runs/$RUN/cost  # research, model, cache saving, projection, unit economics

curl -X POST localhost:8080/v1/estimate \
  -H 'content-type: application/json' \
  -d '{"pages":105,"drafts":4,"cache_hit_rate":0.9}'
```

The estimator runs the same subject density and the same processor prices the
router actually uses, so the number on the marketing surface and the number on
the meter are the same arithmetic. A redraft's model half is **not** discounted
by the cache: a rewritten draft is re read end to end whatever changed in it,
and only research, adjudication and remedy scale with the delta.

Roughly two to three dollars for a two hundred subject feature, against one to
three thousand dollars and days to weeks for the manual equivalent. The
`BudgetGovernor` degrades depth before failing a run, and critical work draws on
a reserve that ordinary subjects cannot touch.

---

## 12. Evaluation

Two suites, both reporting their misses.

**Eval A, the labelled script.** Two people independently label every element
and claim in the demo screenplay. Disagreements are adjudicated, and the result
is ground truth. Reports element and claim recall, precision, dedup accuracy,
and verdict accuracy against the seeded claims, where the answer is known
because the falsehoods were written deliberately.

```bash
make eval
```

**Eval B, the Litigation Set.** Reconstructed published disputes, embedded in
neutral scenes, run blind. Did the pipeline flag the specific item at issue, at
what tier, with what verdict, and does the evidence support the call.

```bash
make eval-litigation
```

The defence side cases are scored just as heavily. A system that flags
everything is useless, so correctly returning `CLEAR_WITH_CONDITIONS` on
expressive use that a court went on to protect matters exactly as much as
catching the failures. That is the difference between a clearance engine and a
paranoia engine.

> [!WARNING]
> **Neither number is publishable yet, and this section will not pretend
> otherwise.** The harness runs; the figures are not yet evidence of accuracy.
>
> - **Eval A returns `claim_recall 0.000` today.** The offline extractor does not
>   recover the seeded claims, so each is scored as a recall miss. It needs the
>   tuned Gemini pass and ground truth completed by two independent labellers
>   rather than the committed scaffold.
> - **Eval B returns 100% on ten cases, and that figure measures the routing
>   table only.** `_run_case` calls `routing.match()` and the project
>   escalations; it does not ingest the reconstructed scene, dispatch research,
>   or adjudicate. Until the reconstructions run through the full pipeline blind,
>   this is a policy self test and is described as one.
>
> Full detail in the [engineering log](docs/ENGINEERING_LOG.md).

A stated 0.92 beats a claimed 1.00, and every number quoted publicly comes from
the harness output rather than a summary of it.

---

## 13. Repository layout

```
├── policy/                          the domain knowledge, as data
│   ├── routing.yaml                 the RiskRouter, in its entirety
│   ├── rubric.yaml                  deterministic post checks and fixed wording
│   └── jurisdictions.yaml           territory rules, post mortem publicity terms
├── schemas/                         eleven Parallel output schemas
├── src/truestory/
│   ├── models/                      frozen contracts, zero dependencies
│   ├── policy/                      loader, matcher, validator
│   ├── providers/                   the swap layer, eight providers
│   ├── mcp/                         clearance tool server, fifteen domain tools
│   ├── agents/                      the eight stages, and every prompt
│   ├── storage/                     Firestore, BigQuery, GCS, Secret Manager
│   ├── api/                         REST, live stream, roles and masking
│   ├── webhooks/                    signed callback receiver
│   ├── reports/                     PDF rendering, no model in the path
│   └── cli.py
├── web/                             Next.js: overlay, evidence, dashboard, meter
├── eval/
│   ├── litigation_set/cases.yaml    reconstructed published disputes
│   ├── labeled_script/              hand labelled ground truth, two scripts
│   ├── fixtures/                    recorded provider responses
│   └── run_eval.py
├── demo/screenplay/                 scripts, all original
│   ├── the_long_shadow.fountain     invented cast, the safe offline demo
│   └── forty_five_minutes.fountain  real deceased subjects, the accuracy fixture
├── a2a/agent_card.json              AgentCard, shipped as a specification
├── infra/                           Terraform: services, IAM, buckets, secrets
├── deploy/                          Agent Engine deployment
├── tests/                           384 tests, no network, no spend
└── docs/
    ├── ARCHITECTURE.md              full architectural detail
    └── ENGINEERING_LOG.md           build status, defect log, what is outstanding
```

---

## 14. Configuration

Copy [.env.example](.env.example) to `.env`. Every value is documented inline.

```bash
TRUESTORY_MODE=mock       # mock | cached | live
```

| Mode | Behaviour |
|---|---|
| `mock` | Fixtures only. No network, no credentials, no spend. **The default.** |
| `cached` | Replays recorded responses, falls through to live on a miss. Demo recording mode |
| `live` | Real Parallel and real Vertex AI. Costs money, governed by the budget |

Live mode **fails loudly at startup** if a required credential is a placeholder,
rather than degrading into a run that produces a useless report.

In deployment, secrets come from Secret Manager and never from an environment
variable, a container image, or this repository.

---

## 15. Deployment

```bash
make infra-apply PROJECT=your-project     # Terraform: services, IAM, buckets, secrets

# add the secret values by hand, they never enter Terraform state
echo -n "$PARALLEL_KEY" | gcloud secrets versions add truestory-parallel-api-key --data-file=-
openssl rand -hex 32 | gcloud secrets versions add truestory-parallel-webhook-secret --data-file=-

make deploy-webhooks                       # first, it gives you the callback URL
make deploy-mcp
make deploy-agent
make deploy-web
```

Then reapply Terraform with the webhook URL so the scheduler can reach the sweep
endpoint, and deploy the Firestore security rules.

---

## 16. Guardrails

Non negotiable, and they appear in the product and the report as well as here.

1. **Decision support, not legal advice.** Said plainly, the legal angle is a
   strength. Left ambiguous, one sharp question ends the conversation.
2. **Never run on a living private individual.** The demo screenplay is original
   and depicts nobody real. Collision hits on living people render masked,
   always.
3. **Masking on by default.** Reveal is role gated and audited.
4. **The Litigation Set is retrospective only.** Published disputes, public
   record, no pending matters, no private individuals.
5. **The human review queue is visible in the interface.** Every real clearance
   workflow ends with an attorney. Hiding that would be a worse product.
6. **Claim only measured accuracy.** Report the eval numbers including the
   misses.
7. **Nothing marked for verification ships unverified.** Two person rule.
8. **`UNSUPPORTED` is not `FALSE`.** The epistemics are load bearing. The UI
   language and the report language preserve the distinction, because collapsing
   it is exactly the defamation this tool exists to prevent.

---

## 17. Project status

The engine runs end to end offline, 384 tests pass with no network and no spend,
and CI is green. What is built, what is only exercised offline, what is broken
and what is deliberately deferred is tracked openly in
**[docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md)**, including the defects
still open.

Two classes of fabricated finding — a real stranger's estate named on the
strength of a shared surname, and a licence requirement asserted for a work
nobody had identified — were found by reading output rather than by a test, and
both are now held by regression tests. The log says so in those words. A
clearance tool that hides its own defect history is the wrong kind of clearance
tool.

---

## 18. Licence

MIT. See [LICENSE](LICENSE).
