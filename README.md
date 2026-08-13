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
7. [The Parallel integration](#7-the-parallel-integration)
8. [Google Cloud services in runtime use](#8-google-cloud-services-in-runtime-use)
9. [Governance and privacy](#9-governance-and-privacy)
10. [Evaluation](#10-evaluation)
11. [Repository layout](#11-repository-layout)
12. [Configuration](#12-configuration)
13. [Deployment](#13-deployment)
14. [TODO: what still needs wiring](#14-todo-what-still-needs-wiring)
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

Expect something close to this:

```
  ingest    7 scenes, 24 spans  TRUE STORY ASSERTED
  claims    92 extracted, 6 opinions filtered
  ledger    13 elements (1.8x reduction)
  routing   79 subjects, projected $0.00
  verdicts  62 green · 17 amber · 7 red · 6 grey · 33 counsel
  remedies  15 verified of 17 proposed
```

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
| Sources conflict | Counsel queue, both surfaced side by side |
| Contradicted plus a living subject | Counsel queue, regardless of confidence |
| Contradiction on secondary sources only | Downgraded to unsupported |
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

**The output schemas do the heavy lifting.** Nine JSON schemas in
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
| **Pub/Sub** | Research queue and alert fan out |
| **Cloud Tasks** | Retry and backoff |
| **Cloud Scheduler** | The stale run sweep that rescues missing callbacks |
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

---

## 11. Repository layout

```
├── policy/                        the domain knowledge, as data
│   ├── routing.yaml               the RiskRouter, in its entirety
│   ├── rubric.yaml                deterministic post checks and fixed wording
│   └── jurisdictions.yaml         territory rules, post mortem publicity terms
├── schemas/                       nine Parallel output schemas
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

## 14. TODO: what still needs wiring

This is a complete base build. The pipeline runs end to end, all 95 tests pass,
and every artifact renders. What follows is what stands between this and a live
deployment, in dependency order.

### Credentials and accounts

**1. Parallel API key.**
Sign up at [platform.parallel.ai](https://platform.parallel.ai) and create a
key. Put it in `.env` as `PARALLEL_API_KEY` for local work, and in Secret
Manager as `truestory-parallel-api-key` for deployment.
Also apply for the hackathon credit allowance while registering; it is an email
and the free monthly allowance covers roughly two full feature runs.
Re verify current pricing at `docs.parallel.ai` before finalising
`policy/routing.yaml`, since several figures in the cost model date to the Task
API launch.

**2. Google Cloud project.**
Create a project, enable billing, apply the $300 trial credit **and** the $100
hackathon credit form (allow one to five business days, so do this first).
Then:
```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT
make infra-apply PROJECT=YOUR_PROJECT
```
Terraform enables all thirteen APIs, creates the buckets, the BigQuery dataset
and tables, the Pub/Sub topics, the Cloud Tasks queue, the scheduler job, the
four service accounts and the four custom roles.

**3. Webhook signing secret.**
Generate one and store it in Secret Manager as
`truestory-parallel-webhook-secret`. Until this exists the receiver **refuses
every callback**, which is deliberate: an unauthenticated endpoint that accepts
research findings lets a stranger write into a legal deliverable.

**4. Identity token verification.**
`current_principal` in [src/truestory/api/main.py](src/truestory/api/main.py)
currently trusts request headers in local mode and raises `501` otherwise.
Replace it with verification of the Cloud Run identity token, reading the role
from a signed custom claim. **Do not deploy publicly until this is done.**

**5. Firestore security rules.**
The rules are written and live in `FIRESTORE_RULES` in
[src/truestory/api/security.py](src/truestory/api/security.py). Move them to
`firestore.rules` and deploy with `firebase deploy --only firestore:rules`.
Per project isolation belongs in the rules, not only in the application.

**6. Agent Engine deployment.**
```bash
python deploy/deploy_agent_engine.py --project YOUR_PROJECT --dry-run
```
Verify the eight stage tree prints, then drop `--dry-run`. Put the returned
resource name in `.env` as `AGENT_ENGINE_RESOURCE_NAME`. Do this early rather
than late; deployment friction is easier to solve with time in hand.

### Quality and content

**7. Prompt tuning against real Gemini output.**
Every prompt is written and structured, and none has been tuned against live
model output. The two that matter most are `CLAIM_EXTRACTOR_SYSTEM`, where
atomicity and opinion classification set the ceiling on the whole system, and
`INGEST_SYSTEM`, where `REAL_PERSON_IDENTIFIABLE` recall is the hardest and
most valuable signal.

**8. Record the fixture set.**
```bash
TRUESTORY_MODE=live truestory warm-cache demo/screenplay/the_long_shadow.fountain
```
Promote the entries you want into `eval/fixtures/`, reviewing each one first
against the checklist in that directory's README. This makes the demo free,
deterministic and byte identical across takes, which removes the single largest
source of demo day fragility.

**9. Complete the ground truth labelling.**
`eval/labeled_script/ground_truth.json` is a scaffold with the correct shape and
partial entries. Two people label independently, a third adjudicates. Until
this is done the recall figures Eval A reports are **not publishable**.

**10. Verify every legal fact in the Litigation Set.**
Every case in `eval/litigation_set/cases.yaml` is marked `verify: required` and
is described in general terms on purpose. Before any of it appears in a
deliverable or on camera, confirm each against a primary source under a two
person rule. Court dockets move, and appellate posture in particular moves
fastest.

**11. Firm up the demo screenplay's element mix.**
The script is written and produces a good distribution. Confirm the seeded
claims land on the intended verdicts once prompts are tuned, since mock mode
cannot tell you that.

### Product surface

**12. Frontend live wiring.**
The overlay, evidence panel, claim dashboard, cost meter and role switcher are
all built and typed. Remaining: `npm install` in `web/`, connect the remedy
payload into the evidence panel (`selectedRemedy` is currently a placeholder in
[web/app/page.tsx](web/app/page.tsx)), and add the drag and drop upload path.

**13. Monitor path end to end.**
Provider, handles, manifest, event classification and alerting are all written.
Untested against a real Parallel Monitor callback. A pre recorded insert of a
genuine run is acceptable for the video; a staged mockup is not.

**14. Cost model verification.**
Re check every price in `Processor.usd_per_run` and the FindAll tiers against
current published pricing, then re run `truestory explain` to confirm the
projection.

### Nice to have

**15.** BigQuery vector search over the precedent corpus. The table and schema
exist; the embedding write path and retrieval do not.
**16.** Final Draft write back. The PDF redline ships; `.fdx` write back does not.
**17.** Live A2A endpoint. The AgentCard ships as a specification.
**18.** Storyboard still multimodal path. `Modality.STORYBOARD_STILL` exists and
is unused.

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
