# Architecture

How TRUE STORY is built, and why each decision went the way it did.

The short version: a screenplay goes in, and a document comes out in which
every factual claim about every real person carries a verdict and a citation.
Between those two points sit eight stages, exactly four of which use a language
model.

---

## 1. Design principles

These are load bearing. Every structural decision below traces back to one.

| | Principle | What it forces |
|---|---|---|
| **P1** | **Determinism over discretion.** A legal product cannot have a model improvising control flow. | Four language model decision points. Everything else is a policy table, a schema, or a template. |
| **P2** | **No verdict without evidence.** A red line with no citation is legally worthless, and is itself a careless assertion about a real person. | The `Evidence` envelope is mandatory, enforced by forced function calling and by an invariant in the model layer that raises. |
| **P3** | **Vendor swappable, contract stable.** | `ResearchProvider` behind an MCP tool boundary. No agent has ever heard of Parallel. |
| **P4** | **Cost is a governed runtime resource.** | `BudgetGovernor` is a real component with a protected reserve for critical work. |
| **P5** | **Degrade honestly.** | Fallbacks are stamped, confidence is capped, and the report states its own coverage quality on the front page. |
| **P6** | **Privacy by default.** The output is assertions about real people. | Living private individuals are masked; reveal is role gated and audited. |
| **P7** | **Everything is re runnable.** Scripts change daily. | Content addressed identifiers, diff based re verification. |
| **P8** | **The claim is the atom.** | Factual claims are first class objects with their own lifecycle, not attributes hanging off an entity. |

---

## 2. The pipeline

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

Four of eight stages call a model. That ratio is the design rather than an
accident, and every prompt in the system lives in one file, `agents/prompts.py`,
so a fifth decision point cannot appear quietly.

### Why ADK workflow agents rather than one agent with tools

| Primitive | Used for | Why not a model |
|---|---|---|
| `SequentialAgent` | The spine | Stage order is fixed by the domain. Research cannot precede extraction. |
| `ParallelAgent` | Research fan out | Concurrency is infrastructure, not a judgement. |
| `LoopAgent` | Remedy, at most three | Termination is objective: does the proposal verify. |
| `LlmAgent` | Ingest, extract, adjudicate, propose | The only four places judgement is genuinely required. |

When asked how we know a run is reproducible, the answer is to point at the
tree.

### Stage by stage

**1. IngestAgent.** Screenplay to typed spans. Chunks on `INT.` and `EXT.`
headings, the most reliable structural boundary any industry format has, with
one scene of overlap. Deliberately no document AI service: Gemini's native PDF
and multimodal understanding parses screenplay structure better, and dropping
the service removed a dependency, a failure mode and a line item at once.

Also runs the project level pass that sets `truth_claim_framing`. One boolean,
and it changes the risk tier of every person adjacent subject in the script.

**2. ClaimExtractor.** The heart of the product. Decomposes person and event
spans into atomic, independently verifiable claims. Two rules carry the stage:
*atomicity*, which is what lets the overlay light one line rather than one
scene, and *opinion filtering*, which is both the most legally motivated rule in
the system and the largest single budget control.

**3. LedgerAgent.** Deterministic, and the hardest engineering in the build.
Naive extraction on a feature yields two thousand spans; the ledger collapses
them to a few hundred real subjects. Screenplay cue blocks hand us half the
coreference problem already solved, because an all capitals name above dialogue
is the format stating unambiguously that these tokens name one character.

**4. RiskRouter.** A lookup against `policy/routing.yaml`. Zero model. This is
where the domain knowledge is legible: the truth claim escalation is one rule in
a configuration file implementing a doctrine two federal courts applied.

**5. ResearchSwarm.** Bounded fan out over the tool layer, metered by the
budget governor, streamed to the UI as results land. Depth decides transport:
lite and base await inline, which keeps the on camera run synchronous, while
core and above dispatch with a webhook and park state in Firestore.

**6. Adjudicator.** Forced function calling means the model is structurally
incapable of emitting a verdict without evidence identifiers. Everything
consequential happens *after* it, in the deterministic post checks.

**7. RemedyLoop.** Propose a fix, send it back through the same research path
under the same schema, adjudicate it under the same rubric, and only then
present it as a fix. This closed loop is what separates the system from a
research wrapper.

**8. ReportAgent.** Templated, no model. A document that counsel reviews and an
underwriter relies on must render identically from identical data every time.

---

## 3. Layering

```
api / webhooks / cli        service tier, thin
  -> agents                 ADK orchestration, eight stages
    -> mcp                  domain tool boundary
      -> providers          ResearchProvider registry, vendor swappable
        -> models           frozen dataclasses, the contracts
          -> policy         routing table, rubric, jurisdictions
```

