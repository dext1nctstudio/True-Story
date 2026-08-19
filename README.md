# TRUE STORY

**A fact and rights engine for "based on a true story" productions.**

Reads a screenplay. Checks every factual claim about every real person against
the live public record. Marks each line green, amber or red with the sources
attached. Underneath, it clears every name, brand, song, artwork and location
that could trigger a lawsuit, documented to the standard insurance carriers
require before a film can be distributed. Then it keeps watching, because facts,
licences and litigation all change after the report is filed.

Built for the Agentic Cinema hackathon, Parallel track. Gemini, Google Cloud
Agent Development Kit, Vertex AI Agent Engine, and five of Parallel's six web
APIs.

> **Decision support for a clearance attorney. Not legal advice.** Every
> clearance report in this industry is reviewed by a qualified attorney before
> a policy is bound. This system automates the research and the document, not
> the judgement.

---

## Table of contents

1. [The problem](#1-the-problem)
2. [What this actually does](#2-what-this-actually-does)
3. [Quick start](#3-quick-start)
4. [Architecture](#4-architecture)
5. [The eight stages](#5-the-eight-stages)
6. [Where the domain knowledge lives](#6-where-the-domain-knowledge-lives)
   - [How a verdict is allowed to exist](#how-a-verdict-is-allowed-to-exist)
   - [Cost, in two bills](#6a-cost-in-two-bills)
   - [Four roles, four workspaces](#6b-four-roles-four-workspaces)
7. [The Parallel integration](#7-the-parallel-integration)
8. [Google Cloud services in runtime use](#8-google-cloud-services-in-runtime-use)
9. [Governance and privacy](#9-governance-and-privacy)
10. [Evaluation](#10-evaluation)
11. [Repository layout](#11-repository-layout)
12. [Configuration](#12-configuration)
13. [Deployment](#13-deployment)
14. [Build status: done and outstanding](#14-build-status-done-and-outstanding)
15. [Guardrails](#15-guardrails)
16. [Licence](#16-licence)

---

## 1. The problem

"Based on a true story" are the five most valuable words in television, and the
five most dangerous. When a production tells a story about real people, every
line of dialogue is a claim about someone's life. Get one line wrong and the
consequences are now famous: streamers have faced nine figure defamation
claims, settled suits over a single sentence, and settled others days before
trial. In each case the problem was the same thing. A statement about a real
person that nobody had checked against the record.

The existing fix is a cottage industry of a few dozen expert researchers
serving a global content machine. A feature clearance report costs one to three
thousand dollars and takes three to seven business days. Every revised draft,
every one off name change, every art department signage request generates
follow up billing. And the report is a photograph: it says nothing about what
happens to those rights over the commercial life of the title.

Three structural facts make this a real workflow rather than a hypothetical:

- **It is mandatory.** No clearance, no errors and omissions policy. No policy,
  no distribution.
- **The work is structured web research at scale.** Hundreds of independent,
  cited, confidence scored lookups about the real world.
- **The output is a document, not a chat.** The industry runs on a specific
  report format that carriers already accept.

---

## 2. What this actually does

Drop in a draft. In minutes, for a couple of dollars:

**Every factual claim about every real person is decomposed and checked.**
"A twice convicted stalker sentenced to five years" is not one claim, it is
three, and each verifies independently. That is exactly how a complaint
itemises alleged falsehoods, and it is the difference between "this scene is
risky" and "this sentence is contradicted by the record, here are the sources".

**Opinion is filtered out and never researched.** "He was a difficult man" is
protected speech. It is classified, coloured grey, and costs nothing. The most
legally motivated rule in the system is also its largest budget control.

**Unnamed characters are checked for identifiability.** Profession plus city
plus description plus relationship resolves to a real person whether or not a
name appears. Naming is not the legal trigger; identifiability is.

**A truth claim changes everything downstream.** If the production tells its
audience the story is true, every person adjacent element is escalated one full
risk tier, because courts have treated that framing itself as bearing on
whether a production acted with reckless disregard for falsity. That is one
rule in a configuration file implementing a doctrine two federal courts applied.

**Unsupported claims are counted per person, not just per line.** Amber is not
"probably fine". Amber is the category that settles: not provably false, and
therefore not defensible either. Once the density of unsupported conduct claims
about a named living person crosses a threshold, the *person* escalates.

**Fixes are proposed and then verified.** A contradicted line gets a rewrite,
the rewrite goes back through the identical research path under the identical
schema, and only a proposal that comes back verified is offered as a fix.

**And then it keeps watching.** A clearance report is a photograph. Rights are
a film. Music licences expire quietly years after delivery, depicted people
die and publicity rights change by state, new suits get filed, new records
surface. Monitors run for the commercial life of the title.

---

## 3. Quick start

Runs with **no credentials, no network and no spend**. That is the default, not
a demo mode.

```bash
git clone https://github.com/GIND123/True-Story.git
cd True-Story

make install          # pip install -e ".[dev]", and copies .env.example to .env
make pipeline         # full eight stage run over the demo screenplay
```

This is the exact output of that command on commit `79940b6`:

```
  ingest    7 scenes, 23 spans TRUE STORY ASSERTED
  claims    41 extracted, 1 opinions filtered
  ledger    13 elements (1.77x reduction)
  routing   48 subjects, projected $1.12
  verdicts  25 green · 7 amber · 3 red · 1 grey · 43 counsel
  remedies  7 verified of 7 proposed
```

The projection is what the same run would cost against live Parallel. Mock mode
itself spends nothing, and the counsel figure counts escalations and
confirmations together; the run summary separates them.

Then the rest:

```bash
make test             # 95 tests, no network, no spend
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

> **Mock mode is honest about itself.** Every finding is synthesised offline,
> clearly labelled, and carries no research value. The offline extractor has
> far lower recall than the model pass and says so. It exists so a reviewer can
> exercise the whole system in under a minute, not so the numbers look good.

---

## 4. Architecture

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

## 5. The eight stages

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

**Four of eight stages use a language model. That is the design.** The brief
asks for a deterministic multi step agent, and a legal product cannot have a
model improvising control flow. Every prompt in the system lives in one file,
[src/truestory/agents/prompts.py](src/truestory/agents/prompts.py), so the count
is visible and a fifth decision point cannot appear quietly.

| Primitive | Used for | Why not a model |
|---|---|---|
| `SequentialAgent` | The spine | Stage order is fixed by the domain |
| `ParallelAgent` | Research fan out | Concurrency is infrastructure |
| `LoopAgent` | Remedy, at most three | Termination is objective: does it verify |
| `LlmAgent` | Ingest, extract, adjudicate, propose | The only four places judgement is required |

### Two safeguards worth reading the code for

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

---

## 6. Where the domain knowledge lives

Not in prompts. In three files a clearance attorney can read, argue with, and
change without touching Python.

### `policy/routing.yaml`

```yaml
  - id: claim_negative_living
    match: { kind: claim, polarity: negative, subject_alive: true }
    tier: CRITICAL
    processor: core
    schema: claim_verification_v1
    post: { if_not_verified: NEEDS_COUNSEL }

  - id: claim_opinion
    match: { kind: claim, type: CHARACTERIZATION }
    tier: NONE
    provider: none
    note: "Defamation law protects opinion. Domain knowledge as a budget control."

escalations:
  truth_claim_framing:
    when: "project.truth_claim_framing == true"
    action: escalate_tier
    steps: 1
    applies_to: person_adjacent
```

A negative assertion about a living person is the shape of every marquee case
in this space, and it routes to the deepest processor available. Opinion routes
to nothing at all.

### `policy/rubric.yaml`

The deterministic post checks that run **after** the model, never by it:

| Condition | Action |
|---|---|
| Confidence below threshold | Counsel queue |
| Sources conflict, or the payload returned facts on both sides | Counsel queue, both surfaced side by side |
| Contradicted plus a living subject | Counsel queue, regardless of confidence |
| Contradiction without a **recognised** primary record | Downgraded to unsupported |
| Every source user generated or unattributable | Downgraded, cannot carry a verdict about a person |
| Fewer independent domains than the tier requires | Counsel queue, confidence capped |
| The model's verdict disagrees with its own research payload | Counsel queue, confidence capped |
| Any fallback evidence | Confidence capped |
| Amber density per named living person over threshold | The person escalates |

**Escalation and confirmation are counted separately.** A lawyer thinking hard
about one line is not the same workload as signing off a clean result, and
conflating them would put the entire script in the queue and save nobody any
work.

### `policy/jurisdictions.yaml`

Post mortem publicity terms range from nothing to seventy five years depending
on the state of domicile at death. The same depiction of the same deceased
person is a licence negotiation in one jurisdiction and a non issue in another,
which makes this a product surface rather than a config detail.


### How a verdict is allowed to exist

Three things stand between a research answer and a verdict on screen, and all
three are code rather than prompt text.

**1. Every citation is classified from its host.**
[`source_quality.py`](src/truestory/providers/source_quality.py) resolves a URL
to a source class — official record, registry, archive, reporting, trade,
reference, user generated — and the table wins in both directions. A
courtlistener docket the researcher called "secondary" is promoted; a Wikipedia
page it called "primary" is demoted. An unrecognised host keeps whatever was
declared and is marked unverified, so a rule can require a classified record
rather than an asserted one.

This is load bearing. Parallel's Basis citations carry a URL and excerpts and
nothing else, so before this existed every citation in a live run defaulted to
"secondary" and the rubric's `contradicted_requires_primary_source` silently
downgraded **every red line in the product** to amber.

**2. Corroboration is counted, not asserted.**
[`corroboration.py`](src/truestory/agents/corroboration.py) reports independent
domains (eTLD+1, because five pages on one site are one source), how many
recognised records are behind the finding, how many sources are user generated,
what the research payload itself concluded from its own schema fields, and
whether it returned supporting and contradicting facts at the same time.

**3. Confidence may not exceed what that supports.** The corroboration score
caps confidence before any threshold is applied, so a single tertiary source
cannot produce a 0.95 verdict however certain the model sounded.

All of it is on screen. The evidence panel shows the count of independent
sources, how many are records, the payload's own signal, and a per source badge
naming the class the host was classified as.

---

## 6a. Cost, in two bills

Research and model spend are different invoices and are never blended into one
number, because a blended figure cannot be checked against either.

| Bill | Priced | Governed by the per script ceiling |
|---|---|---|
| Parallel Task, Search, Extract, FindAll, Monitor | per run, per URL, per match, per check | yes |
| Gemini | per token, with a cached input tier | no, deliberately |

Charging model tokens against the research ceiling would silently reduce the
research a script can buy, so they are metered separately and reported side by
side.

Every rate in the product resolves from one place and is served over the API,
so nothing in the UI restates a price of its own:

```bash
curl localhost:8080/v1/pricing                    # published unit prices, with the date they were verified
curl localhost:8080/v1/runs/$RUN/cost             # research, model, cache saving, projection against actual, unit economics
curl -X POST localhost:8080/v1/estimate   -H 'content-type: application/json'   -d '{"pages":105,"drafts":4,"cache_hit_rate":0.9}'   # the pre flight calculator
```

The estimator runs the same subject density and the same processor prices the
router actually uses, so the number on the marketing surface and the number on
the meter are the same arithmetic. A redraft's model half is **not** discounted
by the cache: a rewritten draft is re read end to end whatever changed in it,
and only research, adjudication and remedy scale with the delta.

---

## 6b. Four roles, four workspaces

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

A role is also a link: `?role=truestory.producer` opens that workspace, so
"here is what the carrier sees" is a URL rather than a set of instructions.

---

## 7. The Parallel integration

Five of six APIs, each doing a distinct job.

| API | Job here | Code |
|---|---|---|
| **Task** | Core verification and clearance research, tier routed by depth | [parallel_task.py](src/truestory/providers/parallel_task.py) |
| **Search** | The interrogation path. One round trip for "why is this line red" | [parallel_search.py](src/truestory/providers/parallel_search.py) |
| **FindAll** | Set valued questions. Every entity bearing this name; every person matching this cluster | [parallel_findall.py](src/truestory/providers/parallel_findall.py) |
| **Extract** | Preservation. Registry pages captured into the evidence pack at a known timestamp | [parallel_extract.py](src/truestory/providers/parallel_extract.py) |
| **Monitor** | Living Clearance. Facts, licences and litigation after the report is filed | [parallel_monitor.py](src/truestory/providers/parallel_monitor.py) |

**Why this partner fits this product.** Every response carries citations,
reasoning, excerpts and calibrated confidence per output field, which maps onto
the `Evidence` envelope close to one to one. For a system whose output is "this
line about a real person is false", that is not a convenience feature. A verdict
without a citation is legally worthless, so a provider that cannot produce
citations is structurally disqualified from critical work by
`ResearchProvider.supports_citations`, enforced in the registry rather than left
to a reviewer to notice.

**The output schemas do the heavy lifting.** Eleven JSON schemas in
[schemas/](schemas/) shape every response, which is why the verdict comes back
with supporting and contradicting facts already separated rather than blended
into prose. `claim_verification_v1` is the workhorse, and it deliberately
distinguishes `no_record` from `contradicted`.

**Cost.** Roughly two to three dollars for a two hundred subject feature
against one to three thousand dollars and days to weeks for the manual
equivalent. The `BudgetGovernor` degrades depth before failing a run, and
critical work draws on a reserve that ordinary subjects cannot touch.

---

## 8. Google Cloud services in runtime use

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

## 9. Governance and privacy

Four roles, each mapping to a Firestore security rule **and** to the view matrix
in the application, so a role means the same thing in both places.

| Role | Sees |
|---|---|
| `truestory.counsel` | Everything, including unmasked identities. The only role that may unmask or override |
| `truestory.producer` | Verdict counts, risk posture, cost, alerts. Not the evidence |
| `truestory.writer` | Their own draft's overlay and rewrites. No cross project access |
| `truestory.underwriter` | The final package, read only and watermarked |

There is no global override role. Per project isolation lives in the Firestore
rules rather than only in application code, because an authorisation check that
exists solely in a service is one deploy away from being bypassed.

**Privacy by default.** This system's output is assertions about real people.
Built carelessly it is a defamation engine pointed at the people it protects. So
a living private individual is masked, always. The interface renders
`3 matching individuals · 4 sources · withheld pending counsel review`, which is
itself the useful signal. Revealing requires the counsel role, a stated reason,
and leaves a permanent audit record naming the principal.

---

## 10. Evaluation

Two suites, both reporting their misses.

### Eval A, the labelled script

Two people independently label every element and claim in the demo screenplay.
Disagreements are adjudicated, and the result is ground truth. Reports element
and claim recall, precision, dedup accuracy, and verdict accuracy against the
seeded claims, where we know the answer because we wrote the falsehoods
deliberately.

```bash
make eval
```

### Eval B, the Litigation Set

Reconstructed published disputes, embedded in neutral scenes, run blind. Did the
pipeline flag the specific item at issue, at what tier, with what verdict, and
does the evidence support the call.

```bash
make eval-litigation
```

**The defence side cases are scored just as heavily.** A system that flags
everything is useless, so correctly returning `CLEAR_WITH_CONDITIONS` on
expressive use that a court went on to protect matters exactly as much as
catching the failures. That is the difference between a clearance engine and a
paranoia engine.

Report honestly. A stated 0.92 beats a claimed 1.00, and every number quoted
publicly comes from the harness output rather than a summary of it.

### What these suites currently report, and why neither number is publishable

The harness runs. The numbers are not yet evidence of anything, and the table in
[section 14](#14-build-status-done-and-outstanding) treats both as outstanding
work rather than as results.

- **Eval A returns `claim_recall 0.000` and `verdict_accuracy 0.00%` today.** The
  offline extractor does not recover the six seeded claims, so every one is
  scored as a recall miss. It needs the tuned Gemini pass, and it needs the
  ground truth completed by two independent labellers rather than the scaffold
  that is committed.
- **Eval B returns 100% on ten cases, and that figure measures the routing table
  only.** `_run_case` in [eval/run_eval.py](eval/run_eval.py) calls
  `routing.match()` and the project escalations; it does not ingest the
  reconstructed scene, dispatch research, or adjudicate. The defence side
  `not_status` assertion is currently recorded as a pass without being
  evaluated. Until the reconstructions run through the full pipeline blind, this
  is a policy self test and must be described as one.

---

## 11. Repository layout

```
├── policy/                        the domain knowledge, as data
│   ├── routing.yaml               the RiskRouter, in its entirety
│   ├── rubric.yaml                deterministic post checks and fixed wording
│   └── jurisdictions.yaml         territory rules, post mortem publicity terms
├── schemas/                       eleven Parallel output schemas
├── src/truestory/
│   ├── models/                    frozen contracts, zero dependencies
│   ├── policy/                    loader, matcher, validator
│   ├── providers/                 the swap layer, eight providers
│   ├── mcp/                       clearance tool server, fourteen domain tools
│   ├── agents/                    the eight stages, and every prompt
│   ├── storage/                   Firestore, BigQuery, GCS, Secret Manager
│   ├── api/                       REST, live stream, roles and masking
│   ├── webhooks/                  signed callback receiver
│   ├── reports/                   PDF rendering, no model in the path
│   └── cli.py
├── web/                           Next.js: overlay, evidence, dashboard, meter
├── eval/
│   ├── litigation_set/cases.yaml  reconstructed published disputes
│   ├── labeled_script/            hand labelled ground truth
│   ├── fixtures/                  recorded provider responses
│   └── run_eval.py
├── demo/screenplay/               original screenplay, ours outright
├── a2a/agent_card.json            AgentCard, shipped as a specification
├── infra/                         Terraform: services, IAM, buckets, secrets
├── deploy/                        Agent Engine deployment
├── tests/                         95 tests, no network, no spend
└── docs/ARCHITECTURE.md
```

---

## 12. Configuration

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

## 13. Deployment

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

Then reapply Terraform with the webhook URL so the scheduler can reach the
sweep endpoint, and deploy the Firestore security rules.

---

## 14. Build status: done and outstanding

Audited **20 August 2026** against commit `a8d2ccf`, plus three uncommitted
files carrying the accuracy work in 14.3. Every row was checked by running the
thing rather than by reading the code, and the command that produced the
evidence is named. Where an earlier version of this section claimed something
that is no longer true, the row says so.

Since the 16 August audit the partner integration has been executed for real,
every prompt has been run against Gemini, runs survive a restart, model spend
is counted, and a class of fabricated legal findings was found and closed. The
CI row has also been corrected: it claimed green and was not.

| State | Meaning |
|---|---|
| **Done** | Built, and verified by executing it |
| **Offline only** | Built and exercised against mock or local backends. Never run against the live dependency |
| **Broken** | Present, and does not currently work |
| **Not built** | Deliberately deferred, or not started |

### 14.1 The engine

| Area | What exists | State | Evidence, or what is left |
|---|---|---|---|
| Eight stage pipeline | Ingest, claims, ledger, router, swarm, adjudicator, remedy, report, running end to end | **Done** | `truestory run demo/screenplay/the_long_shadow.fountain` produces 7 scenes, 23 spans, 41 claims, 13 elements, 48 researched subjects, 25/7/3/1 verdicts, 7 verified remedies, every artifact |
| Test suite | 95 tests, no network, no spend | **Done** | `pytest`, 95 passed |
| Domain models | Frozen contracts for spans, claims, elements, evidence, enums. The no verdict without evidence invariant is enforced in the model as well as by forced function calling | **Done** | `tests/test_evidence_invariant.py`, 18 tests |
| Policy as data | `routing.yaml` including the truth claim escalation, `rubric.yaml`, `jurisdictions.yaml`, plus a validating loader | **Done** | `python -m truestory.policy.loader --validate`, green in CI |
| Output schemas | Eleven JSON schemas, `claim_verification_v1` the workhorse | **Done** | `--validate-schemas`, green in CI |
| Provider layer | Task, Search, FindAll, Extract and Monitor over `httpx`, plus a Gemini grounded fallback, a content addressed cache and a mock. Registry resolves cache, policy, budget, health in that fixed order | **Done** | Supersedes the previous "no provider has been called against the live Parallel API". Live Task runs return real citations, 23 to 40 per claim, from Britannica, NASA and Wikipedia among others. Getting there took four fixes: a 422 on every subject because `metadata.jurisdictions` was sent as a list, results that could never arrive because a queued response waited on a webhook no local run can receive, mock fixtures answering live requests through a shared cache keyspace, and `entity_v1` citations being dropped because the provider read only Parallel's `basis` and that schema returns its sources in its own `sources` array |
| Budget governor | Depth degradation, an untouchable CRITICAL reserve, coverage warnings printed on the report front page | **Done** | `tests/test_pipeline.py`, covering degradation, reserve, exhaustion and pre spend projection |
| MCP tool boundary | Fourteen domain tools returning one uniform Evidence envelope, over HTTP and stdio | **Offline only** | `src/truestory/mcp/server.py`. The tools are exercised in process by the swarm; neither transport has been started as a server, and no MCP client has connected |
| Four language model decision points | Ingest, claim extraction, adjudication, remedy proposal. Every prompt in one file | **Done, not tuned** | All four now run against Gemini on Vertex. Adjudication was silently failing on every claim until fixed: `subject_alive` was declared as a JSON Schema union `["boolean","null"]`, which a Gemini function declaration rejects before the call leaves the machine, so every claim fell back to UNSUPPORTED and the report came out amber with no verdict behind it. Ingest and adjudication have since been rewritten for accuracy, see 14.3. Tuning against measured output has still not happened |
| Cost model | Parallel priced per task run, Gemini priced per token, metered per run | **Done** | Processor prices verified 19 August against the published Parallel rates and are correct. Gemini spend was not counted at all, so a run reporting \$0.01 had actually cost \$0.18: model tokens ran roughly 17x the research spend on a short script. `providers/model_cost.py`, metered through a context variable so concurrent runs do not blend |
| ADK wrapper | `build_adk_pipeline` maps the same eight stages onto `SequentialAgent`, `ParallelAgent` and `LoopAgent` | **Offline only** | Code is present and one to one with the local pipeline. The tree has never been constructed: not even `deploy/deploy_agent_engine.py --dry-run` has been run |

### 14.2 The product surface

| Area | What exists | State | Evidence, or what is left |
|---|---|---|---|
| REST and SSE API | Projects, runs, upload, live stream, overlay, claims, elements, remedies, register, report, CSV, PDF, apply remedy, override, unmask, review queue | **Done** | Driven as a running server throughout. Runs now survive a restart: Firestore is enabled and a completed run persists its record, claims, elements, remedies and rendered overlay, so reopening it after a restart returns the annotated script rather than a 404. Firestore had been write only, written on completion and never read back, which is why every restart presented an empty dashboard while the runs sat in the database. A run is also registered the moment it is accepted, so it appears while it works rather than only when it finishes |
| Verdict overlay UI | Docket, overlay, evidence panel, claim dashboard, counsel queue, cost meter, role switcher, drag and drop upload, run list | **Done** | `npm run build` and `next lint` both clean, and the whole surface was driven against a live mock run: upload, stream, overlay, evidence, remedy. Supersedes the previous item 12, which called the remedy payload a placeholder |
| Design system | Dark chrome around a light paper script, one accent, hairline rules, an integer type scale, no gradients and no hover lifts. Screenplay set at US Letter with a 1.5in binding margin, so a line never wraps mid sentence | **Done** | `web/app/globals.css`. Verified in a browser against a completed run |
| Artifacts | Verdict overlay JSON, claim register, E&O report as JSON and PDF, clearance log CSV, monitor manifest | **Done** | `truestory run --report`; `tests/test_pipeline.py` asserts valid CSV, a rendering PDF and a watermarked underwriter copy |
| Roles, masking, audit | Four roles, a view matrix, default masking of living private individuals, counsel only unmask with a reason, audit records | **Done** | `tests/test_security.py`, 20 tests including no global override and no leak of a masked name through serialisation |
| Webhook receiver | Signed callback receiver for task completion and monitor events, with event classification and alert dispatch | **Offline only** | Signature verification is fully tested, including replay and tampering. **No real callback has ever been received** |
| A2A AgentCard | 146 line card, served at `/.well-known/agent.json` | **Done** | Shipped as a specification by design. The live A2A endpoint remains roadmap |
| CLI | `run`, `explain`, `warm-cache`, `doctor`, `version` | **Done** | `truestory doctor` prints exactly which prerequisites are wired |

### 14.3 What was broken, and what still is

These are the rows a judge can see from outside the repository, so they come
first. The three marked fixed were repaired during this audit.

| # | Problem | Impact | State |
|---|---|---|---|
| **B1** | **CI had never been green.** Every run on `main` failed | A red badge on a public submission | **Still open, and the previous claim here was wrong.** B2 and B3 fixed lint, formatting and the Terraform parse, but the python job also runs `mypy src/truestory`, which reports **19 errors in 10 files** and fails the job. Mostly `no-any-return` in the storage and provider layers, plus missing `google.cloud.storage` stubs. Everything else is green: `pytest` 95 passed, policy and schema validation, `npm run build`, `terraform validate` |
| **B2** | `ruff check` reported 61 errors and `ruff format --check` wanted 31 files reformatted | Failed both the 3.11 and 3.12 python jobs before the tests ever ran | **Fixed.** 52 were auto fixable; the rest were 6 `N803` in the PDF helpers, 2 collapsible `if` statements, and one deliberately grouped `__all__` that now carries its reason. `ruff check` and `ruff format --check` are both clean |
| **B3** | `infra/main.tf` used `replication { auto {} }`, invalid HCL, in three places | `terraform validate` failed, so `make infra-apply` could not run and no Google Cloud resource had ever been created | **Fixed.** Expanded to multi line blocks. Terraform is not installed on the audit machine, so this is confirmed against the reported parse error rather than by a local `validate` |
| **B4** | A working `.env` pointing `GOOGLE_APPLICATION_CREDENTIALS` at one developer's absolute path, with `TRUESTORY_MODE=live` | Settings validation rejects a credential path that does not exist, so on that machine the package fails to import and nothing runs until `.env` is edited. `.env` is correctly gitignored and has never been committed, so a fresh clone is unaffected | **Open.** Keep the credential path empty and the mode `mock` in any shared `.env`, exactly as `.env.example` has it |
| **B5** | PR **#3**, 1,619 additions of live pipeline fixes and two new UI components, was unmerged | `main`, the branch a judge clones, was not the current state of the work | **Fixed.** Merged as `79940b6`. It moved the verdict mix, which is why the numbers in section 3 changed |
| **B6** | `web/package-lock.json` was out of sync with `package.json`, so `npm ci` refused to install | Hidden by the `npm ci \|\| npm install` fallback in CI, which meant every web build silently resolved dependencies afresh rather than from the lock | **Fixed.** Lockfile regenerated. `npm ci` now exits 0, and the build and lint both pass from that install |
| **B7** | **The system fabricated legal findings about real people.** An invented character, "Jonah Reed", was matched to an unrelated real person's obituary and issued: *"his estate controls his publicity rights until 2033. A license is required"*, at 0.9 confidence. Its own rationale noted the provider had concluded wrongly, and it issued the finding anyway | The worst output this system can produce. It names a real stranger's estate in a legal deliverable on the strength of a shared name, and it would send counsel chasing an estate that has nothing to do with the production | **Fixed**, see below. Verified by rerunning the same script: the character is now typed `PERSON_NAME_FICTIONAL` and no claim about any real person is made |
| **B8** | **Licence requirements were asserted for works that were never identified.** A photograph came back `work_identified: false`, no creator, no rights holder, `copyright_status: unknown`, and was issued `NEEDS_LICENSE` at 0.9. Others were cited to general law review articles about the de minimis doctrine, which describe how copyright works and say nothing about the work in hand | A licence requirement names an owner. Naming one for a work nobody located is an invented obligation, and citing background law as though the subject had been researched dresses a presumption as a finding | **Fixed.** Rerun shows zero unidentified works asserting `NEEDS_LICENSE` |

**How B7 and B8 were fixed.** Four changes, and only the first two are prompts,
because the model had already demonstrated it will not police itself here.

1. **Ingest now has a test for real versus invented.** It had none: both types
   were defined, neither was given a rule for choosing between them, and the
   surrounding instruction was *"prefer recall over precision, a false positive
   costs a cheap lookup"*. True when deciding whether to tag a span, false when
   deciding whether a person is real, where a false positive manufactures a
   legal claim about a stranger. The rule is now: default to fictional unless
   the person is independently recognisable, or the script fixes their identity
   through a verifiable role, office, event or work. A name alone never
   qualifies, and a true story framing raises the stakes rather than being
   evidence about any particular name.
2. **A source must be tied to the subject.** Matching profession, place, dates,
   relationships or events, not the name. Background law is reasoning, not
   evidence about a subject, and must not raise confidence.
3. **The schema records identity.** `real_person_v2` gained a required
   `identity_confirmed` and an `identity_basis`. `visual_copyright_v1` already
   had `work_identified` and `quote_attribution_v1` already had
   `quote_documented`; both were being answered honestly and neither was read.
4. **Two deterministic post checks, which are the actual guarantee.** A person
   reaching a consequential status without confirmed identity, or a rights
   bearing work reaching one without having been identified, is forced to
   `NEEDS_COUNSEL` with confidence capped at 0.5 and the reason stated on the
   record. The rubric is code, per the design principle that everything
   consequential happens after the model.

The result is deliberately conservative, and possibly too conservative: a real
public figure who appeared in an earlier run is now classified fictional.
Confirming the balance needs a script with genuinely real named subjects, which
is precisely what the demo screenplay cannot provide. See item 12.

### 14.4 What is outstanding, in dependency order

| # | Item | State | Why it matters | Where |
|---|---|---|---|---|
| **1** | Parallel API key, and the credit allowance email | **Done** | The key is wired and live Task runs return real citations into the overlay. Spend so far is a few dollars against no credit allowance, so the allowance is still worth chasing | `PARALLEL_API_KEY`, and Secret Manager as `truestory-parallel-api-key` |
| **2** | Google Cloud project, billing, the $300 trial and the $100 hackathon credit | **Partly done** | Project `gen-lang-client-0569749083` is live with billing: Vertex AI serves all four model calls and Firestore Native is enabled in `us-central1` and persisting runs. Terraform has still never been applied, so every other resource in `infra/` remains uncreated, and the hackathon credit has not been claimed | `make infra-apply`, unblocked by the **B3** fix |
| **3** | Webhook signing secret | **Not built** | Until it exists the receiver refuses every callback, deliberately. An unauthenticated endpoint that accepts research findings lets a stranger write into a legal deliverable | Secret Manager as `truestory-parallel-webhook-secret` |
| **4** | Identity token verification | **Not built** | `current_principal` trusts request headers in local mode and raises `501` otherwise. **Do not deploy publicly until this is done** | [src/truestory/api/main.py](src/truestory/api/main.py) |
| **5** | Firestore security rules deployed | **Not built** | The rules exist only as the `FIRESTORE_RULES` string constant. Per project isolation belongs in the rules, not only in the application | [src/truestory/api/security.py](src/truestory/api/security.py) → `firestore.rules` |
| **6** | Agent Engine deployment | **Not built** | The ADK tree has never been built, let alone deployed. Deployment friction is far cheaper to hit early | `python deploy/deploy_agent_engine.py --project … --dry-run` first |
| **7** | Prompt tuning against real Gemini output | **Not built** | `CLAIM_EXTRACTOR_SYSTEM` sets the ceiling on the entire system, and `INGEST_SYSTEM` carries the hardest and most valuable signal, `REAL_PERSON_IDENTIFIABLE` recall | [src/truestory/agents/prompts.py](src/truestory/agents/prompts.py) |
| **8** | Recorded fixtures | **Not built** | `eval/fixtures/` holds a README and nothing else, so `TRUESTORY_MODE=cached` has nothing to replay and the demo is neither free nor deterministic yet | `truestory warm-cache`, then promote reviewed entries |
| **9** | Ground truth labelling | **Broken** | The committed file is a scaffold and self declares it. Eval A therefore reports **zero claim recall** today | `eval/labeled_script/ground_truth.json`; two labellers, a third adjudicates |
| **10** | Litigation Set run end to end | **Broken** | The suite scores the routing table, not the pipeline. See [section 10](#10-evaluation). This is the differentiator that wins the track, and it is the row furthest from true | `_run_case` in [eval/run_eval.py](eval/run_eval.py) |
| **11** | Every legal fact in the Litigation Set verified | **Not built** | All ten cases are marked `verify: required`. Appellate posture moves fastest of all | `eval/litigation_set/cases.yaml`, two person rule |
| **12** | Demo screenplay subject | **Broken, and now blocking accuracy work** | Every character in `the_long_shadow.fountain` is invented, so **live research can only ever return no record**. Seeds that expect VERIFIED and CONTRADICTED cannot reach those verdicts against the real web. The build specification called for a real, safely deceased public figure with an abundant documented record for exactly this reason | Either re point the script at such a figure, with the estate posture and post mortem publicity term checked by counsel, or state plainly that the demo runs on fixtures. It also now blocks verification of the B7 fix: with no genuinely real named subject in any test script, there is no way to confirm the new conservative classifier still recognises a real person when one is present |
| **13** | Demo screenplay scale | **Not built** | 185 lines, roughly 4 pages, 7 scenes, 54 research subjects. The specification targets 25 to 30 pages and around 200 subjects, which is what makes the cost and dedup story land | `demo/screenplay/` |
| **14** | Monitor path end to end | **Offline only** | Provider, handles, manifest, classification and alerting are all written and never fired by a real event. A pre recorded insert of a genuine run is acceptable for the video; a staged mockup is not | `parallel_monitor.py`, `webhooks/main.py` |
| **15** | Cost model verification | **Done** | Parallel's five processor prices were checked against the published rates on 19 August and all five are correct. Gemini spend is now metered per run and reported next to the research figure, which is the larger of the two | `Processor.usd_per_run`, `providers/model_cost.py` |
| **16** | Cloud Tasks and Cloud Scheduler client code | **Not built** | Both are provisioned in Terraform and neither is called. `/internal/sweep` returns a canned response and sweeps nothing, so a lost callback still leaves a subject pending forever | `webhooks/main.py` |
| **17** | Async research path closed | **Offline only** | A task completion callback writes evidence to Firestore but never resumes the parked run's adjudication. In practice `_webhook_reachable()` returns false and the swarm awaits inline, which is why the demo works. The async plane is not proven | `parallel_task.py`, `webhooks/main.py` |
| **18** | Hosted URL and the three minute video | **Not built** | Both are hard submission requirements | none yet |
| **19** | Framework advisory | **Not built** | Next.js 15.1.0 carries a published advisory (CVE-2025-66478). Low risk for a demo behind an identity token, but a judge who runs `npm install` sees the warning | Bump Next and re run the build. Left alone here because a framework bump wants its own verification pass |

### 14.5 Deliberately deferred

| Item | Note |
|---|---|
| BigQuery vector search over the precedent corpus | Table and schema exist; the embedding write path and retrieval do not |
| Final Draft write back | The PDF redline ships; `.fdx` write back does not |
| Live A2A endpoint | The AgentCard ships as a specification, which is what the plan called for |
| Storyboard still multimodal beat | `Modality.STORYBOARD_STILL` exists and is unused |
| `parallel-web` SDK | Declared as a dependency and never imported. Every Parallel call is raw `httpx`, which is a legitimate integration; the unused dependency and the two docstrings that claim otherwise should be corrected |
| Licence | MIT, complete and auto detectable at the root. The build specification preferred Apache 2.0 for the patent grant. Swapping it is a one file change |

### 14.6 The three things that decide the submission

Everything above is real work. These three are the ones that change the outcome.

1. **Fix the demo subject** (item 12). A fact verification demonstration whose
   subject has no public record cannot show a green verdict with receipts, which
   is the money shot. It now blocks twice over: it is also the only way to
   confirm the B7 classifier still recognises a real person when one is there.
2. **Make Eval B a real blind run** (item 10). It is the differentiator nobody
   else can replicate, and today it measures a YAML file. It is also the only
   mechanism that would have caught B7 and B8 before a human noticed them,
   which is the strongest argument for building it.
3. **Turn CI green** (B1). One job away: `mypy` reports 19 errors and nothing
   else fails. Roughly an hour, and it is the first thing a judge sees.

Making one live Parallel call return a citation into the overlay was the
fourth, and it is done.

**A note on what B7 and B8 mean for the rest of this document.** Two classes of
fabricated finding sat in a legal tool undetected until someone read the output
closely. Both were caught by inspection, not by a test, and neither eval would
have flagged them in its current state. Nothing else in this section should be
read as evidence that the remaining verdicts are accurate; it is evidence that
the pipeline runs. Accuracy is measured by item 10 and item 9, and both are
still broken.

---

## 15. Guardrails

Non negotiable, and they appear in the product, the report and the video.

1. **Decision support, not legal advice.** Said plainly, the legal angle is a
   strength. Left ambiguous, one sharp question ends the conversation.
2. **Never run on a living private individual.** The demo screenplay is
   original and depicts nobody real. Collision hits on living people render
   masked, always.
3. **Masking on by default.** Reveal is role gated and audited.
4. **The Litigation Set is retrospective only.** Published disputes, public
   record, no pending matters, no private individuals.
5. **The human review queue is visible in the interface.** Every real clearance
   workflow ends with an attorney. Hiding that would be a worse product and a
   worse pitch.
6. **Claim only measured accuracy.** Report the eval numbers including the
   misses.
7. **Nothing marked for verification ships unverified.** Two person rule.
8. **`UNSUPPORTED` is not `FALSE`.** The epistemics are load bearing. The UI
   language and the report language preserve the distinction, because
   collapsing it is exactly the defamation this tool exists to prevent.

---

## 16. Licence

MIT. See [LICENSE](LICENSE).

The licence file is complete, unmodified and at the repository root so GitHub
detects it automatically.

> Note: the original build specification called for Apache 2.0. MIT is already
> present and satisfies the submission requirement for a complete, detectable
> open source licence. Swap it before submission only if Apache 2.0 is
> preferred for patent grant reasons.
