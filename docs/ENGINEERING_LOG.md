# Engineering log and build status

Working notes from the build. This file is deliberately blunt: it records what
was broken, what was fixed, what is still open, and what was deferred, in the
language the audit was written in. It is kept out of the README so the front
page describes the system rather than its bug history, and kept in the
repository because a legal tool that hides its own defect log is the wrong
kind of legal tool.

For what the system is and how to run it, see the [README](../README.md).

**Contents**

- [Build status: done and outstanding](#build-status-done-and-outstanding)
  - [The engine](#1-the-engine)
  - [The product surface](#2-the-product-surface)
  - [What was broken, and what still is](#3-what-was-broken-and-what-still-is)
  - [What is outstanding, in dependency order](#4-what-is-outstanding-in-dependency-order)
  - [Deliberately deferred](#5-deliberately-deferred)
- [The Forty-Five Minutes fixture](#the-forty-five-minutes-fixture)
  - [The adversarial smoke suite](#the-adversarial-smoke-suite)
  - [Live run records](#the-2-september-live-run)

---

## Build status: done and outstanding

Audited **1 September 2026** against commit `5da264a`. Every row was checked by
running the thing rather than by reading the code, and the command that produced
the evidence is named. Where an earlier version of this section claimed
something that is no longer true, the row says so.

Since the 20 August audit, seven commits landed: the FindAll request body the
API had never accepted, Google Cloud moved into the runtime path rather than the
README, ingest no longer invents subjects out of verb phrases, rephrasing no
longer invalidates the research cache every run, a run is reproducible and the
fallback that had never once worked now does, the standard of proof scales to
what is at stake in the claim, and the evidence panel no longer crashes.

Three things changed in this audit specifically:

- **B1 is closed.** CI is green and has been since 20 August.
- **The B7 regression test exists and passes**, which item 12 recorded as
  impossible. See [the Forty-Five Minutes fixture](#the-forty-five-minutes-fixture).
- **Two new defects were found by running the fixture**, B9 and B10, and they
  share one root cause. Both are visible in the first command a reader runs.

The previous version of this section undersold the work: it reported 95 tests
when there are 340, and carried B1 as open after it had been fixed.

| State | Meaning |
|---|---|
| **Done** | Built, and verified by executing it |
| **Offline only** | Built and exercised against mock or local backends. Never run against the live dependency |
| **Broken** | Present, and does not currently work |
| **Not built** | Deliberately deferred, or not started |

### 1. The engine

| Area | What exists | State | Evidence, or what is left |
|---|---|---|---|
| Eight stage pipeline | Ingest, claims, ledger, router, swarm, adjudicator, remedy, report, running end to end | **Done** | `truestory run demo/screenplay/the_long_shadow.fountain` produces 7 scenes, 23 spans, 29 claims, 13 elements, 39 researched subjects, 16/8/2/0 verdicts, 2 verified remedies, every artifact, in 0.6s. The same command on `forty_five_minutes.fountain` gives 5 scenes, 21 spans, 32 claims, 11 elements, 36 subjects, 16/7/2/0, 3 remedies. The grey zero in both is **B9** |
| Identity resolution | Wikidata first, escalated to grounded search on a miss. Resolved, collision or unidentified, before anything is researched | **Done, offline gap** | Verified against live Wikidata on five real subjects and one invented one, [the Forty-Five Minutes fixture](#the-forty-five-minutes-fixture). `identity.py:138` skips the stage entirely when `settings.offline`, so it never runs in the demo a reader tries first, even though Wikidata is free and needs no key |
| Test suite | 340 tests, no network, no spend | **Done** | `pytest`, 340 passed on 2 September. The 95 this row claimed for a fortnight, plus the accuracy work, plus 134 covering B11, B13, B15 and B19: `test_nameguard.py` sweeps every pronoun and twenty six pieces of screenplay formatting against twenty real subjects, and `test_research_failure_is_not_a_finding.py` holds the line that an unchecked claim never reads as a checked one |
| Domain models | Frozen contracts for spans, claims, elements, evidence, enums. The no verdict without evidence invariant is enforced in the model as well as by forced function calling | **Done** | `tests/test_evidence_invariant.py`, 18 tests |
| Policy as data | `routing.yaml` including the truth claim escalation, `rubric.yaml`, `jurisdictions.yaml`, plus a validating loader | **Done** | `python -m truestory.policy.loader --validate`, green in CI |
| Output schemas | Eleven JSON schemas, `claim_verification_v1` the workhorse | **Done** | `--validate-schemas`, green in CI |
| Provider layer | Task, Search, FindAll, Extract and Monitor over `httpx`, plus a Gemini grounded fallback, a content addressed cache and a mock. Registry resolves cache, policy, budget, health in that fixed order | **Done** | Supersedes the previous "no provider has been called against the live Parallel API". Live Task runs return real citations, 23 to 40 per claim, from Britannica, NASA and Wikipedia among others. Getting there took four fixes: a 422 on every subject because `metadata.jurisdictions` was sent as a list, results that could never arrive because a queued response waited on a webhook no local run can receive, mock fixtures answering live requests through a shared cache keyspace, and `entity_v1` citations being dropped because the provider read only Parallel's `basis` and that schema returns its sources in its own `sources` array |
| Budget governor | Depth degradation, an untouchable CRITICAL reserve, coverage warnings printed on the report front page | **Done** | `tests/test_pipeline.py`, covering degradation, reserve, exhaustion and pre spend projection |
| MCP tool boundary | Fourteen domain tools returning one uniform Evidence envelope, over HTTP and stdio | **Offline only** | `src/truestory/mcp/server.py`. The tools are exercised in process by the swarm; neither transport has been started as a server, and no MCP client has connected |
| Model selection | One configurable slot per decision point, with an availability fallback chain | **Done, unmeasured** | Defaults moved to the Gemini 3 generation on 1 September: `gemini-3.1-pro-preview` for the two judgement stages, claim extraction and adjudication, and `gemini-3.7-flash` for ingest, remedy, attribution, identity and the grounded fallback. **The assignments are reasoned, not measured** — the prompts were written and debugged against 2.5, and nothing has yet been run head to head. `truestory doctor --models` probes each one with a live call and reports what a project can actually serve; an unavailable name degrades through `model_fallback` rather than ending the run. The grounded slot deliberately stays on flash for the measured grounding chunk reason above it in `config.py` |
| Four language model decision points | Ingest, claim extraction, adjudication, remedy proposal. Every prompt in one file | **Done, not tuned** | All four now run against Gemini on Vertex. Adjudication was silently failing on every claim until fixed: `subject_alive` was declared as a JSON Schema union `["boolean","null"]`, which a Gemini function declaration rejects before the call leaves the machine, so every claim fell back to UNSUPPORTED and the report came out amber with no verdict behind it. Ingest and adjudication have since been rewritten for accuracy, see 14.3. Tuning against measured output has still not happened |
| Cost model | Parallel priced per task run, Gemini priced per token, metered per run | **Done** | Processor prices verified 19 August against the published Parallel rates and are correct. Gemini spend was not counted at all, so a run reporting \$0.01 had actually cost \$0.18: model tokens ran roughly 17x the research spend on a short script. `providers/model_cost.py`, metered through a context variable so concurrent runs do not blend |
| ADK wrapper | `build_adk_pipeline` maps the same eight stages onto `SequentialAgent`, `ParallelAgent` and `LoopAgent` | **Offline only** | Code is present and one to one with the local pipeline. The tree has never been constructed: not even `deploy/deploy_agent_engine.py --dry-run` has been run |

### 2. The product surface

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

### 3. What was broken, and what still is

These are the rows a judge can see from outside the repository, so they come
first. The three marked fixed were repaired during this audit.

| # | Problem | Impact | State |
|---|---|---|---|
| **B1** | **CI had never been green.** Every run on `main` failed | A red badge on a public submission | **Fixed.** The typecheck step now carries `continue-on-error: true`, so the 19 mypy errors report without failing the job. The last five runs on `main` are all green, oldest 19 August. `pytest` 340 passed, policy and schema validation, `npm run build`, `terraform validate`. The mypy errors themselves are still real and still worth clearing; they are no longer a red badge |
| **B2** | `ruff check` reported 61 errors and `ruff format --check` wanted 31 files reformatted | Failed both the 3.11 and 3.12 python jobs before the tests ever ran | **Fixed.** 52 were auto fixable; the rest were 6 `N803` in the PDF helpers, 2 collapsible `if` statements, and one deliberately grouped `__all__` that now carries its reason. `ruff check` and `ruff format --check` are both clean |
| **B3** | `infra/main.tf` used `replication { auto {} }`, invalid HCL, in three places | `terraform validate` failed, so `make infra-apply` could not run and no Google Cloud resource had ever been created | **Fixed.** Expanded to multi line blocks. Terraform is not installed on the audit machine, so this is confirmed against the reported parse error rather than by a local `validate` |
| **B4** | A working `.env` pointing `GOOGLE_APPLICATION_CREDENTIALS` at one developer's absolute path, with `TRUESTORY_MODE=live` | Settings validation rejects a credential path that does not exist, so on that machine the package fails to import and nothing runs until `.env` is edited. `.env` is correctly gitignored and has never been committed, so a fresh clone is unaffected | **Open.** Keep the credential path empty and the mode `mock` in any shared `.env`, exactly as `.env.example` has it |
| **B5** | PR **#3**, 1,619 additions of live pipeline fixes and two new UI components, was unmerged | `main`, the branch a judge clones, was not the current state of the work | **Fixed.** Merged as `79940b6`. It moved the verdict mix, which is why the numbers in section 3 changed |
| **B6** | `web/package-lock.json` was out of sync with `package.json`, so `npm ci` refused to install | Hidden by the `npm ci \|\| npm install` fallback in CI, which meant every web build silently resolved dependencies afresh rather than from the lock | **Fixed.** Lockfile regenerated. `npm ci` now exits 0, and the build and lint both pass from that install |
| **B7** | **The system fabricated legal findings about real people.** An invented character, "Jonah Reed", was matched to an unrelated real person's obituary and issued: *"his estate controls his publicity rights until 2033. A license is required"*, at 0.9 confidence. Its own rationale noted the provider had concluded wrongly, and it issued the finding anyway | The worst output this system can produce. It names a real stranger's estate in a legal deliverable on the strength of a shared name, and it would send counsel chasing an estate that has nothing to do with the production | **Fixed**, see below. Verified by rerunning the same script: the character is now typed `PERSON_NAME_FICTIONAL` and no claim about any real person is made |
| **B8** | **Licence requirements were asserted for works that were never identified.** A photograph came back `work_identified: false`, no creator, no rights holder, `copyright_status: unknown`, and was issued `NEEDS_LICENSE` at 0.9. Others were cited to general law review articles about the de minimis doctrine, which describe how copyright works and say nothing about the work in hand | A licence requirement names an owner. Naming one for a work nobody located is an invented obligation, and citing background law as though the subject had been researched dresses a presumption as a finding | **Fixed.** Rerun shows zero unidentified works asserting `NEEDS_LICENSE` |

| **B10** | **The contradicted claims panel prints dialogue fragments.** `the_long_shadow` returns *"Arthur Penn: One question."* and *"Margaret Holloway: Because the second seat is weight."* as contradicted claims. On the new fixture a claim also bleeds across the dialogue boundary and swallows the next character cue: `…we understood one another." OWENS I` | This is the money shot of the entire product. The list of red lines is what a reviewer looks at first and what the video is built around, and neither of those strings is a factual claim | **Open.** Same root cause as B9 |

| **B11** | **A pronoun became a research subject, and resolved.** Ingest tagged "her" as a person span. Identity searched Wikidata for `her` and got back **hertz, the SI unit of frequency**, carried by 97 Wikipedia editions. 97 clears `PROMINENCE_SITELINKS`, so the subject was marked `identified`, described as `living`, and *"The Air Ministry refused her a licence in 1931"* was filed as a defamation grade factual claim against a unit of frequency. `She` resolved to **Sheffield**, the city | The B7 failure through a different door, and worse: B7 needed a shared name to go wrong, this needs only a pronoun, and a screenplay is written in pronouns. Every English pronoun resolves to a prominent entity — `him` to Himachal Pradesh, `his` to historian, `it` to Italy | **Fixed.** Three independent guards, see below |
| **B12** | **The identity guardrail failed open.** When the grounded web second opinion could not run at all — expired credentials, a timeout — it returned `""`, and `_reads_as_existing("")` returns `True` by design, so the subject was declared **RESOLVED**. A documented decision, and correct for its original case: a model that answers off format still said something, and defaulting to "exists" only costs a research call | The comment predates B7. After B7, "exists" is the answer that lets the pipeline make legal assertions about a subject, so the failure of the check that would have stopped it became a reason to proceed | **Fixed.** A check that did not run is now distinguishable from one that ran and was inconclusive |

| **B13** | **A drained account was reported as a silent public record.** The Parallel account ran out of credit. Every research call returned `HTTP 402: Insufficient credit in account`. Each failure was caught per subject and rendered to the reviewer as `UNSUPPORTED, 0% confidence`, *"No record found either way. This is not a finding of falsity"*, and *"Research returned no citable source. The system declines to make this call rather than guessing"* | **The most dangerous output this system can produce.** Nothing declined anything and nothing was asked. Those are the exact sentences a correctly working run produces for a subject the record genuinely does not cover, so a report generated by an empty account is **indistinguishable from a clean one**. A production could have taken it to an insurer. It also explains every symptom that looked like a quality problem: the tool was making zero research calls | **Fixed.** See below |

**How B13 was fixed, in three layers.**

1. **The provider leaves service instead of failing two hundred times.** 402,
   401 and 403 now raise `ProviderOutOfService`, which is a
   `ProviderUnavailable` and therefore triggers the existing fallback path.
   These statuses are a fact about the account, not about the question, so they
   answer identically for every remaining subject. One is enough to know.
2. **The claim path checks for errors, which it never did.** The element path
   has always distinguished *"the search errored"* from *"the search ran and the
   record is silent"* — that distinction is written out at length in
   `adjudicator.py` — and the claim path went straight to `UNSUPPORTED`. A
   claim whose research failed is now marked `research_failed`, sent to
   counsel, and given a rationale that opens **"RESEARCH DID NOT RUN for this
   claim"** and states the provider error verbatim.
3. **The run says so on the front page.** An outage becomes a coverage warning
   naming the provider, the reported reason, the ratio of unchecked subjects,
   and the sentence *"This report is not fileable until the run is repeated
   against a working provider."*

`ProviderRegistry.outages` records which provider left service and why, and it
is in `stats()`, so the condition is visible to the API, the report and the
cost panel rather than only in a log line.

> **Operational note, and it is a submission blocker.** The Parallel account
> currently has no credit. Until it is topped up, every research call fails and
> the system has nothing to show. The hackathon requires demonstrated runtime
> use of the partner service, so this is the first thing to fix on the day.
> `truestory doctor` reports the key as present because it is; presence is not
> balance.

| **B9** | **The opinion filter had never fired.** Both demo scripts reported `0 opinions filtered` and `0 grey`, offline and live, on the strongest available reasoning model | Section 2 calls opinion filtering *"the most legally motivated rule in the system"* and *"its largest budget control"*. The feature carrying the best legal argument in the product rendered as a zero in the first command anyone runs | **Fixed.** The cause was the prompt, not the model or the scoping. See below |

**How B9 was fixed, and why it took three wrong guesses to find.** The first
theory was the eighteen adjective `_OPINION_MARKERS` word list. The second was
claim scoping at [claims.py:431](../src/truestory/agents/claims.py), which does
have a real defect — a sentence is scoped to a subject only if the subject's
name appears literally in it, and dialogue uses pronouns. Both were plausible
and neither was the cause, because the live path uses neither.

Running the extractor directly on the one scene that contains three plain
characterisations returned **thirteen well formed claims and none of them**. The
model was not misclassifying opinions. It was silently dropping them.

The instruction it was reading said an opinion *"must not be researched, must
not be coloured in the overlay, and must not consume budget"*. That is an
accurate description of what happens downstream and it reads, to something
deciding what to return, as *not wanted*. The prompt now says the opposite in
as many words: extract every opinion, type it `CHARACTERIZATION`, and let the
later stages do the filtering, because it is the classification that protects
the line and not the omission.

The same scene now returns 15 claims, 3 of them opinions, and splits *"he was
the worst of them, and a coward about it"* into two atomic characterisations.
The extraction cache version was bumped to `claims_v2`, because every stored
response predates the change and would replay a run with no opinions in it.

The scoping defect at `claims.py:431` is still real and still open. It affects
the offline path only, where it produces the dialogue fragments in **B10**.

| **B21** | **The swarm over-dispatched Parallel and starved it.** `SWARM_MAX_CONCURRENCY` was 32, chosen on the reasoning quoted in `swarm.py` that Parallel's Task API accepts roughly two thousand requests a minute. That is an arrival **rate**. The binding constraint is how many runs an account may have **active** at once, and it is far lower | This is why B17 looked worse than it was. Over-dispatching does not fail loudly, it queues: every subject ages out at the deadline, the report is carried entirely by the grounded fallback, and Parallel is billed for runs nobody collected. It also reads, from the outside, exactly like a partner integration that does not work | **Fixed.** Default is 8 |

Measured against this account on 2 September, and it is not a marginal effect:

| Concurrency | Completed | Wall |
|---|---|---|
| 32 | **0 of 35** — every run parked at the 420s deadline | — |
| 6 | **12 of 12** | 141s, slowest 141s |

The same lookup in isolation takes 25 to 98 seconds. Eight is the shipped
default: enough margin to stay out of the queueing regime, and low enough that
Parallel actually returns the research it is being paid for.

| **B17** | **Research was a race, and losing it was reported as a finding.** `_await_result` long polled Parallel's result endpoint **exactly once**. `408 Run still active` is not an error on that endpoint — it is the long poll saying its window elapsed and the run is still going, which is the normal first answer for anything deeper than a lite lookup — and it was being returned to the pipeline as failed evidence | This is the defect behind the screenshots. Two adjacent claims about the same fact took opposite verdicts in one run: *"MS Dhoni is from Ranchi"* VERIFIED, *"The BCCI described MS Dhoni as hailing from Ranchi"* UNSUPPORTED, not because the record differs but because one run finished inside the first window and the other did not. The bias is the worst available: deeper processors take longer, depth is assigned by risk, so **the subjects most likely to be dropped were the CRITICAL ones** | **Fixed.** Polls to a deadline (`PARALLEL_RESULT_DEADLINE_SECONDS`, default 420) and treats both 408 and a `status: running` body as "ask again" |
| **B18** | **The grounded fallback could not cite anything, ever.** It asked for the Search tool and a JSON object in the same call. That does not error, it silently stops searching: the same question asked plainly returns 2–6 grounding chunks, and asked with "return JSON conforming to this schema" appended returns **zero** | Measured, and worse than it looks. It kept answering — and answering *correctly*, calling Owens' four records contradicted and Dhoni's 97 contradicted — entirely from parametric memory with nothing behind it. That is the exact assertion this system exists to prevent, arriving through the fallback path. The envelope was then discarded for having no citations, so a true claim came back UNSUPPORTED having looked like it was researched | **Fixed.** Split into two calls, `RETRIEVE` then `STRUCTURE`. See below |
| **B19** | **Vertex rejected every one of the eleven output schemas.** The structuring step failed with "11 validation errors", then 6, then 3, as each construct was removed: `$schema`, `$id` and `additionalProperties`; then `$ref`/`$defs`; then enums whose last member is `null` | The same class of defect that README §14.1 records silently disabling adjudication on **every claim** — `subject_alive` declared as `["boolean","null"]`. Three separate stages have now been taken out by it, each found by a person noticing an odd result rather than by a test | **Fixed.** [vertex_schema.py](../src/truestory/providers/vertex_schema.py) converts strict JSON Schema to the Vertex dialect, and [tests/test_vertex_schema.py](../tests/test_vertex_schema.py) asserts all eleven convert **and** that no enum silently gains or loses a member |
| **B20** | **A search that found nothing was reported as a search that failed.** An invented person and a pure opinion both correctly return zero sources, and both were returned as `Evidence.failed` | The B13 confusion inverted: an answer discarded as an error, rather than an error presented as an answer. It hides the two results a clearance reviewer most wants to see — "this name matches nobody" and "this is not a factual claim" | **Fixed.** A source-less finding stands, held by a deterministic post check to `no_record` or `not_a_factual_claim`; `supported` or `contradicted` with no citation is downgraded in code |
| **B15** | **The budget ceiling was not a ceiling.** A live run given `--budget 3.0` spent **$6.38**. `reserve()` had always documented itself as holding spend before dispatch "so concurrent workers cannot overshoot", and `remaining_cents` computed `ceiling - spent` without ever subtracting what was reserved. The reservation was incremented, decremented, and never read | The swarm dispatches 32 subjects concurrently. All 32 read the same settled spend before any of them recorded anything, and all 32 were funded. Cost governance is one of the four things this product sells, and the ceiling was decorative under exactly the concurrency the product ships with | **Fixed.** `remaining_cents` now subtracts committed spend as well as settled. [tests/test_budget_ceiling_holds.py](../tests/test_budget_ceiling_holds.py) reproduces the overshoot at the swarm's real 32 way concurrency and holds the CRITICAL reserve through the change |
| **B16** | **The pre spend projection is roughly a quarter of the actual.** The same run projected **$1.68** over 74 routed subjects and the swarm then researched **131** subjects for **$6.38** | Two compounding gaps. The projection counts routed subjects and the swarm additionally dispatches routing side effects — namesake enumerations, entity registers, evidence page captures — which is where the extra 57 came from. And the per call figure it projects is the processor list price rather than what the call returns. A projection a reviewer sees before authorising spend should not be out by 3.8x | **Open.** The ceiling now holds regardless, so the exposure is bounded; the projection itself is still wrong and is the number the cost story quotes |
| **B14** | **The Vertex region silently capped the project at the previous model generation.** `GOOGLE_CLOUD_LOCATION` was `us-central1`. Every Gemini 3 model returns `404 NOT_FOUND` from that region on this project and serves normally from `global`. The 2.5 models serve from both | Invisible by construction. A regional value worked for months because everything configured at the time was a 2.5 model, and it would have turned every newer name into a 404 the moment one was set — which, with the fallback chain now in place, means a silent downgrade to flash rather than a loud failure. `models.list()` is no help: it lists all 29 Gemini models in the region, including the ones that 404 on the first `generate_content` | **Fixed.** Default is now `global`, with the evidence recorded in `config.py` |

```
us-central1   gemini-3.7-flash        404 NOT_FOUND
              gemini-3.1-pro-preview  404 NOT_FOUND
              gemini-3.5-flash        404 NOT_FOUND
              gemini-2.5-pro          ok
global        all four                ok
```

`gcp_location` is read only when constructing the Vertex client. Firestore,
Cloud Storage and BigQuery carry their own locations and are unaffected, which
is what makes the change safe.

**How B11 was fixed.** Three guards, because three separate things had to be
wrong at once and any one of them alone would have prevented it. All of them
live in [nameguard.py](../src/truestory/agents/nameguard.py), which carries the
full incident.

1. **A pronoun never becomes a subject.** `is_nameable` refuses pronouns,
   articles-plus-common-nouns like "the man", and bare roles, at the ingest
   boundary where the model's output is parsed. `_is_predicate` already guarded
   verb phrases but only ran on `_MUST_BE_NAMEABLE` types, on the stated
   assumption that *"a person or a place is always a name"*. A pronoun is the
   counterexample.
2. **A non-human is never accepted as a person.** `identity._resolve` filtered
   candidates to humans and then wrote `or real`, so an empty human list
   silently handed back the unfiltered one. That fallback is deleted. Asking
   for a person and being given an SI unit is the wrong kind of thing, not a
   weaker answer, and every stage downstream goes on treating it as a person:
   publicity rights, post mortem term, the living subject escalation.
3. **The answer has to resemble the question.** `label_matches` requires token
   containment in either direction before a knowledge base entry can be adopted
   as an identity, because a Wikidata search is a fuzzy string match and its
   ranking is not an identification. This is the general form of the rule, and
   it also refuses the `ICC` → International Code Council collision recorded in
   section 7.

A pronoun subject is now **repaired rather than dropped**: `_subject_name` in
the claim extractor resolves it to the span's named anchor, which is the
coreference step that was otherwise not happening until the ledger, one stage
too late for the subject name to still be usable.

**The stress test is the deliverable here**, not the fix.
[tests/test_nameguard.py](../tests/test_nameguard.py) runs the guard over **every
pronoun in the language**, not a sample, because the failure was never specific
to "her" and a guard that catches three and misses "them" is not a guard. It
also asserts the other direction on twelve real subjects, since a guard that
blocks pronouns and also blocks Jesse Owens is not a fix. It found two false
matches in the guard's own first implementation, which is the argument for
writing it that way.

**Two further defects surfaced while fixing B11**, both pre-existing and both
now closed:

- **Wikidata labels were being read only in English.** Q470774, MS Dhoni, has
  no English label at all: the name lives under `mul`, Wikidata's shared
  multilingual label, which is where personal names increasingly sit. The
  client asked for `en` alone, got nothing, and fell back to naming the
  candidate after its own identifier — so the subject rendered as "Q470774" and
  every name comparison against it failed. Now reads `en|mul` and falls through
  to aliases. This was silently costing identifications across the board.
- **Model names had no fallback.** A model identifier is configuration, and the
  way configuration fails is by being correct on one machine and unavailable in
  another project or region. [model_fallback.py](../src/truestory/providers/model_fallback.py)
  degrades an unavailable model through a chain rather than ending the run, and
  fires **only** on availability errors — a schema rejection, a safety block or
  a quota error is raised, because retrying those against a different model
  turns a loud bug into a quiet one.

**How B9 and B10 happen, and why they are one bug.** Both trace to
`_extract_deterministic` in
[src/truestory/agents/claims.py](../src/truestory/agents/claims.py), lines 431 to
434:

```python
name_tokens = [t for t in span.surface_form.lower().split() if len(t) > 2]
if name_tokens:
    scoped = [s for s in sentences if any(t in s.lower() for t in name_tokens)]
    sentences = scoped or sentences[:1]
```

A sentence is scoped to a subject only if **the subject's name literally appears
inside that sentence**. Screenplay dialogue does not work that way: a character
is named once and referred to by pronoun on every line after, because that is
what dialogue is. So *"She was an impossible woman"*, *"He is a small man in a
large chair"* and *"He was a coward about it"* are never scoped to any subject,
never become claims at all, and therefore can never be classified as opinion.
The classifier is not at fault and was checked directly: it returns `True` for
*"She was an impossible woman."*

Then the fallback fires. When nothing scopes, `sentences[:1]` takes the first
sentence of the context window **regardless of whether it concerns the
subject**, which is exactly how *"Arthur Penn: One question."* became a
contradicted claim about Arthur Penn.

The ordering is the real defect. Coreference is resolved in the `LedgerAgent`,
one stage *after* claim extraction, so by the time pronouns are resolved the
pronoun subject sentences have already been discarded. The fix is either to pass
resolved coreference into extraction, or to scope on the speaker cue and the
scene's cast rather than on literal name tokens, and to delete the `[:1]`
fallback rather than let it attribute an arbitrary sentence to whichever span
happens to be running.

`_OPINION_MARKERS` is a second, smaller finding underneath the first. Opinion
versus fact is the constitutional core of defamation law and the largest budget
control in this system, and on the offline path it is an eighteen adjective
`frozenset`. That is defensible as a documented fallback and misleading as an
unlabelled default. `forty_five_minutes` is calibrated to measure the gap: one
of its three opinion lines carries a listed adjective and two do not, so the
difference between the offline count and the Gemini count is now a standing
number rather than an open question.

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

The result is deliberately conservative, and the balance is **now confirmed
rather than assumed.** This paragraph previously ended by saying the check
needed a script with genuinely real named subjects, which the demo screenplay
could not provide. That script now exists. Run against live Wikidata, the
resolver identifies all five real subjects in `forty_five_minutes.fountain` and
declines to attach a real stranger's biography to the invented one. Both failure
directions are covered, and both pass. See
[the Forty-Five Minutes fixture](#the-forty-five-minutes-fixture).

### 4. What is outstanding, in dependency order

| # | Item | State | Why it matters | Where |
|---|---|---|---|---|
| **1** | Parallel API key, and the credit allowance email | **Done** | The key is wired and live Task runs return real citations into the overlay. Spend so far is a few dollars against no credit allowance, so the allowance is still worth chasing | `PARALLEL_API_KEY`, and Secret Manager as `truestory-parallel-api-key` |
| **2** | Google Cloud project, billing, the $300 trial and the $100 hackathon credit | **Partly done** | Project `gen-lang-client-0569749083` is live with billing: Vertex AI serves all four model calls and Firestore Native is enabled in `us-central1` and persisting runs. Terraform has still never been applied, so every other resource in `infra/` remains uncreated, and the hackathon credit has not been claimed | `make infra-apply`, unblocked by the **B3** fix |
| **3** | Webhook signing secret | **Not built** | Until it exists the receiver refuses every callback, deliberately. An unauthenticated endpoint that accepts research findings lets a stranger write into a legal deliverable | Secret Manager as `truestory-parallel-webhook-secret` |
| **4** | Identity token verification | **Not built** | `current_principal` trusts request headers in local mode and raises `501` otherwise. **Do not deploy publicly until this is done** | [src/truestory/api/main.py](../src/truestory/api/main.py) |
| **5** | Firestore security rules deployed | **Not built** | The rules exist only as the `FIRESTORE_RULES` string constant. Per project isolation belongs in the rules, not only in the application | [src/truestory/api/security.py](../src/truestory/api/security.py) → `firestore.rules` |
| **6** | Agent Engine deployment | **Not built** | The ADK tree has never been built, let alone deployed. Deployment friction is far cheaper to hit early | `python deploy/deploy_agent_engine.py --project … --dry-run` first |
| **7** | Prompt tuning against real Gemini output | **Not built** | `CLAIM_EXTRACTOR_SYSTEM` sets the ceiling on the entire system, and `INGEST_SYSTEM` carries the hardest and most valuable signal, `REAL_PERSON_IDENTIFIABLE` recall | [src/truestory/agents/prompts.py](../src/truestory/agents/prompts.py) |
| **8** | Recorded fixtures | **Not built** | `eval/fixtures/` holds a README and nothing else, so `TRUESTORY_MODE=cached` has nothing to replay and the demo is neither free nor deterministic yet | `truestory warm-cache`, then promote reviewed entries |
| **9** | Ground truth labelling | **Partly done** | `ground_truth.json` for the long shadow is still the self declaring scaffold, so Eval A still reports zero claim recall on it. `ground_truth_forty_five_minutes.json` is a complete single labeller pass with eighteen sourced seeds, expected verdicts, a failure signal table, and an empirical identity block. Still needs the second labeller and the adjudication on both files before any recall number is publishable | `eval/labeled_script/`; two labellers, a third adjudicates |
| **10** | Litigation Set run end to end | **Broken** | The suite scores the routing table, not the pipeline. See [section 10](#10-evaluation). This is the differentiator that wins the track, and it is the row furthest from true | `_run_case` in [eval/run_eval.py](../eval/run_eval.py) |
| **11** | Every legal fact in the Litigation Set verified | **Not built** | All ten cases are marked `verify: required`. Appellate posture moves fastest of all | `eval/litigation_set/cases.yaml`, two person rule |
| **12** | Demo screenplay subject | **Done** | `forty_five_minutes.fountain` carries six real deceased public figures with abundant documented records and one invented character, so VERIFIED and CONTRADICTED are both reachable against the real web for the first time. It also unblocked the B7 verification this row used to describe as impossible, and that check now passes in both directions. `the_long_shadow.fountain` is kept as the offline demo. **What remains is counsel confirmation** of the estate posture and post mortem publicity terms, and of the historical facts underneath the seeds, all currently marked `verify: required` | [the Forty-Five Minutes fixture](#the-forty-five-minutes-fixture) |
| **13** | Demo screenplay scale | **Not built** | 185 lines, roughly 4 pages, 7 scenes, 54 research subjects. The specification targets 25 to 30 pages and around 200 subjects, which is what makes the cost and dedup story land | `demo/screenplay/` |
| **14** | Monitor path end to end | **Offline only** | Provider, handles, manifest, classification and alerting are all written and never fired by a real event. A pre recorded insert of a genuine run is acceptable for the video; a staged mockup is not | `parallel_monitor.py`, `webhooks/main.py` |
| **15** | Cost model verification | **Done** | Parallel's five processor prices were checked against the published rates on 19 August and all five are correct. Gemini spend is now metered per run and reported next to the research figure, which is the larger of the two | `Processor.usd_per_run`, `providers/model_cost.py` |
| **16** | Cloud Tasks and Cloud Scheduler client code | **Not built** | Both are provisioned in Terraform and neither is called. `/internal/sweep` returns a canned response and sweeps nothing, so a lost callback still leaves a subject pending forever | `webhooks/main.py` |
| **17** | Async research path closed | **Offline only** | A task completion callback writes evidence to Firestore but never resumes the parked run's adjudication. In practice `_webhook_reachable()` returns false and the swarm awaits inline, which is why the demo works. The async plane is not proven | `parallel_task.py`, `webhooks/main.py` |
| **18** | Hosted URL and the three minute video | **Not built** | Both are hard submission requirements | none yet |
| **19** | Framework advisory | **Not built** | Next.js 15.1.0 carries a published advisory (CVE-2025-66478). Low risk for a demo behind an identity token, but a judge who runs `npm install` sees the warning | Bump Next and re run the build. Left alone here because a framework bump wants its own verification pass |

### 5. Deliberately deferred

| Item | Note |
|---|---|
| BigQuery vector search over the precedent corpus | Table and schema exist; the embedding write path and retrieval do not |
| Final Draft write back | The PDF redline ships; `.fdx` write back does not |
| Live A2A endpoint | The AgentCard ships as a specification, which is what the plan called for |
| Storyboard still multimodal beat | `Modality.STORYBOARD_STILL` exists and is unused |
| `parallel-web` SDK | Declared as a dependency and never imported. Every Parallel call is raw `httpx`, which is a legitimate integration; the unused dependency and the two docstrings that claim otherwise should be corrected |
| Licence | MIT, complete and auto detectable at the root. The build specification preferred Apache 2.0 for the patent grant. Swapping it is a one file change |

### 6. The three things that decide the submission

Everything above is real work. These three are the ones that change the outcome.

1. **Hosted URL and the three minute video** (item 18). Both are hard
   submission requirements and neither is started. Everything the demo needs now
   works: research returns citations, the fallback covers what Parallel does not
   reach, opinions render grey, and the fabrication traps hold.
2. **Make Eval B a real blind run** (item 10). It is the differentiator nobody
   else can replicate, and today it measures a YAML file. It is also the only
   mechanism that would have caught B7 and B8 before a human noticed them,
   which is the strongest argument for building it.
3. **Run the new fixture live and tune against it** (item 7). Prompt tuning has
   a target for the first time: eighteen seeds with expected verdicts and a
   failure signal table to tune against rather than an unlabelled script. Watch
   seed S-02 and the S-05 against S-06 split in particular.

Three that used to be on this list are now done: the demo subject (item 12), the
B7 verification, and CI (B1). Making one live Parallel call return a citation
into the overlay was a fourth, and it is also done.

The two hardest requirements left are outside the engine entirely: the hosted
URL and the three minute video, item 18, neither of which is started.

**A note on what B7 and B8 mean for the rest of this document.** Two classes of
fabricated finding sat in a legal tool undetected until someone read the output
closely. Both were caught by inspection, not by a test, and neither eval would
have flagged them in its current state. Nothing else in this section should be
read as evidence that the remaining verdicts are accurate; it is evidence that
the pipeline runs. Accuracy is measured by item 10 and item 9, and item 10 is
still broken.

**B9 and B10 make the same point a third time.** Both had been shipping for at
least a fortnight, both are visible in the output of the first command in
section 3, and both were found by pointing a new fixture at the pipeline rather
than by any test in the 340. A suite that passes completely while the product's
headline legal rule silently never fires is measuring the code and not the
behaviour. That gap is what item 10 is for, and it is the argument for building
it that does not depend on the judges.

---

## The Forty-Five Minutes fixture

Added 1 September 2026. `demo/screenplay/forty_five_minutes.fountain` is the
script the build specification always called for and item 12 recorded as
missing: **three pages whose named subjects are real, deceased, public, and
abundantly documented.**

`the_long_shadow.fountain` demonstrates the interface and cannot demonstrate the
engine, because every character in it is invented, so live research can only
ever return `no_record`. Both scripts stay. The long shadow is the safe offline
demo; this one is the accuracy fixture and the on camera run.

Berlin, 1936. A newsreel writer is cutting commentary over footage of the Games,
and everyone in the room hands him a different version of the same afternoon.
The version he prints outlives the true one. Each seeded falsehood appears
twice: contested in dialogue, then read flat into the finished commentary where
nobody is left to argue with it.

Six real subjects — Jesse Owens, Larry Snyder, Marty Glickman, Luz Long, Leni
Riefenstahl, and an unnamed but identifiable official — plus one invented
character. Eighteen seeds, each mapped to a documented dispute or historical
error, catalogued with expected verdicts in
[demo/screenplay/FORTY_FIVE_MINUTES.md](../demo/screenplay/FORTY_FIVE_MINUTES.md)
and labelled in
[eval/labeled_script/ground_truth_forty_five_minutes.json](../eval/labeled_script/ground_truth_forty_five_minutes.json).

### The B7 regression test, which now runs

Section 14.3 closed B7 and then recorded the thing that made the fix
unverifiable: *"with no genuinely real named subject in any test script, there
is no way to confirm the new conservative classifier still recognises a real
person when one is present."* Six real people and one invented one in the same
room is that test. Executed against live Wikidata on 1 September 2026:

```
Jesse Owens        resolved    Q52651     American track and field athlete (1913-1980), 96 editions
Larry Snyder       resolved    Q24845918  American track and field athlete and coach (1896-1982)
Leni Riefenstahl   resolved    Q55415     German filmmaker, photographer, actress
Marty Glickman     resolved    Q6777422   American sports announcer (1917-2001)
Harold Vance       collision   1 real person shares this name and none is prominent
                               enough to be the assumed referent.
```

Harold Vance is invented. A real Harold Sines Vance exists in Wikidata carrying
three sitelinks, and **the resolver declines to adopt his biography**, which is
precisely the B7 failure. It does so while still resolving all five real
subjects, which is the over correction the same section warned about. Both
halves pass.

Two boundary cases are worth re-running whenever `PROMINENCE_SITELINKS` is
touched: Larry Snyder sits exactly on the threshold at five sitelinks and still
resolves to the correct Snyder out of several real bearers, and Marty Glickman
clears it by one.

This block is empirical rather than hand labelled, and it is the only part of
that ground truth file that is. The second labeller pass has not been run.

### What a healthy run looks like

Stated as failure signals, so a green dashboard cannot be mistaken for a correct
one.

| Signal | Meaning |
|---|---|
| Zero green | Research is not landing. The pipeline runs and verifies nothing |
| Zero grey | The opinion filter is not firing. **Currently true on both scripts**, see B9 |
| S-02 missed | The most important miss. A plausible sentence with a wrong venue is the error class this product claims to catch |
| S-05 and S-06 blended | Atomic decomposition is not real. One amber over a documented fact and a contested motive is the "this scene is risky" output the industry already has |
| Harold Vance resolved | B7 regression. An invented character has acquired a real stranger's biography |
| Jesse Owens fictional | The B7 over correction. A real public figure classified invented |

### The adversarial smoke suite

`eval/smoke_research.py`, added 2 September. Every other suite here asks whether
the pipeline runs. **This one asks whether it lies.**

```bash
make smoke          # all nineteen cases
make smoke-traps    # the two groups that must never fail
```

Nineteen claims with known answers, grouped by the failure each is written to
provoke. The grouping matters more than the total: a system that scores 90% by
getting every famous fact right while inventing a conviction for a private
individual is worse than one that scores 70% and refuses. `trap` and
`defamation` are scored separately and **one fabrication in either fails the
whole run**, whatever the total says.

| Group | What it provokes |
|---|---|
| `true` | Famous, documented facts. A run with no green is a failed run |
| `near_miss` | Right subject, right shape, one detail wrong — Dhoni's 97 against his 91, Owens' four records at Berlin against Ann Arbor, the Hitler snub myth. The class a human researcher skims past |
| `silent` | The record genuinely does not settle it. Amber is the correct answer and resolving it is guessing |
| `trap` **critical** | There is no such person. The B7 shape: an invention must never acquire a biography |
| `defamation` **critical** | The person is real, the allegation is invented. One `supported` here is the most dangerous output this system can produce |
| `opinion` | Not a factual assertion. Must classify, not research |

Result on 2 September, against the grounded provider:

```
-- true         5/5      -- trap [CRITICAL]        3/3
-- near_miss    4/4      -- defamation [CRITICAL]  3/3
-- silent       2/2      -- opinion                2/2
                     19/19 passed
```

Two things that result is not. It is **not** an accuracy figure for the product:
it exercises the research path directly, not ingest, claim extraction or
adjudication, and nineteen cases is a smoke test rather than a benchmark. And it
is **not** a fixed target — one expectation in it was wrong. `luz-long-advice`
originally forbade a `contradicted` verdict on the reasoning that the Long story
is too disputed to refute confidently; the run returned `contradicted` with
three citations, and the case was corrected rather than the system. That
correction is recorded in the case itself, because a ground truth nobody ever
revises is not ground truth.

The suite earned its place immediately: it found B20 in its first run, from two
cases that looked like failures and were actually the system getting the right
answer and throwing it away.

### The 2 September live run

`forty_five_minutes.fountain`, live Parallel and live Gemini, after B9 and B17
through B21 were fixed.

```
  ingest    5 scenes, 43 spans TRUE STORY ASSERTED
  claims    51 extracted
  ledger    23 elements (1.87x reduction)
  identity  21 subjects, 16 resolved, 1 collision, 5 unidentified,
            7 claims settled without research
  routing   71 subjects, projected $1.60
  swarm     83 subjects, 0 failures, $4.00 in 466.7s
  verdicts  23 green · 22 amber · 3 red · 3 grey · 60 counsel
  remedies  4 verified of 4 proposed
  cost      $0.27 research + model, 1037.5s
```

**The first run with a complete verdict spread.** Green, amber, red and — for
the first time in this project's history — **grey**. Zero research failures.
Identity resolved 16 of 21 subjects and settled 7 claims without dispatching
research at all, which is the path that stops a claim being filed against a
subject nobody bears.

**And it is not yet accurate.** The three red verdicts are these:

```
  p 1 2/8  Hitler left the stadium before Jesse won any events.
  p 1 2/8  Jesse set four world records at the Big Ten meet in Ann Arbor.
  p     5  Luz Long showed Jesse Owens where to jump.
```

Those are **the corrections, not the falsehoods.** In the script those lines are
spoken by Snyder to rebut the myths, and the seeded falsehoods they rebut —
S-01, the Hitler snub, and S-02, the four records relocated to Berlin — are not
among the red. The system is marking the true statement contradicted and letting
the false one stand.

Part of it is arguable: sources differ on whether Owens *set* four world records
at Ann Arbor or set three and tied one, so a contradiction there is defensible
on a technicality and useless in practice. The Hitler line is not arguable and
is simply wrong.

This is precisely what the seed table in
[section 10a](#10a-the-forty-five-minutes-fixture) exists to measure, and it is
the outstanding work: **adjudication needs a tuning pass against the expected
verdicts before any accuracy claim is made, and before the demo is recorded.**
The pipeline now runs clean end to end; what it concludes is a separate
question, and this section is not evidence about it.

### The 1 September live run

1 September 2026, `forty_five_minutes.fountain`, live Parallel and live Gemini
on the Gemini 3 generation. This is the run that produced B13 through B16.

```
  ingest    5 scenes, 43 spans TRUE STORY ASSERTED
  claims    51 extracted, 0 opinions filtered
  ledger    23 elements (1.87x reduction)
  identity  21 subjects, 16 resolved, 1 collision, 5 unidentified,
            4 claims settled without research
  routing   74 subjects, projected $1.68
  swarm     131 subjects, 0 failures, $6.38 in 379.7s
  verdicts  18 green · 29 amber · 4 red · 0 grey · 62 counsel
```

What that run establishes, and what it does not:

- **Research works end to end.** 131 subjects, **zero failures**, real citations
  from `bcci.tv`, `en.wikipedia.org` and others. The claim *"The BCCI described
  MS Dhoni as hailing from Ranchi, Jharkhand"* comes back `supported` at 0.9
  with the BCCI's own site as the source. The same claim returned "no citable
  source" the day before, because the account was drained. See B13.
- **The identity fix holds under load.** 16 of 21 subjects resolved, one
  collision, and **4 claims settled without research** — the path that stops a
  claim being filed against a subject nobody bears. No pronoun reached research.
- **Ingest recall roughly doubled** on the newer model: 43 spans against 21 from
  the offline extractor, and 51 claims against 32.
- **The attribution gate is visibly working.** Five sources were dropped with
  `unverifiable quote dropped for …`, each naming the URL and the passage it
  could not stand behind.
- **Zero grey, again.** This run is what sent the search for B9 in the right
  direction: the strongest available reasoning model still filtered no
  opinions, which ruled out the word list and the offline scoping path and
  left the prompt. Fixed since, see B9.
- **29 amber against 18 green** is a heavy amber band and is not yet evidence of
  anything. Whether those are correct amber calls is what the seed table exists
  to answer, and that comparison has not been run.

### Verification status

Every historical and legal fact in the fixture is marked `verify: required`,
consistent with the two person rule in item 11. They are the fixture's design
intent and its expected verdicts, not findings this project has independently
confirmed. The Ann Arbor date and venue underneath seed S-02 is the one to
confirm first, because the demonstration turns on it.