Nothing imports upward. `models` and `policy` have no dependency on Google
Cloud, on Parallel, or on a web framework, which is why the whole pipeline runs
offline against fixtures.

---

## 4. The tool boundary

Agents see verbs from the clearance trade, never vendor endpoints:

```
verify_factual_claim        attribute_quote           check_person_collision
check_person_identifiability  check_entity_registration  check_trademark_status
check_music_rights          check_publicity_rights    check_visual_copyright
check_public_domain         enumerate_matching_entities  capture_evidence_page
watch_subject               check_entity
```

A tool named `parallel_task_run` couples the agent to a vendor. A tool named
`verify_factual_claim` couples it to the problem, and the second survives a
vendor change. It also produces better tool selection, because the name states
the purpose rather than the transport.

**On Parallel's hosted MCP servers:** they are OAuth based and built for
interactive clients, which makes them excellent for developer exploration and
wrong for a two hundred subject fan out under budget governance. This project
uses the SDK inside its own MCP server, where retries, idempotency keys,
concurrency caps and the reserve are ours to control.

---

## 5. Provider selection

Four checks, fixed order, auditable at every step:

```
cache hit        -> serve for nothing
routing policy   -> which provider and depth this subject deserves
budget governor  -> degrade depth rather than fail the run
provider health  -> fall back, and stamp the fallback
```

| Capability | Mechanism |
|---|---|
| Change vendor without touching agent code | Edit `routing.yaml`. Agents see only tool names. |
| Develop at zero cost | `mock` and `cached` |
| Free, deterministic demo recording | Warm once, then every take is free and byte identical |
| Survive an outage or rate limit | Health check, fall back to grounded, stamp `is_fallback` |
| Survive budget exhaustion | `resolve()` walks core to base to lite; critical draws on a reserve |

### The five Parallel APIs, each doing a distinct job

| API | Job |
|---|---|
| **Task** | The core verification and clearance research, tier routed by processor depth |
| **Search** | The interrogation path. One round trip, sub five seconds, for "why is this line red" |
| **FindAll** | Set valued questions. Every registered entity bearing this name; every real person matching this attribute cluster |
| **Extract** | Preservation. Registry pages and dockets captured into the evidence pack at a known timestamp |
| **Monitor** | Living Clearance. Facts, licences and litigation change after the report is filed |

Every response carries citations, reasoning, excerpts and calibrated confidence
per field, which maps onto the `Evidence` envelope close to one to one. For a
product whose output is "this line about a real person is false", that is not a
convenience. It is the product.

---

## 6. The rubric

The Adjudicator produces a verdict. `policy/rubric.yaml` decides whether the
machine gets the last word, and it runs as plain code over the model's output.

| Condition | Action |
|---|---|
| Confidence below threshold | Counsel queue |
| Sources conflict | Counsel queue, both surfaced side by side |
| Contradicted plus a living subject | Counsel queue, regardless of confidence |
| Contradiction resting only on secondary sources | Downgraded to unsupported |
| Any fallback evidence | Confidence capped |
| Critical tier returning clean | Confirmation pass before it renders green |
| Amber density per named living person above threshold | The *person* escalates, not just the line |

**The amber density rule deserves its own paragraph.** Amber is not "probably
fine". Amber is the category that settles: not provably false, and therefore
not defensible either. A production can defend a true statement and can cut a
false one; it can do neither with a scene the record cannot speak to. So the
system counts unsupported claims per named living person and escalates the
person once the density crosses.

**Escalation and confirmation are different workloads** and are counted
separately everywhere. If every verified claim landed in the lawyer's queue,
the queue would be the whole script and the tool would have saved nobody any
work.

---

## 7. State

| Store | Contents | Why |
|---|---|---|
| Firestore | Runs, elements, claims, evidence, monitors, review queue | Low latency reads, and real time listeners drive the live stream for free |
| BigQuery | Cost telemetry, eval results, precedent corpus | Every unit economics figure is a query, not an estimate. Vector search over past adjudications is precedent retrieval |
| GCS | Scripts, captured evidence pages, reports | Blob storage with a seven year retention matching the errors and omissions claims tail |
| Secret Manager | Research key, webhook signing secret | Never an environment variable, never the repository, never an image |

```
/projects/{id}
/projects/{id}/runs/{run_id}
/projects/{id}/runs/{run_id}/{elements,claims,evidence}/{id}
/projects/{id}/monitors/{monitor_id}
/review_queue/{item_id}
/audit/{record_id}
```

Every backend has an offline twin with an identical interface, which is why CI
needs no cloud project at all.

---

## 8. Governance

Four custom roles, each mapping to a Firestore security rule *and* to the view
matrix in the application, so a role means the same thing in both places.

| Role | Sees |
|---|---|
| `truestory.counsel` | Everything, including unmasked identities and full evidence. The accountable human, and the only role that may unmask or override |
| `truestory.producer` | Verdict counts, risk posture, cost, alerts. Not the evidence |
| `truestory.writer` | Their own draft's overlay and rewrites. No cross project access |
| `truestory.underwriter` | The final package, read only and watermarked. An external party |

There is no global override role. Counsel is scoped to assigned projects like
everyone else.

Per project isolation lives in the Firestore rules rather than only in
application code, because an authorisation check that exists solely in a
service is one deploy away from being bypassed.

---

## 9. Privacy

Built carelessly, this system is a defamation engine pointed at exactly the
people it exists to protect. So:

1. Living private individuals are **masked by default**. Stored, never
   displayed. The UI renders "three matching individuals, four sources,
   withheld pending counsel review", which is itself the useful signal.
2. Reveal requires the counsel role, a stated reason, and leaves a permanent
   audit record naming the principal.
3. No masked identity enters a generated artifact without explicit release.
4. The demo subject is invented and the demo surfaces no real person at all.

---

## 10. Failure modes

| Failure | Detection | Response |
|---|---|---|
| Provider rate limited | 429 | Backoff; sustained, fall back and stamp it |
| Low confidence | Below rubric threshold | Counsel queue |
| Sources conflict | Post check | Counsel queue, both shown |
| Budget exhausted | Governor | Degrade depth; critical reserve intact; report carries a coverage warning |
| Webhook never arrives | Scheduler sweep | Poll once, then mark research failed and escalate |
| Model safety block on violent content | Safety response | Retry adjusted, then flag the scene for manual breakdown. Never skip silently |
| Extraction misses | Eval recall | Reported as a number, not hidden |

The last two matter most. A silently skipped scene is a hole in a legal
document that looks complete, which is worse than a report that admits its own
gap.

---

## 11. Observability

Every `Evidence` record carries cost, latency, provider and cache status, so
observability is not instrumentation bolted on. It is the same data the report
needs, routed to a second destination.

- Live cost meter, ticking in cents
- Cost per script, per claim type, per tier
- Cache hit rate, which is the draft over draft argument measured rather than claimed
- Fallback rate, which feeds the report's own coverage statement
- Counsel escalation rate, the number a studio buyer asks about first

---

## 12. Deployment

| Component | Runtime | Note |
|---|---|---|
| `TrueStoryPipeline` | Vertex AI Agent Engine | Warm minimum instances through judging |
| `clearance-tool-server` | Cloud Run | Concurrency 80 |
| Webhook receiver | Cloud Run | Separate service. Must stay up while the pipeline idles |
| Web app | Cloud Run | Server sent events |
| Queue, retry, sweep | Pub/Sub, Cloud Tasks, Cloud Scheduler | Free tier friendly |

Google Cloud services in genuine runtime use: Vertex AI, Agent Engine, Cloud
Run, Pub/Sub, Cloud Tasks, Cloud Scheduler, Firestore, BigQuery, Cloud Storage,
Secret Manager, Cloud IAM, Cloud Logging and Cloud Trace. Each is created in
`infra/` and called in code.

---

## 13. Protocol placement

> ADK for orchestration, MCP for tools, A2A at the boundary. Each protocol
> where it belongs.

**ADK** is the core because stage order, concurrency and loop termination are
all properties of the domain rather than decisions a model should make.

**MCP** sits at the tool boundary, which buys vendor swappability, a test seam,
and better tool selection.

**A2A** belongs only at organisational boundaries: an insurer, a studio or a
law firm agent calling this system from outside our trust boundary, and
`CounselAgent` as the external escalation peer. Using it for internal control
flow would add latency and buy nothing. In this build the AgentCard ships as a
documented specification at `a2a/agent_card.json`.

---

## 14. Reading the code

Start here, in this order:

1. `policy/routing.yaml` — the domain knowledge, in one readable file
2. `src/truestory/models/enums.py` — the vocabulary everything else uses
3. `src/truestory/models/evidence.py` — the central contract
4. `src/truestory/agents/pipeline.py` — the eight stages wired together
5. `src/truestory/agents/adjudicator.py` — where the safeguards actually live
6. `src/truestory/agents/prompts.py` — all four model decision points, in one place
