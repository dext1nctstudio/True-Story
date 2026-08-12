# Agentic Cinema — Project TRUE STORY

**A Fact-and-Rights Engine for "Based on a True Story" Productions**
*(powered by the COVERAGE clearance pipeline)*

| | |
|---|---|
| **Hackathon** | Agentic Cinema: The Blockbuster Hackathon (Google Cloud × Devpost) |
| **Deadline** | 7 September 2026, 5:00pm EDT |
| **Track** | **Parallel** (Parallel Web Systems) |
| **Prize pool (track)** | $7,500 / $4,500 / $3,000 — 1st / 2nd / 3rd |
| **Core stack** | Gemini · Google Cloud Agent Development Kit (ADK) · Vertex AI Agent Engine · Parallel Web APIs |
| **Document status** | Internal build spec + submission strategy. Facts flagged ⚠️ require primary-source verification before public use — see Appendix C. |

---

## 0. What This Tool Does — In Plain English

*(Read this if you read nothing else. No technical knowledge required.)*

"Based on a true story" are the five most valuable words in television — and the five most dangerous. When a show tells a story about real people, every line of dialogue is a claim about someone's life. Get one line wrong and the results are now famous: Netflix was sued for $170 million over *Baby Reindeer*, settled a lawsuit over a single sentence in *The Queen's Gambit*, and settled another over *When They See Us* days before trial. In each case, the problem was one thing: a statement about a real person that nobody had checked against the record.

TRUE STORY reads a script and checks it. For every factual claim about every real person — "she never played against men," "he was convicted twice" — it researches the live public record and marks the line green (verified), amber (unsupported), or red (contradicted, with the sources attached). Underneath, it runs a full legal clearance: every name, brand, song, artwork, and location that could trigger a lawsuit, researched and documented to the standard insurance companies require before a film can be distributed. What takes specialist research firms weeks and thousands of dollars, it does in minutes for a few dollars — and then keeps watching, alerting the production when facts, lawsuits, or licences change.

*(~215 words. For a strict 200, cut the final clause.)*

---

## 1. Table of Contents

1. Plain-English summary *(above)*
2. Table of contents
3. Hackathon context and what is actually being judged
4. Track selection: why Parallel
5. Positioning: why TRUE STORY, and its relationship to COVERAGE
6. Market background study — clearance, E&O, and the true-story boom
7. Competitive landscape — is this a white space?
8. The real cases: three lawsuits TRUE STORY would have prevented
9. The AI wedge: why now
10. **Detailed system design**
11. The demo script — an original screenplay engineered for the demo
12. Protocol architecture: ADK vs MCP vs A2A vs LangGraph
13. Parallel API integration and cost model
14. Repository structure
15. Evaluation — the Litigation Set
16. Build plan, team allocation, cut list
17. Demo video script
18. Legal and ethical guardrails
19. Post-hackathon product roadmap
20. Appendices (A: routing matrix · B: schemas · C: verification checklist ⚠️ · D: known gaps)

---

## 2. Hackathon Context — What Is Actually Being Judged

### 2.1 The brief

The hackathon asks for *"a functional agent — powered by Gemini and Google Cloud Agent Builder — that integrates a Partner Entity's product or MCP to power a real media & entertainment workflow."* The resources page sharpens it: *"a functional, production-ready AI agent or multi-agent network … to solve critical bottlenecks across the entertainment and media value chain, specifically targeting the workflows of filmmakers, screenwriters, studio crews, or fans."*

And the phrase that shapes the whole build: *"Show off a **deterministic, multi-step agent** that solves enterprise friction."*

### 2.2 The four judging criteria, and how TRUE STORY attacks each

| Criterion | What they ask | Our answer |
|---|---|---|
| **Technological Implementation** | How well built; how effectively does it use Google Cloud *and* the Partner services? | Five of Parallel's six APIs, each doing a distinct job. ADK workflow agents deployed on Agent Engine. Nine+ Google Cloud services in genuine runtime use. |
| **Design** | A complete, coherent product experience, not a proof of concept | The verdict-overlay script view is a real product surface, and the output is the E&O-format report insurers already accept. |
| **Potential Impact** | A credible, specific case for a real problem, a real audience | $175M+ in claims across three famous shows; a mandatory, priced workflow with named vendors. Sections 6 and 8. |
| **Quality of the Idea** | Creative, non-obvious, genuine understanding of the problem space | Nobody else will bring a fact-verification engine to a cinema hackathon. The Litigation Set eval (blind runs against the actual lawsuits) proves domain understanding no one can fake in a week. |

### 2.3 Why this idea fits the *cinema* branding, not just the enterprise criteria

The judge-mismatch risk of a pure compliance tool is real: if the panel skews creative-technologist, insurance software reads dry next to a storyboard generator. TRUE STORY closes that gap by construction rather than by editing:

- The demo subject is a **drama about real people** — inherently cinematic material.
- The money shot is a **script page whose lines light up against the truth**, with the receipts alongside — visually legible to any judge in three seconds.
- The framing cases (*Baby Reindeer*, *The Queen's Gambit*, *When They See Us*) are shows every judge knows and half of them have opinions about.
- The enterprise substance (E&O, clearance, cost) sits underneath for the judges who score on friction and production-readiness.

One product, two audiences, no trade-off.

### 2.4 Submission requirements checklist

- [ ] URL to a hosted, working project
- [ ] 3-minute demo video — **the project functioning as built, not a cinematic trailer** — YouTube/Vimeo, public, English or English-subtitled
- [ ] Public repo (GitHub/GitLab/Bitbucket): all source, assets, run instructions
- [ ] Repo demonstrates **actual runtime use** of Google Cloud and Parallel — *imported and called in code, not just named in the README*
- [ ] Complete open-source licence, **detectable and visible in the repo's About section** — use a verbatim, unmodified `LICENSE` (Apache-2.0) at the repo root so GitHub auto-detects it
- [ ] Partner track selected: **Parallel**
- [ ] Completed Devpost submission form

---

## 3. Track Selection: Why Parallel

### 3.1 Crowding analysis

With 5,599 registrants across five identical prize buckets and judging **only within your track**, track choice is the highest-leverage single decision. Realistic submission volume: Devpost attrition on hackathons with a real technical bar typically leaves ~8–12% submitting → **~400–600 projects total**.

| Track | Expected crowding | Reasoning |
|---|---|---|
| **Replit** | Highest (~30%) | Most familiar, lowest barrier, credit-request form prominently linked from the resources page — a gold-rush signal |
| **IBM** | High (~25%) | Brand recognition; watsonx is the "safe" enterprise default |
| **ClickHouse** | Medium-high (~20%) | Developer-beloved; "box-office analytics dashboard" is the obvious angle everyone reaches for |
| **Grafana** | Medium-low (~13%) | Awkward cinema fit; those who enter will mostly build "observability for your agent" |
| **Parallel** | **Lowest (~12%)** | Newest company, least name recognition; many entrants won't know what it does |

Estimated field in the Parallel track: **~50–70 submissions for 3 prizes** — of which, on typical hackathon quality distributions, only ~4 will be genuinely strong. Those are the actual competition.

⚠️ *These percentages are inference, not data. Check the Devpost project gallery around 31 August. If Parallel looks unexpectedly crowded, do not panic-switch tracks — double down on the Litigation Set eval, the one differentiator nobody can replicate in the final week.*

### 3.2 The better reason: surface area nobody else will use

Parallel is a six-API platform, and most entrants will discover exactly one.

| API | Shape | TRUE STORY's use |
|---|---|---|
| **Search** | Single round-trip; natural-language objective → LLM-optimised excerpts; sub-5s latency | Interactive interrogation tool ("why is this line red?") |
| **Extract** | URL → clean markdown; handles JS pages and PDFs | Capturing registry pages, dockets, archives into the evidence pack |
| **Task** | Multi-hop research agent; seconds to hours; structured output with citations | The core verification and clearance research, tier-routed |
| **FindAll** | Natural-language query → structured entity dataset with citations and confidence | "Every registered business named X in Illinois"; "every person matching this attribute cluster" |
| **Monitor** | Scheduled recurring query; webhooks on new events; automatic dedup | **Living Clearance** — facts, lawsuits, and licences change after the report is filed |
| Chat/Responses | Web-grounded completions | Not used; noted for completeness |

Every Parallel response carries the **Basis framework** — citations, reasoning, excerpts, and calibrated confidence per output field. For a product whose output is "this line about a real person is false," that is not a nice-to-have. **It is the product.** A verdict without a citation is legally worthless; Parallel is the only partner in the hackathon whose core differentiator is evidence.

Parallel also integrates with Google Vertex AI directly and delivers async results over webhooks — the Google-plus-Partner story is native, not bolted on.

### 3.3 What the typical Parallel submission will look like

*"A deep-research agent that finds box-office comps for your screenplay."* One API, one call, a chat window, no artifact, no eval. TRUE STORY beats that on every judged axis by an order of magnitude.

---

## 4. Positioning — TRUE STORY and COVERAGE

**One engine, two framings.** COVERAGE is the full clearance pipeline (every element type, every deliverable). TRUE STORY is the same pipeline aimed at its most cinematic, most famous, most currently-litigated slice: **fact verification and clearance for adapted-reality productions** — true crime, biopics, docudramas.

Why lead with the slice:

1. **It is the hottest genre on every streamer**, and it is generating the era's most famous entertainment lawsuits (§8). The demo material is inherently dramatic.
2. **The truth-claim escalation is a real legal doctrine, not a gimmick.** Courts in both *Queen's Gambit* and *Baby Reindeer* treated the "true story" framing itself as evidence bearing on reckless disregard. A production that says "true story" changes the legal standard applied to every line — which is exactly a computable, project-level rule.
3. **It narrows the demo's live path** (fewer moving parts on judging day) while the full clearance ledger remains underneath as depth.
4. **It maps onto Parallel's exact strength** — claim verification with citations and calibrated confidence.

The product thesis, restated:

> **TRUE STORY turns the riskiest genre in television from a legal minefield into a verified document — every claim checked against the record, every element cleared to insurer standard, in minutes instead of weeks, continuously instead of once.**

Three defensible claims:
1. **The workflow is mandatory.** No clearance, no E&O policy; no E&O, no distribution (§6.4).
2. **The work is structured web research at scale** — hundreds of independent, cited, confidence-scored lookups about the real world. Precisely Parallel's product shape.
3. **The output is a document, not a chat** — the verdict-annotated script and the E&O-format report the industry already runs on.

---

## 5. Market Background Study

### 5.1 The true-story boom (the genre context)

Adapted-reality content — true crime, biopics, docudrama — is a dominant commissioning category across streamers, and its legal exposure is structurally different from fiction: every named or identifiable person is a potential plaintiff, and every factual assertion is a potential defamation claim. The three marquee cases in §8 arose in a four-year window (2020–2024) and involve a combined **$175M+ in claims** — all from productions that passed conventional, manual clearance processes.

⚠️ *If a specific commissioning statistic on true-crime volume is wanted for the deck, source it fresh; none is asserted here.*

### 5.2 What a script clearance report is

A scene-by-scene analysis flagging every element that could create legal exposure. The standard taxonomy, from vendor descriptions:

- Character names (defamation/false-light where a real person shares name + profession + locale)
- Business and organisation names; products, brands, trademarks, logos
- **Real persons depicted or mentioned — living and deceased — and the factual claims made about them**
- Real events and institutions
- Locations, addresses, phone numbers, licence plates, URLs, handles
- Music cues (composition *and* master — two separate rights)
- Artwork, photographs, posters, murals, tattoos visible on screen
- Film clips and archival footage; quoted text
- Defamatory references and trade libel
- Public-domain status of underlying source material

Vendors also **suggest cleared alternatives** — Hollywood Script Research advertises 2–3 alternate names as close to the original as possible, free within the original report.

### 5.3 Pricing and turnaround (the friction being solved)

| Item | Figure | Source |
|---|---|---|
| First full feature report | **$1,000–$3,000** | The Front Row View (Grant Patten), Medium |
| Heavy feature, many rewrites + art-dept requests | **$5,000+** | same |
| Series, per episode | ~$100 (short-form) to ~$1,000 (one-hour) | same |
| Rush surcharge | ~+50% | same |
| Hollywood Script Research | **$1,000 fiction, 3–4 business days standard**; $10/page over 120pp | vendor site |
| The Clearance Lab | ~7-day standard turnaround | vendor site |

**The re-billing dynamic is the deeper pain:** every revised draft, every one-off name change, every art-department signage request generates follow-up billing by the hour or item. A production in active shooting generates a continuous trickle.

### 5.4 What E&O carriers require before binding

Converging broker/carrier sources describe a standard clearance package:

1. Script clearance report **plus evidence recommended changes were implemented**
2. Title report and often a title opinion
3. **Chain-of-title memo/opinion from an entertainment attorney** ("not optional")
4. Copyright report and registration
5. Signed talent, location, and materials releases
6. **Two music licences per cue — synchronisation and master use** — plus complete cue sheets
7. Clip/archival licences
8. A clearance log listing every visible piece of IP and its status

Netflix and other platforms typically require all clearance completed and documented **before** the policy issues. Typical policy: **$1M per claim / $3M aggregate, $10K deductible, 3-year claims-made**; streamers often require $1M/$5M+.

### 5.5 E&O premiums (all broker self-published estimates — no audited survey exists)

| Tier | Premium | Source |
|---|---|---|
| Indie/low-budget, 3-yr $1M policy | **$2,500–$10,000** | Wrapbook |
| Filmmaker-reported actuals | ~$3,700–$6,000 | IndieTalk forum |
| Full range | **$1,000–$20,000+** | TH Agency |
| Documentary festival coverage | $2,000–$3,500 | attr. Debra Kozee, C&S International |

### 5.6 The vendor landscape — small, veteran, manual

| Vendor | Notes |
|---|---|
| **Act One Script Clearance** | "Since 1952"; ~a dozen professionals; Glendale, CA. ⚠️ *actonescript.com and deforestresearch.com resolve to the same site — the historic De Forest Research brand appears absorbed; verify before citing.* |
| **Marshall/Plumb Research Associates** | Since 1986; E&O research, title clearance, historical research; US + Canada |
| **The Clearance Lab** | Clearance, title reports/opinions, copyright reports, chain-of-title, with an attorney arm |
| **Hollywood Script Research** | Feature/MOW and series reports |
| **Eastern Script · The Research House · Clear-a-Rite** | Smaller / less documented |

A cottage industry of a few dozen expert researchers serving a global content machine. That asymmetry is the opportunity.

### 5.7 Market size (present as ranges, attributed — vendors disagree ~2×)

- **Entertainment insurance:** ~**$3.2B–$4.5B** (2024/25), ~6–11% CAGR — SkyQuest, The Business Research Company, Global Growth Insights, MRFR, Virtue
- **Media liability** (closest E&O segment): ~**$2.5B–$4.5B** (2023/24) — Verified Market Reports, MarketIntelo, Dataintelo
- **Carriers:** Chubb ("MediaGuard," ~40 years insuring producers), AXA XL (Jeffrey L. Loop appointed Head of Media Liability, Dec 2025), AXIS, Hiscox, Allianz, Great American, Philadelphia. **Brokers:** Front Row, DeWitt Stern (merged into Risk Strategies 2014), Gallagher, Aon, Marsh, Lockton.

### 5.8 Production volume — the defensible bottom-up TAM

Per ProdPro (live-action scripted, US-commissioned, >$1M budget):

| | 2022 | 2023 | 2024 |
|---|---|---|---|
| Features tracked | — | 600 | **679** |
| TV series tracked | 607 | 397 | **494** |
| US theatrical releases | — | 506 | **569** |

Global feature output is commonly estimated at **6,000–8,000/year**; US original scripted series peaked ~600 (2022), 516 in 2023 (FX Networks data).

**Bottom-up TAM:** ~680 US features + ~500 US series annually × ($1–5K clearance + $2.5–20K E&O). Lead with this arithmetic — it is checkable — rather than a single disputed market-size figure.

---

## 6. Competitive Landscape — Is This a White Space?

Short answer: **yes, genuinely** — with honest caveats.

### 6.1 Script-breakdown / production-management software (tags elements; does not clear them)

| Tool | What it does | Clearance? |
|---|---|---|
| **Filmustage** | AI script breakdown; auto-tags cast, props, locations, VFX; markets an "AI Analysis" flagging "legal, safety, and pre-production challenges" and "copyright clearance" risk at a high level | **Nearest adjacent AI feature — and our nearest competitive threat.** But it is risk-*flagging* for planning: no real-world database research, no citations, no cleared alternatives, no report. |
| **StudioBinder** | Breakdown sheets, call sheets (manual tagging) | No |
| **Movie Magic Scheduling/Budgeting** | Industry-standard scheduling | No |
| **Celtx, Gorilla, Scenechronize, Yamdu, Croogloo, SetKeeper** | Production management | No |
| **Wrapbook, Greenslate** | Payroll/accounting (Wrapbook also brokers E&O) | No |

### 6.2 Rights-management platforms (downstream of clearance)

| Platform | Scope |
|---|---|
| **Rightsline** | Enterprise rights & royalties; acquired **FilmTrack (May 2024, from City National Bank, ~200 customers)** and **RSG Media (Sept 2024)** |
| **FilmTrack** | Mid-market rights/contracts/royalties |
| **Vistex** | Enterprise rights/royalty/revenue, often SAP-adjacent |

These are the "math" layer — royalties, waterfalls, avails — at $30K–$300K/yr. They manage rights you already hold; they do not tell you what rights you need.

### 6.3 General legal AI

Harvey, Luminance, Robin AI, Lex Machina target contract review and litigation analytics. None is documented as addressing entertainment script clearance, and none does fact-verification against the live web with citations.

### 6.4 Fact-checking tools

Newsroom fact-checking (e.g. wire-service verification desks, claim-matching research prototypes) is adjacent in *technique* but not in *product*: nothing packages claim verification into the clearance/E&O deliverable chain, and nothing does continuous monitoring over a production's life. ⚠️ *If a named fact-checking product is cited in the deck, verify its current capabilities first.*

### 6.5 The white space, stated precisely

> Breakdown tools **tag elements**. Rights platforms **manage downstream contracts**. Human research shops produce **point-in-time reports**. Newsroom tools **check claims but ship no clearance artifact**. Nobody does **AI-native, citation-backed fact verification plus full clearance, continuously monitored, delivered in the format insurers require.**

Caveats for the record: Filmustage could ship a deeper legal module — our moat is therefore **continuous monitoring + the verified remedy loop + the Litigation Set-calibrated rubric + the E&O artifact**, not "AI reads scripts." And absence of evidence is not proof of absence — the claim to make on camera is *"no publicly available product does this,"* which is accurate.

---

## 7. The Real Cases — Three Lawsuits TRUE STORY Would Have Prevented

These are now the **narrative spine of the product**, not background. Each is a different failure mode; each justifies a different subsystem; each is famous enough that judges will recognise it on sight. Every factual detail below was verified against contemporaneous reporting during research; items marked ⚠️ still require primary-source confirmation before appearing on camera (Appendix C).

### 7.1 Case A — *The Queen's Gambit*: one unverified line ($5M)

**Failure mode: a false factual claim about a real, living, named person — in a single line of dialogue.**

In the season-one finale, as Beth Harmon plays a 1968 match in Moscow, a commentator says of the real Georgian chess grandmaster Nona Gaprindashvili that she is "the female world champion and **has never faced men**."

Per her complaint, by 1968 she had competed against **at least 59 male chess players — 28 of them simultaneously in one exhibition — including at least 10 Grandmasters of the era.** She was the first woman awarded the general Grandmaster title (1978).

- Filed **September 2021**, C.D. Cal., seeking **$5,000,000**, for defamation and false-light invasion of privacy
- Netflix moved to dismiss on First Amendment grounds: the show is fiction
- **Motion denied, January 2022.** The court held that **fictional works are not immune from defamation suits when they disparage real people**, and found the record could support reckless disregard for accuracy. ⚠️ *One source attributes the ruling to Judge Virginia Phillips — confirm the name before citing it.*
- **Settled September 2022**, terms undisclosed; the pending appeal was dismissed.

**How TRUE STORY catches it.** IngestAgent tags the line `REAL_PERSON_DEPICTED` with an attached `FACTUAL_CLAIM` ("never faced men"). The Risk Router escalates: named + living + negative assertion = CRITICAL. Parallel Task verifies the claim against the historical record — tournament databases, chess federation records, contemporaneous coverage. Verdict: **claim FALSE, subject LIVING, assertion DISPARAGING → line renders RED**, citations attached. RemedyLoop proposes: cut the name, or substitute a verifiably accurate line — and re-verifies the substitute.

**Why it's the perfect demo item:** it is *one line*. It demonstrates the system's granularity in eight seconds, and every judge instantly grasps that a human reader plausibly missed what a machine checking every claim would not.

### 7.2 Case B — *Baby Reindeer*: identifiable without being named ($170M)

**Failure mode: a real person made identifiable through an attribute cluster, compounded by a "this is a true story" truth-claim.**

Fiona Harvey, identified by viewers within days as the inspiration for the stalker "Martha," sued Netflix on **6 June 2024** (C.D. Cal.) for **$170 million** — defamation, IIED, negligence, right of publicity — over the series' opening card "This is a true story" and its depiction of her as a twice-convicted stalker imprisoned for sexual assault. In reality she had been warned by police but **never arrested, charged, or convicted**.

- **27 September 2024:** Judge R. Gary Klausner dismissed negligence, right of publicity, and punitive damages, but **allowed defamation and IIED to proceed** — holding that the "true story" framing, which Netflix may have "insisted on adding" despite the creator's own concerns, could evidence **reckless disregard** for falsity. Gadd himself had called the series "emotionally true" in a court declaration.
- Trial set for 6 May 2025; **Netflix appealed in May 2025** (arguing no provably false statement of fact was alleged), halting trial.
- **Status: unresolved as of this document's research.** ⚠️ *Verify at the Ninth Circuit docket immediately before recording the video — this is the fact most likely to have moved.*

**The clearance lesson, and it is the sharp one: the character was never named, and it did not help.** Identifiability — profession + city + physical description + relationship, in combination — is the legal trigger, not naming.

**How TRUE STORY catches it.** Two mechanisms, both first-class in the design:
1. **`REAL_PERSON_IDENTIFIABLE`** is a *composite detector* — it fires on attribute clusters with no name present, then uses Parallel **FindAll** to enumerate real persons matching the cluster in the relevant territories.
2. **`TRUTH_CLAIM_FRAMING`** is a *project-level flag*: any production asserting "true story" escalates every person-adjacent element one full risk tier, because courts in this very case treated the framing itself as evidence on the reckless-disregard standard. This is a legal doctrine expressed as a routing rule — the single best example of the system encoding genuine domain knowledge.

### 7.3 Case C — *When They See Us*: the named real person ($1M settlement + re-cut disclaimer)

**Failure mode: a named, living real person alleging false portrayal of specific conduct.**

Former prosecutor Linda Fairstein sued Netflix and Ava DuVernay (filed **March 2020**) over her portrayal in the 2019 series about the Central Park Five, alleging she was falsely depicted as the racist architect of the prosecution, with specific invented scenes attributed to her.

- Judge P. Kevin Castel **denied summary judgment** (fall 2023), finding certain scenes could be defamatory — the case was headed to a jury.
- **Settled 4 June 2024, days before trial:** Netflix donated **$1M to the Innocence Project**; Fairstein received no money; and the fictionalisation disclaimer ("certain characters, incidents, locations, dialogue and names are fictionalized…") was **moved to the start of each episode**.

**How TRUE STORY catches it.** Every scene in which a named real person performs specific conduct generates `FACTUAL_CLAIM` entries ("Fairstein ordered X," "Fairstein said Y"). Claims the record cannot support render **AMBER (unsupported)** — which is precisely the category that settles: not provably false, but undefendable. The report's front page counts amber claims per named person; any named living person with amber-claim density above threshold routes to `NEEDS_COUNSEL`. The disclaimer remedy — position and prominence — is itself encoded, because its placement was a negotiated term of this very settlement.

### 7.4 The monitoring case — *WKRP in Cincinnati*: rights that expired after the report was filed

**Failure mode: time-boxed licences lapsing silently, years after clearance.** *(Retained from COVERAGE — it justifies the Monitor subsystem and the subscription business model.)*

*WKRP in Cincinnati* (1978–1982) licensed real music for limited terms (~10 years, pre-home-video). The licences expired; syndication and early DVDs replaced the music with sound-alikes, redubbing dialogue and cutting scenes to fit. When Shout! Factory re-licensed for the 2014 complete-series set, its release noted that **"well over 100 artists' tracks will be heard on WKRP in Cincinnati episodes for the first time since the music rights expired at some point after its cancellation in 1982."** *The Wonder Years* has the same story — off DVD for years over music costs; the Joe Cocker theme swapped for the Netflix run, restored for the 2014 StarVista set.

**A clearance report is a photograph; rights are a film.** Every `MUSIC_CUE` gets a Parallel Monitor with an expiry-aware cadence; the production is alerted *before* the licence lapses. And for true-story productions specifically, Monitors also watch **the facts**: a depicted person dies (publicity rights change by state), a related lawsuit is filed, new records surface contradicting a verified claim.

### 7.5 The defence-side ledger — cases the studios *won* (equally important)

A verification engine that flags everything is useless. These cases calibrate the rubric's other edge — where the First Amendment protects the production and the correct verdict is `CLEAR` or `CLEAR_WITH_CONDITIONS`:

- **Sarver v. Chartier** (*The Hurt Locker*) — Ninth Circuit, **17 Feb 2016, No. 11-56986**: dismissal affirmed under California anti-SLAPP; the film was protected expressive speech.
- **Greene v. Paramount** (*The Wolf of Wall Street*) — claim that "Nicky 'Rugrat' Koskoff" defamed a real Stratton Oakmont executive; filed Feb 2014 (EDNY), sought $25M then $50M; **summary judgment for Paramount, affirmed on appeal**. The court cited the studio's clearance practice — composite characters with fictitious names — as "appropriate steps… so that no one would be defamed." **This is the case that proves clearance works as a legal defence.**
- **de Havilland v. FX** (*Feud*) — California Court of Appeal reversed the anti-SLAPP denial (**March 2018**, portrayal transformative and protected); Cal. Supreme Court denied review July 2018; **US Supreme Court denied cert January 2019**.
- **Louis Vuitton v. Warner Bros** (*The Hangover Part II*) — SDNY, **dismissed 15 June 2012** under *Rogers v. Grimaldi* (875 F.2d 994, 2d Cir. 1989): artistic relevance, not explicitly misleading.

And the visual-copyright pair used in the eval:
- **Whitmill v. Warner Bros** — Mike Tyson's tattoo artist sued (**April 2011, E.D. Mo.**) over the replica tattoo on Ed Helms; Judge Catherine Perry **denied the preliminary injunction 24 May 2011** but called Warner's defences "silly"; Warner threatened to digitally alter the tattoo for home video; **settled June 2011**. A clearance failure that came within days of enjoining a ~half-billion-dollar release.
- **Ringgold v. BET** (2d Cir. 1997) — a story-quilt poster visible as background set dressing for seconds; Second Circuit held the use **not de minimis**. ⚠️ *Verify citation and holding before use.*
- **Caterpillar v. Walt Disney** (*George of the Jungle 2*, C.D. Ill. 2003) — injunction over menacing Cat bulldozers denied. ⚠️ *Verify before use.*

### 7.6 What a lawsuit actually costs

| Figure | Source | Reliability |
|---|---|---|
| Defence of a **meritless** defamation suit: **$21K–$55K, median ~$39K** | Institute for Free Speech, citing NCSC 2012 study | Best-sourced available |
| Defence through trial: **$10K–$150K** | Lawfold (2026) | Secondary |
| "Defence and settlement costs can escalate to hundreds of thousands (if not millions)" | Chubb, via Front Row | Carrier marketing |
| "$500,000 or more defending a single claim" | Kelly Insurance Group | Broker marketing — flag as such |
| Observed outcomes | $1M-to-charity (*WTSU*) → $5M sought (*QG*) → $170M sought (*BR*) | Court records |

**Claim frequency:** no public quantitative data exists — carriers do not release loss ratios. Qualitatively, the most-cited E&O claim types: copyright/trademark infringement, defamation/libel, privacy, right of publicity, plagiarism, idea theft, title disputes, music-clearance errors, chain-of-title defects. Copyright is repeatedly cited as the most common indie claim. **Say "no public frequency data exists" — a judge who knows the space will respect it.**

---

## 8. The AI Wedge — Why Now

*(The section that turns a hackathon project into a fundable company. Lead the pitch deck with it.)*

### 8.1 Insurance is closing the door on AI content

- **ISO filed three generative-AI exclusion endorsements — CG 40 47, CG 40 48, CG 35 08 — effective January 2026**, excluding bodily injury, property damage, and **personal & advertising injury (which includes defamation and IP infringement)** arising out of generative AI in commercial general liability.
- Verisk's in-form definition: *"a machine-based learning system or model that is trained on data with the ability to create content or responses, including but not limited to text, images, audio, video or code."*
- **By April 2026, W.R. Berkley, Chubb, Travelers, Berkshire Hathaway, and Cincinnati Financial had filed to adopt these endorsements or proprietary AI-exclusion language, with state regulators approving more than 80% of submitted filings** (actuary.info citing IndependentAgent.com; PYMNTS, May 2026).
- Some carriers (Berkley, Hamilton, Philadelphia) adopted **absolute AI exclusions** barring any claim "based upon, arising out of, or in any way involving" generative AI; Hamilton's definition names ChatGPT, Bard, Midjourney, DALL-E.
- Entertainment-specific commentary (Akker LLC, 2026): many 2025–26 E&O renewals added AI-content exclusions; *"a film generated using training data from unlicensed sources faces uninsurable copyright exposure."*
- **Affirmative AI coverage is emerging:** HSB (Hartford Steam Boiler) launched AI Liability Insurance for SMBs, **March 2026** — an active benchmark.

### 8.2 Copyright is closing the other door

US Copyright Office, **"Copyright and Artificial Intelligence": Part 1 (Digital Replicas, 31 July 2024), Part 2 (Copyrightability, 29 January 2025)**, on 10,000+ comments:

- **"Human authorship is a bedrock requirement of copyright."**
- Prompts alone **do not provide sufficient human control** for copyrightability.
- Purely AI-generated output is **not registrable**; works with more than *de minimis* AI content **must disclose it**, with only human contributions protected.
- Part 3 (training data, licensing, liability) forthcoming at time of research.

### 8.3 Digital-replica law is fragmenting by jurisdiction

| Instrument | Status |
|---|---|
| **NO FAKES Act** (S. 4591, 2026) | Advanced from Senate Judiciary by voice vote **18 June 2026**; federal licensable right against unauthorised AI voice/likeness replicas; notice-and-takedown; preempts future state laws, preserves those existing as of 2 Jan 2025. ⚠️ *Advancing, not enacted; trackers disagree — verify.* |
| **Tennessee ELVIS Act** (HB 2091 / PC 588) | Effective **1 July 2024** — first US law extending right of publicity to AI voice clones |
| **California AB 1836** | Deceased performers' digital replicas; amends Civ. Code §3344.1; Ch. 258 of 2024; statutory damages ≥$10,000 |
| **California AB 2602** | Digital-replica contract requirements (2024) |
| **Illinois HB 4875 · NY Civ. Rights Law §50-f** | State digital-replica / deceased-personality provisions |
| **TAKE IT DOWN Act** (PL 119-12) | Signed **19 May 2025**; nonconsensual intimate deepfakes; 48-hour takedown |
| **EU AI Act** | Transparency obligations for AI-generated/manipulated media ⚠️ *article/date unverified* |

### 8.4 The double bind — and where TRUE STORY sits

> An AI-assisted production in 2026 faces a work that may be **unregistrable** (Copyright Office) and **uninsurable** (ISO exclusions), governed by a **patchwork of state digital-replica statutes** varying by domicile and mortality.

Nobody sells the compliance layer for this. Clearance is where it naturally lives — the one existing process where a production already enumerates every rights-bearing element. TRUE STORY's roadmap extends the taxonomy with `AI_GENERATED_ASSET` (training-data provenance, human-authorship log) and `DIGITAL_REPLICA` (consent instrument, jurisdiction, post-mortem term): the same pipeline that verifies a true-story script produces the provenance dossier an underwriter needs to write affirmative AI coverage.

And note the convergence: **true-story productions are precisely where digital replicas are heading** — AI-recreated voices and likenesses of real people in docudramas. The genre focus and the AI wedge are the same wedge.

⚠️ *Gap: no single cleanly documented film/TV AI-likeness lawsuit was confirmed in research. Do not assert one without a source.*

---

# 9. DETAILED SYSTEM DESIGN

## 9.1 Design principles

| # | Principle | Consequence |
|---|---|---|
| **P1** | **Determinism over discretion.** The brief asks for a *deterministic, multi-step agent*; a legal product cannot have an LLM improvising control flow. | Only **four** LLM decision points in the pipeline. Everything else is a policy table, schema, or template. |
| **P2** | **No verdict without evidence.** A red line with no citation is legally worthless — and defamatory of the production. | The `Evidence` envelope is mandatory, enforced structurally via forced function calling. |
| **P3** | **Vendor-swappable, contract-stable.** | `ResearchProvider` abstraction behind an MCP tool boundary. |
| **P4** | **Cost is a governed runtime resource.** | The BudgetGovernor is a real component with a CRITICAL-tier reserve. |
| **P5** | **Degrade honestly.** | Fallback providers stamp `is_fallback: true, confidence: reduced`; the report states its own coverage quality. |
| **P6** | **Privacy by default.** The system's output is assertions about real people. | Private individuals masked by default; reveal gated behind IAM and audited. |
| **P7** | **Everything is re-runnable.** Scripts change daily. | Content-addressed element IDs; diff-based re-verification. |
| **P8** | **The claim is the atom.** *(New for TRUE STORY.)* | Factual claims are first-class objects with their own lifecycle — extracted, decomposed, verified, versioned, monitored — not attributes hanging off an entity. |

## 9.2 System context (C4 Level 1)

```
                    ┌────────────────────────────────────────┐
                    │              HUMAN ACTORS              │
                    ├────────────────────────────────────────┤
  Screenwriter ─────▶ uploads draft, sees verdict overlay,   │
                    │ receives verified rewrites             │
  Showrunner/Prod ──▶ claim dashboard, risk posture, alerts  │
  Clearance Attorney▶ reviews escalations, unmasks, signs off│
  Underwriter ──────▶ receives E&O clearance package         │
                    └───────────────┬────────────────────────┘
                                    │
                    ┌───────────────▼────────────────────────┐
                    │            TRUE STORY                   │
                    │   (ADK on Vertex AI Agent Engine)       │
                    └───┬───────────┬───────────┬─────────────┘
                        │           │           │
         ┌──────────────▼──┐  ┌─────▼─────┐  ┌──▼──────────────────┐
         │  Parallel Web   │  │  Gemini   │  │  Google Cloud       │
         │  Search Extract │  │  (Vertex) │  │  Firestore BigQuery │
         │  Task FindAll   │  │ long-ctx  │  │  Cloud Run Pub/Sub  │
         │  Monitor        │  │ multimodal│  │  IAM Secret Manager │
         └─────────────────┘  └───────────┘  └─────────────────────┘
                        │
         ┌──────────────▼──────────────────┐
         │  EXTERNAL AGENTS (A2A, spec'd)  │
         │  Law-firm CounselAgent          │
         │  Studio / insurer agents        │
         └─────────────────────────────────┘
```

## 9.3 Container view (C4 Level 2)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ PRESENTATION                                                             │
│  Next.js app (Cloud Run):                                                │
│   · Verdict Overlay script view  ← THE MONEY SHOT                       │
│   · Claim Dashboard (per-person amber/red density)                      │
│   · Evidence panel (citations, excerpts, confidence, masked identities) │
│   · Live cost meter (SSE)                                               │
│  REST API · A2A AgentCard (spec)                                        │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│ ORCHESTRATION — ADK on Vertex AI Agent Engine                            │
│                                                                          │
│  TrueStoryPipeline = SequentialAgent(                                    │
│      IngestAgent        → LlmAgent (Gemini, per-scene)        [LLM 1]    │
│      ClaimExtractor     → LlmAgent (claim decomposition)      [LLM 2]    │
│      LedgerAgent        → deterministic (coref, dedupe)                  │
│      RiskRouter         → deterministic (policy table)                   │
│      ResearchSwarm      → ParallelAgent (fan-out)                        │
│      Adjudicator        → LlmAgent (forced fn calling)        [LLM 3]    │
│      RemedyLoop         → LoopAgent (propose→verify, ≤3)      [LLM 4]    │
│      ReportAgent        → deterministic (templated)                      │
│  )                                                                       │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ MCPToolset
┌───────────────────────────────▼──────────────────────────────────────────┐
│ TOOL BOUNDARY — clearance-tool-server (MCP, Cloud Run)                   │
│  Domain tools, uniform Evidence envelope out                             │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│ PROVIDER LAYER — ResearchProvider registry                               │
│  ParallelTask · ParallelSearch · ParallelFindAll · ParallelExtract        │
│  ParallelMonitor · GeminiGrounded (fallback) · Cached · Mock             │
│  ── selected by routing.yaml + BudgetGovernor ──                         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌────────────────────────────────▼─────────────────────────────────────────┐
│ ASYNC PLANE                     │ STATE PLANE                            │
│  Pub/Sub work queue             │ Firestore: runs, claims, elements,     │
│  Cloud Run webhook receiver     │            evidence, monitors          │
│  Cloud Tasks retry/backoff      │ BigQuery: precedent corpus + vectors,  │
│  Cloud Scheduler stale sweep    │           cost telemetry, eval results │
│                                 │ GCS: scripts, PDFs, evidence pages     │
└──────────────────────────────────────────────────────────────────────────┘
```

## 9.4 The eight agents, specified

### Agent 1 — `IngestAgent` (LlmAgent, Gemini)

Raw script → typed spans.

- **Input:** `.fdx` (XML), `.pdf`, `.fountain`, plain text. Optionally a storyboard still.
- **Model:** Gemini long-context. **Deliberately no Document AI** — Gemini's native PDF/multimodal understanding parses screenplay structure better and removes a service, a failure mode, and a line item.
- **Chunking:** by scene (`INT./EXT.` headings are reliable natural boundaries), one-scene overlap, chunks processed in parallel.
- **Project-level pass:** detects `TRUTH_CLAIM_FRAMING` — title cards, marketing copy, or dialogue asserting the story is true. One boolean that changes everything downstream (§7.2).

```python
@dataclass
class RawSpan:
    span_id: str            # hash(scene_no, char_start, text)
    scene_no: int
    page: float             # 1/8-page granularity, industry standard
    line_no: int
    element_type: ElementType
    surface_form: str       # exactly as written
    context: str            # ±200 chars
    modality: Literal["script", "still"]
    extraction_confidence: float
```

**Element taxonomy** (`ElementType`):

```
PERSON_NAME_FICTIONAL     BUSINESS_NAME          BRAND_PRODUCT
TRADEMARK_LOGO            ORGANIZATION           REAL_LOCATION
PHONE_NUMBER              STREET_ADDRESS         URL_HANDLE
VEHICLE_PLATE             MUSIC_CUE              ARTWORK_VISUAL
TATTOO                    PRINT_QUOTE            FILM_CLIP
REAL_EVENT                REAL_PERSON_DEPICTED   REAL_PERSON_IDENTIFIABLE
DEFAMATORY_REF            TRADE_LIBEL            SOURCE_MATERIAL
── project-level ──       ── roadmap ──
TRUTH_CLAIM_FRAMING       AI_GENERATED_ASSET     DIGITAL_REPLICA
```

`REAL_PERSON_IDENTIFIABLE` is a **composite detector** — attribute clusters (profession + city + description + relationship), no name required. Exists because of *Baby Reindeer*.

### Agent 2 — `ClaimExtractor` (LlmAgent) — *new; the heart of TRUE STORY*

For every `REAL_PERSON_DEPICTED` / `REAL_PERSON_IDENTIFIABLE` / `REAL_EVENT` span, decompose the text into **atomic, independently verifiable factual claims**.

```python
@dataclass
class FactualClaim:
    claim_id: str                   # content hash → cacheable across drafts
    subject_element_id: str         # the person/event it is about
    claim_text: str                 # atomic: "X was convicted of stalking"
    claim_type: ClaimType           # CONDUCT | STATUS | ACHIEVEMENT | QUOTE
                                    # | RELATIONSHIP | EVENT_FACT | CHARACTERIZATION
    polarity: Literal["positive", "neutral", "negative"]   # reputational valence
    asserted_in: list[Occurrence]   # scene/page/line
    verdict: Verdict | None         # set by Adjudicator
    evidence: list[Evidence]

Verdict = Literal[
    "VERIFIED",        # supported by the record            → GREEN
    "UNSUPPORTED",     # no record either way               → AMBER
    "CONTRADICTED",    # record shows otherwise             → RED
    "UNVERIFIABLE",    # private fact, no public record     → AMBER + counsel
    "OPINION",         # not a factual assertion            → GREY, no research
]
```

Decomposition rules the prompt enforces:
- **Atomicity.** "Twice-convicted stalker sentenced to five years" → three claims: (1) convicted of stalking, (2) convicted twice, (3) sentenced to five years. Each verifies independently — exactly how the *Baby Reindeer* complaint itemises the falsehoods.
- **Opinion filtering.** "He was a difficult man" is `CHARACTERIZATION` → `OPINION`, no research spend. Defamation law protects opinion; the system must not flag it. This is domain knowledge as a classifier, and it also saves budget.
- **`polarity: negative` + subject living** is the escalation cocktail: those claims route to `core` processor and mandatory counsel review if not `VERIFIED`.

Expected volume: a 30-page true-story script yields **~60–120 claims** on top of ~100–150 conventional clearance elements.

### Agent 3 — `LedgerAgent` (deterministic)

Spans + claims → canonical entities. No LLM. **The hardest engineering in the build — dedicated owner from day 1.**

1. **Normalise** — casefold, strip honorifics, canonicalise formats.
2. **Coreference** — "Dr. Reyes" / "MIGUEL REYES" / "MIGUEL" / "he" = one entity. Exploit the screenplay's own character-cue blocks (ALL-CAPS names above dialogue) as free ground-truth structure prose doesn't have.
3. **Deduplicate** — a name appearing 40 times is one research task with 40 occurrence pointers; naïve extraction yields 2,000+ spans, target ledger ~250–350.
4. **Enrich** — jurisdiction set (shoot + distribution territories from project config), occurrence stats, dialogue-vs-action modality (they carry different legal risk).

```python
@dataclass
class ClearableElement:
    element_id: str                 # content hash → free draft-over-draft caching
    element_type: ElementType
    canonical_form: str
    aliases: list[str]
    occurrences: list[Occurrence]
    jurisdictions: list[str]
    claims: list[FactualClaim]      # for person/event types
    prior_risk: RiskTier
    status: ClearanceStatus
    evidence: list[Evidence]
    remedies: list[Remedy]
    monitor_handle: str | None
```

### Agent 4 — `RiskRouter` (deterministic, zero LLM)

A lookup table — auditable, testable, explainable in one sentence.

```yaml
# policy/routing.yaml
defaults: {provider: parallel_task, processor: lite}

rules:
  # ── claims (TRUE STORY core) ──
  - match: {kind: claim, polarity: negative, subject_alive: true}
    tier: CRITICAL
    processor: core
    schema: claim_verification_v1
    post: {if_not_verified: NEEDS_COUNSEL}

  - match: {kind: claim, type: QUOTE}
    tier: HIGH
    processor: base
    schema: quote_attribution_v1

  - match: {kind: claim}
    tier: HIGH
    processor: base
    schema: claim_verification_v1

  - match: {kind: claim, type: CHARACTERIZATION, verdict_hint: OPINION}
    tier: NONE            # no research; grey in UI

  # ── elements (COVERAGE core, retained) ──
  - match: {type: REAL_PERSON_DEPICTED}
    tier: CRITICAL
    processor: core
    schema: real_person_v2
    also: [findall_similar_persons, monitor]

  - match: {type: REAL_PERSON_IDENTIFIABLE}
    tier: CRITICAL
    processor: core
    schema: identifiability_v1
    also: [findall_matching_persons]

  - match: {type: MUSIC_CUE}
    tier: HIGH
    processor: base
    schema: music_rights_v1
    also: [monitor]                  # licences expire — §7.4

  - match: {type: [BUSINESS_NAME, TRADEMARK_LOGO]}
    tier: HIGH
    processor: base
    schema: trademark_v1
    also: [findall_registered_entities, monitor]

  - match: {type: [ARTWORK_VISUAL, TATTOO, FILM_CLIP]}
    tier: CRITICAL
    processor: core
    schema: visual_copyright_v1
    also: [extract_evidence_page]

  - match: {type: PERSON_NAME_FICTIONAL, occurrence_count: {gte: 5}}
    tier: HIGH
    processor: base
    schema: person_collision_v1

  - match: {type: PERSON_NAME_FICTIONAL}
    tier: MEDIUM
    processor: lite
    schema: person_collision_v1

  - match: {type: [PHONE_NUMBER, VEHICLE_PLATE, URL_HANDLE]}
    tier: LOW
    provider: deterministic_rules    # 555 convention etc.; no research

escalations:
  truth_claim_framing: +1_tier_on_all_person_adjacent   # the Baby Reindeer rule

budget_policy:
  per_script_ceiling_usd: 5.00
  on_exceed: degrade_tier            # core→base→lite before failing
  reserve_for_critical_usd: 1.50     # CRITICAL always gets its budget
```

**The `truth_claim_framing: +1 tier` escalation is one line of YAML implementing a doctrine two federal courts applied.** Say that sentence to a judge.

### Agent 5 — `ResearchSwarm` (ADK `ParallelAgent`)

Fan out claims + elements to the tool layer.

- **Concurrency:** bounded pool (default 32). Parallel's Task API supports ~2,000 req/min; our own budget governance is the binding constraint, not their limits.
- **Async:** `lite`/`base` awaited inline; `core`/`pro` dispatched with **webhook callback** to Cloud Run, run state parked in Firestore. *(For the demo build, the live path uses `-fast` processor variants — same price, lower latency, no live crawling — so the on-camera run stays synchronous; webhooks remain in the Monitor path.)*
- **Idempotency:** `claim_id`/`element_id` as idempotency keys; webhook replays safe.
- **Backpressure:** Pub/Sub depth drives workers; Cloud Tasks handles retry/backoff.

### Agent 6 — `Adjudicator` (LlmAgent, forced function calling)

Evidence → verdicts and statuses. The model is **structurally incapable** of emitting a verdict without evidence IDs and confidence — a schema constraint, not a prompt instruction:

```python
def record_verdict(
    claim_id: str,
    verdict: Literal["VERIFIED","UNSUPPORTED","CONTRADICTED","UNVERIFIABLE","OPINION"],
    supporting_evidence_ids: list[str],     # min_length=1 unless OPINION
    rationale: str,
    confidence: float,
) -> None: ...

def record_adjudication(   # for non-claim elements
    element_id: str,
    status: Literal["CLEAR","CLEAR_WITH_CONDITIONS","NOT_CLEAR",
                    "NEEDS_LICENSE","NEEDS_COUNSEL"],
    supporting_evidence_ids: list[str],
    rationale: str,
    confidence: float,
    conditions: list[str] | None = None,
) -> None: ...
```

**Deterministic post-checks** (applied after the model, not by it):

| Condition | Action |
|---|---|
| `confidence < 0.75` | → `NEEDS_COUNSEL`, review queue |
| Evidence sources conflict | → `NEEDS_COUNSEL`, both surfaced side by side |
| `CONTRADICTED` + subject living | → mandatory counsel item, regardless of confidence |
| CRITICAL tier adjudicated `CLEAR`/`VERIFIED` | → human confirmation before it renders green in the report |
| Any `is_fallback` evidence | → confidence capped 0.6 |
| Amber-claim density per named living person > threshold | → person-level `NEEDS_COUNSEL` (the *Fairstein* rule, §7.3) |

**The human review queue is a feature.** Every real clearance workflow ends with an attorney; a system that knows its own uncertainty reads as mature to enterprise judges.

### Agent 7 — `RemedyLoop` (ADK `LoopAgent`, max 3 iterations)

For every `CONTRADICTED` claim and `NOT_CLEAR` element: **propose a fix, then verify the fix through the same research path.**

```
propose(claim, evidence) ── Gemini: rewrite preserving dramatic function,
       │                    consistent with the verified record
       ▼
re-verify via Parallel ── same schema, same adjudication
       │
   VERIFIED? ──yes──▶ emit Remedy (redline), exit
       │no
   iteration < 3? ──yes──▶ loop, excluding failed candidates
       │no
       ▼
   NEEDS_COUNSEL
```

Remedies by kind:

| Kind | Remedy |
|---|---|
| `CONTRADICTED` claim | Rewritten line, **verified against the record**, preserving beat function |
| `UNSUPPORTED` claim, living subject | Soften to attributed opinion, fictionalise the character further, or counsel |
| `PERSON_NAME_FICTIONAL` collision | 3 verified alternate names (syllables, period, ethnicity, phonetics matched) |
| `MUSIC_CUE` | Sync + master licence request letters to identified rights holders |
| `PHONE/PLATE` | Deterministic substitution, no research |
| `TRUTH_CLAIM_FRAMING` | Disclaimer language + placement recommendation — encoded from the *Fairstein* settlement term (§7.3) |

**This closed loop is what separates the submission from a research wrapper** — propose, re-verify through the same path, and only then present as fixed. Genuinely agentic, with an objective success criterion.

### Agent 8 — `ReportAgent` (deterministic, templated)

No LLM in the rendering path — byte-stable, legally reviewable output.

| Artifact | Audience | Format |
|---|---|---|
| **Verdict-annotated script** | Writer, showrunner | Interactive web view + annotated PDF export |
| **Claim Register** | Counsel | Per-person claim table: verdicts, polarity, evidence, counsel items |
| **E&O Clearance Report** | Underwriter, production counsel | PDF; per-item evidence appendix with URLs and access timestamps |
| **Clearance Log** | Insurer checklist | CSV |
| **Monitor Manifest** | Producer | Active watches, cadence, last-checked |
| Script redline | Writer | Annotated PDF diff (`.fdx` write-back is roadmap) |

## 9.5 The Verdict Overlay — UI specification (the money shot)

The single most important build artifact after the pipeline itself. **Assign your best frontend engineer to this alone.**

- **Layout:** screenplay rendered in proper Courier screenplay format (fidelity matters — judges from the industry will notice), scene-by-scene, with a claim rail on the right.
- **Line states:** verified = quiet green underline; unsupported = amber; contradicted = red with a citation count badge; opinion = untouched grey. **Restraint is the design language** — a script drowning in highlights reads as noise; the demo script is engineered (§10) so red is rare and damning.
- **Click a red line →** evidence panel slides in: the claim as decomposed, verdict, confidence, Parallel citations with excerpts, retrieved-at timestamps, and the proposed verified rewrite with an *Apply* button that writes the redline.
- **Person view:** per-real-person rollup — N claims, verdict distribution, the *Fairstein* amber-density meter, counsel flags.
- **Masking:** collision matches to living private individuals render as `3 matching individuals · 4 sources · withheld pending counsel review`; the reveal is role-gated and audited (§9.11).
- **Cost meter:** persistent, ticking in cents, with tier breakdown on hover.
- **Streaming:** verdicts arrive via SSE as the swarm completes — the page *fills in live*, which is the demo's kinetic energy.

## 9.6 The `Evidence` envelope — the central contract

```python
@dataclass
class Evidence:
    evidence_id: str
    subject_id: str                  # claim_id or element_id
    question: str                    # what was asked
    finding: dict                    # conforms to the declared JSON schema
    citations: list[Citation]        # url, title, accessed_at, excerpt
    reasoning: str
    confidence: float                # calibrated 0..1
    provider: str                    # "parallel_task:core" | "gemini_grounded" | "cache"
    is_fallback: bool
    cost_cents: float
    latency_ms: int
    cached: bool
    retrieved_at: datetime
    schema_version: str
```

Parallel's **Basis framework** — citations, reasoning, excerpts, calibrated confidence per field — maps onto this nearly one-to-one: the deepest reason this partner fits this product. Providers that cannot populate `citations` are structurally disqualified from CRITICAL work.

## 9.7 Provider abstraction — seamless switching, concretely

```python
class ResearchProvider(ABC):
    name: str
    supports_citations: bool
    supports_async: bool
    async def investigate(self, question: str, output_schema: dict,
                          depth: Depth, jurisdictions: list[str]) -> Evidence: ...

REGISTRY = {
    "parallel_task":    ParallelTaskProvider(),
    "parallel_search":  ParallelSearchProvider(),
    "parallel_findall": ParallelFindAllProvider(),
    "parallel_extract": ParallelExtractProvider(),
    "parallel_monitor": ParallelMonitorProvider(),
    "gemini_grounded":  GeminiGroundedProvider(),   # fallback
    "cached":           CachedProvider(),           # content-addressed
    "mock":             MockProvider(),             # fixtures, CI, $0
}

def select(subject, budget) -> ResearchProvider:
    if cache.has(subject.id):               return REGISTRY["cached"]
    plan = routing_policy.match(subject)
    if not budget.can_afford(plan.cost):    plan = budget.degrade(plan)
    if not health.is_up(plan.provider):     plan = plan.fallback()
    return REGISTRY[plan.provider]
```

| Capability | Mechanism |
|---|---|
| Change vendor without touching agent code | Edit `routing.yaml`; agents see only MCP tool names |
| Develop at $0 | `mock` + `cached` |
| Deterministic, free demo recording | Warm cache on run 1; every later run $0 and identical |
| Survive outage / rate limit | Health check → `gemini_grounded`, stamped `is_fallback` |
| Survive budget exhaustion | `degrade()` walks core→base→lite; CRITICAL reserve protected |
| Prove it on camera | Flip a provider live, identical output shape — 10 seconds that say "production system" |

## 9.8 MCP tool boundary

Agents never see Parallel. They see **domain tools**:

```
clearance-tool-server (MCP over HTTP, Cloud Run)
├── verify_factual_claim(subject, claim, jurisdiction)          → Evidence
├── attribute_quote(quote, purported_speaker, era)              → Evidence
├── check_person_collision(name, profession, city, juris)       → Evidence
├── check_person_identifiability(attributes[], jurisdictions)   → Evidence
├── check_entity_registration(name, jurisdiction, classes)      → Evidence
├── check_trademark_status(mark, classes, territories)          → Evidence
├── check_music_rights(title, artist, year)                     → Evidence
├── check_publicity_rights(person, domicile)                    → Evidence
├── check_visual_copyright(description, creator_hint)           → Evidence
├── check_public_domain(work, jurisdiction)                     → Evidence
├── enumerate_matching_entities(pattern, jurisdiction)          → Evidence[]
├── capture_evidence_page(url)                                  → Evidence
└── watch_subject(subject_id, query, cadence)                   → MonitorHandle
```

A tool named `parallel_task_run` couples the agent to a vendor; `verify_factual_claim` couples it to the problem. The second survives a vendor change and produces better model tool-selection because the name states the purpose.

**Parallel's hosted MCPs** (Search MCP at `search-mcp.parallel.ai`, Task MCP) are OAuth-based, built for interactive clients (Claude Code, Cursor) — excellent for developer exploration, **wrong for a 200-subject fan-out**. The swarm uses the `parallel-web` Python SDK inside our own MCP server.

## 9.9 Control flow — end-to-end

```
Writer            Web App         Pipeline            Tools           Parallel
  │                  │               │                  │                │
  ├─ upload ────────▶│               │                  │                │
  │                  ├─ POST /runs ─▶│                  │                │
  │                  │               ├─ Ingest (Gemini, per-scene)       │
  │                  │               ├─ ClaimExtractor: 84 claims        │
  │                  │◀─ SSE: 84 claims · 212 elements ─┤                │
  │                  │               ├─ Ledger (dedupe) ├─ Router (tiers)│
  │                  │◀─ SSE: plan, projected $2.71 ────┤                │
  │                  │               ├─ Swarm ─────────▶├─ task_run ────▶│
  │                  │◀═ SSE: verdicts stream in, page fills, cost ticks═│
  │                  │               ├─ Adjudicator (forced fn)          │
  │                  │◀─ SSE: 61 green · 14 amber · 6 red · 3 counsel ──┤
  │                  │               ├─ RemedyLoop ────▶├─ re-verify ───▶│
  │                  │               ├─ ReportAgent                      │
  │◀─ verdict overlay + reports ─────┤                  │                │
  │                  │               ├─ watch_subject × 29 ─────────────▶│ Monitor
```

Weeks later:

```
Parallel Monitor ─webhook─▶ Cloud Run ─▶ re-adjudicate subject
                                          ├─ verdict changed? ─▶ Pub/Sub ─▶ Slack/email
                                          └─ Firestore + Monitor Manifest updated
```

Monitor watches, for a true-story production: trademark registrations, music-licence expiry windows, **depicted-person deaths** (publicity rights change by state), **related litigation filings**, and new records bearing on verified claims.

## 9.10 Data model and storage

| Store | Contents | Why |
|---|---|---|
| **Firestore** | Runs, elements, claims, evidence, verdicts, monitors, review queue | Low-latency UI reads; real-time listeners drive SSE for free |
| **BigQuery** | Precedent corpus, Litigation Set results, cost telemetry | Analytics; **Vector Search over past adjudications = precedent RAG** ("cleared this element type in this jurisdiction 40 times; here is the pattern") |
| **GCS** | Scripts, PDFs, captured evidence pages | Blob + lifecycle retention |
| **Secret Manager** | Parallel key, webhook signing secret | Never env vars, never repo |

```
/projects/{id}: title, truth_claim_framing, jurisdictions[], budget, iam
/projects/{id}/runs/{run_id}: draft_version, script_hash, status, cost_cents, parent_run_id
/projects/{id}/runs/{run_id}/elements/{element_id}: ClearableElement
/projects/{id}/runs/{run_id}/claims/{claim_id}: FactualClaim
/.../evidence/{evidence_id}: Evidence
/projects/{id}/monitors/{monitor_id}: subject_id, parallel_id, cadence, last_event
/review_queue/{item_id}: subject_id, reason, assigned_to, resolution
```

**Diff-based re-verification:** `claim_id` and `element_id` are content hashes, so draft *n+1* researches only the delta; `parent_run_id` chains lineage. **~95% cost/time reduction on a typical revision** — a 15-second demo beat and the thing that makes series economics work.

## 9.11 Security, IAM, governance

The brief name-checks *"the Studio Head enforcing Cloud IAM security and governance across multi-agent workflows."* Show it.

| Custom role | Sees | Rationale |
|---|---|---|
| `truestory.counsel` | Everything, incl. unmasked identities + full evidence | The accountable human |
| `truestory.producer` | Verdict counts, risk posture, cost, alerts | Manages; doesn't read evidence |
| `truestory.writer` | Own draft's overlay + rewrites only | No cross-project access |
| `truestory.underwriter` | Final report package, read-only, watermarked | External party |

Controls: per-project isolation enforced in **Firestore security rules** (not just app code); 7-year evidence retention default (matches the E&O claims-made tail); every adjudication, override, and unmasking audited to Cloud Logging with the acting principal; **webhook signature verification** on all Parallel callbacks; Gemini **safety settings** configured to analyse scripts containing violence/slurs/sexual content without refusing (analysis ≠ generation) — and if a scene still blocks, it is flagged for manual breakdown, never silently skipped.

**Show the role switch on camera for four seconds** — the writer view with the evidence panel absent is instantly legible governance.

## 9.12 Privacy design — the part most teams get wrong

The system's output is *assertions about real people*. Built carelessly it is a defamation engine pointed at the people it protects.

1. **Default masking** of living private individuals: `3 matching individuals · 4 sources · withheld pending counsel review`. Stored, not displayed.
2. **Reveal gated** behind `truestory.counsel` + audit record.
3. **No masked identity enters a generated artifact** without explicit counsel release.
4. **Public-figure test documented** — analysing a public figure's documented record is a different act from profiling a private person.
5. **Demo recordings always masked**, and the demo subject is deceased (§10).

Ship it as a named feature — **Privacy-Preserving Evidence Handling** — in the architecture diagram.

## 9.13 Failure modes and degradation

| Failure | Detection | Response |
|---|---|---|
| Parallel rate-limited | 429 | Cloud Tasks backoff; sustained → `gemini_grounded`, stamped fallback |
| Low provider confidence | Basis score < threshold | Escalate one tier once; still low → `NEEDS_COUNSEL` |
| Sources conflict | Post-check | `NEEDS_COUNSEL`, both shown side by side |
| Budget exhausted mid-run | BudgetGovernor | Degrade core→base→lite; CRITICAL reserve intact; report carries a coverage-quality warning |
| Webhook never arrives | Scheduler sweep of stale PENDING > tier SLA | Poll `task_run.result`; after 2 attempts → `RESEARCH_FAILED`, escalate |
| Gemini safety block on violent script content | Safety response | Retry adjusted config; still blocked → flag scene for manual breakdown, never skip silently |
| Ingest/extraction misses | Eval recall metric | Reported honestly as recall, not hidden |
| Agent Engine cold start | Latency | Min-instance warm pool through judging window |

**P5 in practice:** the report always states its own coverage quality on the front page. An insurer — and a judge — prefers a caveated report to a confident wrong one.

## 9.14 Observability

Every `Evidence` carries `cost_cents`, `latency_ms`, `provider`, `cached` → BigQuery:

- **Live cost meter** (the demo's best recurring visual)
- Cost per script / claim type / tier — the unit-economics slide writes itself
- Cache hit rate (>90% by draft 3)
- Fallback rate (provider health)
- **Counsel-escalation rate** — the human-workload number a studio buyer asks about first
- Verdict distribution over time — rubric calibration, empirically

Cloud Trace spans per agent stage; Cloud Logging on every adjudication with evidence IDs.

## 9.15 Deployment topology

| Component | Runtime | Notes |
|---|---|---|
| `TrueStoryPipeline` (ADK) | Vertex AI Agent Engine | Min-instances warm through judging |
| `clearance-tool-server` (MCP) | Cloud Run | 0→N, concurrency 80 |
| Webhook receiver | Cloud Run | Separate service — must stay up while pipeline idles |
| Web app | Cloud Run | SSE |
| Queue / retry / sweep | Pub/Sub · Cloud Tasks · Cloud Scheduler | Free-tier friendly |

**Google Cloud services in genuine runtime use:** Vertex AI (Gemini), Agent Engine, Cloud Run, Pub/Sub, Cloud Tasks, Cloud Scheduler, Firestore, BigQuery (+Vector Search), GCS, Secret Manager, Cloud IAM, Cloud Logging/Trace. Comfortably satisfies *"imported and called in code, not just named in the README."*

## 9.16 External API surface

```
POST   /v1/projects                      create; jurisdictions + budget + framing
POST   /v1/projects/{id}/runs            upload script, start
GET    /v1/runs/{id}                     status + verdict summary
GET    /v1/runs/{id}/stream              SSE — verdicts, progress, cost
GET    /v1/runs/{id}/claims              claim register, filterable
GET    /v1/runs/{id}/elements            clearance ledger
GET    /v1/runs/{id}/overlay             verdict-annotated script (JSON for UI)
GET    /v1/runs/{id}/report.pdf          E&O clearance report
GET    /v1/runs/{id}/claims.pdf          claim register export
POST   /v1/claims/{id}/apply_remedy      writes redline; audited
POST   /v1/subjects/{id}/override        counsel override; audited
GET    /v1/projects/{id}/monitors        active watches
POST   /webhooks/parallel                signed callback receiver
```

**A2A:** AgentCard at `/.well-known/agent.json` exposing `truestory.assess` / `truestory.status` — shipped as a documented spec in the hackathon build (live endpoint is roadmap; §16 cut list), with `CounselAgent` described as the external A2A escalation peer outside our trust boundary.

---

## 10. The Demo Script — An Original Screenplay Engineered for the Demo

The demo does **not** run on a real production's script (rights problems in the repo) and does **not** surface living private individuals (§18). Instead, Workstream F writes an original 25–30 page "based on a true story" short — a fictional biopic built so that every beat of the video is scripted into the source material itself.

**Subject:** a real, safely-deceased public figure with a well-documented public record — e.g. a mid-century athlete, aviator, or Cold War-era scientist. Selection criteria: dead >25 years (post-mortem publicity terms analysable but no living plaintiff), abundant contemporaneous records for Parallel to find, and zero living private individuals depicted. ⚠️ *Counsel-check the chosen figure's estate posture and the relevant state's post-mortem publicity term before locking the subject.*

**Seeded, deliberately:**

| Seed | Count | Demonstrates |
|---|---|---|
| False factual claims about the subject (wrong record, wrong year, invented conviction-adjacent fact) | 3 | The red line + citations — the *Queen's Gambit* beat |
| Unsupported claims (plausible, no record either way) | 2 | Amber + the *Fairstein* density meter |
| A verifiably true but surprising claim | 2 | Green with receipts — proves the system isn't a paranoia engine |
| A pure opinion line ("he was impossible to work with") | 1 | Grey — the OPINION filter saving budget and respecting defamation law |
| "THIS IS A TRUE STORY" title card | 1 | The project-level escalation firing on screen |
| Fictional supporting character whose name collides with real registered professionals | 1 | Masked collision panel + verified rename via RemedyLoop |
| A named song of the era | 1 | Music rights schema + a Monitor with an expiry window |
| A described visible artwork (poster on a wall) | 1 | Visual-copyright path (*Whitmill*/*Ringgold* beat) |
| A real business name in signage | 1 | Trademark path + art note |

Expected pipeline output on this script: **~84 claims + ~120 elements ≈ 200 research subjects**, resolving to roughly **61 green · 14 amber · 6 red · a handful of counsel items** — dense enough to impress, sparse enough that every red line on screen is legible and damning.

The script is written once, cache-warmed once, and every recorded take thereafter is deterministic and free (§13.3).

---

## 11. Protocol Architecture — ADK vs MCP vs A2A vs LangGraph

### 11.1 ADK is the core. Not LangGraph.

The hackathon's own resources page: *"We recommend building your agents natively using the Agent Development Kit (ADK) instead of external wrapper libraries."* Google judges will grade against their own sentence; building the core on LangGraph is choosing to lose points for no gain.

Substantively, ADK's workflow agents deliver Principle P1 directly:

| ADK primitive | Use | Why not an LLM |
|---|---|---|
| `SequentialAgent` | Pipeline spine | Stage order is fixed by the domain |
| `ParallelAgent` | Research fan-out | Concurrency is infrastructure |
| `LoopAgent` | Remedy propose→verify, ≤3 | Termination is objective: does it verify? |
| `LlmAgent` | Ingest, ClaimExtract, Adjudicate, Propose | The only four places judgement is required |

When a judge asks *"how do you know this is reproducible?"* — point at the tree. Most submissions will be one `LlmAgent` with a bag of tools and no answer.

Install: `pip install "google-cloud-aiplatform[agent_engines,adk]>=1.101.0"`

### 11.2 MCP at the tool boundary

§9.8. Buys vendor swappability, a test seam, better tool selection, and alignment with the brief's own *"managed MCP servers"* / *"managed protocol adapters"* language.

### 11.3 A2A at organisational boundaries only

A2A is for agents across trust/deployment boundaries; using it for internal control flow adds latency and buys nothing. Two legitimate uses: the published **AgentCard** (insurer/studio/law-firm agents calling TRUE STORY) and **CounselAgent** as the external escalation peer. In the hackathon build the AgentCard ships as a documented spec (cut list, §16).

### 11.4 LangGraph: no

Not as core. Team members who know it can port the mental model — `StateGraph`→`SequentialAgent`, conditional edges→routing policy, `Send`→`ParallelAgent` — not the dependency.

### 11.5 The sentence for the video

> *"ADK for orchestration, MCP for tools, A2A at the boundary — each protocol where it belongs."*

---

## 12. Parallel Integration and Cost Model

### 12.1 Pricing

⚠️ *From Parallel's published materials, some dating to the Task API launch post. **Re-verify at `docs.parallel.ai/getting-started/pricing` before finalising routing.***

| API | Cost |
|---|---|
| Task — **Lite** | $5 / 1,000 runs |
| Task — **Base** | $10 / 1,000 runs |
| Task — **Core** | $25 / 1,000 runs |
| Task — Pro/Ultra | Higher; exceptional CRITICAL items only |
| **`-fast` variants** | Same price as standard; lower latency (no live crawl) — the demo's live path |
| **Search** | $0.001 + $0.001/additional result (advanced mode $0.005 base) |
| **Monitor** | Lite $3 / Base $10 per 1,000 |
| **FindAll** | Preview $0.10 + $0.00/match (testing) · Base $0.25 + $0.03/match · Core $2.00 + $0.15/match |

**Free allowance:** signup credit + **recurring $5/month free allowance per account** + up to 16,000 free requests to start + up to $250 in credits if qualified — **apply with the hackathon entry; it is an email.** Rate limits: Task ~2,000 req/min; FindAll ~25/hour. Parallel is **SOC 2 Type 2** certified — one line in the pitch, since we handle pre-release scripts.

### 12.2 Cost of one full TRUE STORY run (demo script, ~200 subjects)

| Tier | Subjects | Unit | Cost |
|---|---|---|---|
| Lite | 120 | $0.005 | $0.60 |
| Base | 55 | $0.010 | $0.55 |
| Core | 25 | $0.025 | $0.63 |
| FindAll (Base, 2 queries) | — | ~$0.25+matches | ~$0.40 |
| Search (interactive) | ~50 | $0.001 | $0.05 |
| Monitors (29, first month) | — | — | ~$0.09 |
| **Total** | | | **≈ $2.32** |

A full 110-page feature scales to ~$3–5. **Versus $1,000–$3,000 and days-to-weeks for the human equivalent** — a ~500× cost and ~1000× time reduction, both defensible from published vendor pricing. **Two full runs per month per account sit inside the free allowance**; each developer holds their own key. Parallel spend for this project: effectively zero.

### 12.3 Three moves that make the demo literally free

1. **`CachedProvider`** keyed on `(subject_type, canonical_value, jurisdiction)` — warm once, then every recorded take is $0 and deterministic. Standard production practice, not a shortcut.
2. **FindAll Preview tier** ($0.10, $0.00/match) for all development iteration — it is explicitly the testing tier.
3. **`MockProvider`** fixtures for CI and the labelled eval set.

### 12.4 Google Cloud cost

$300 trial + the **$100 hackathon credit form** (1–5 business days, while supplies last — **apply week 1**) covers Agent Engine, Cloud Run, Pub/Sub, Firestore, BigQuery, Scheduler; most have perpetual free tiers. Gemini inference is the only meaningful spend and that budget is accepted. Dropping Document AI removed a service, a failure mode, and a line item.

---

## 13. Repository Structure

```
truestory/
├── LICENSE                          # Apache-2.0, verbatim, root — GitHub must auto-detect
├── README.md                        # architecture, setup, runtime proof of both integrations
├── agents/                          # ADK
│   ├── pipeline.py                  # SequentialAgent root
│   ├── ingest.py                    # LlmAgent — Gemini, per-scene
│   ├── claims.py                    # LlmAgent — ClaimExtractor
│   ├── ledger.py  router.py         # deterministic
│   ├── swarm.py                     # ParallelAgent
│   ├── adjudicator.py               # LlmAgent, forced function calling
│   ├── remedy.py                    # LoopAgent
│   └── report.py                    # templated
├── mcp/clearance_tool_server/       # domain tools over MCP
├── providers/                       # the swap layer
│   ├── base.py                      # ResearchProvider ABC + Evidence
│   ├── parallel_task.py  parallel_search.py  parallel_findall.py
│   ├── parallel_extract.py  parallel_monitor.py
│   ├── gemini_grounded.py  cached.py  mock.py
│   └── registry.py  budget.py
├── policy/
│   ├── routing.yaml  rubric.yaml  jurisdictions.yaml
├── schemas/
│   ├── claim_verification_v1.json   quote_attribution_v1.json
│   ├── identifiability_v1.json      person_collision_v1.json
│   ├── real_person_v2.json          trademark_v1.json
│   ├── music_rights_v1.json         visual_copyright_v1.json
├── webhooks/                        # Cloud Run — Monitor/Task callbacks, signed
├── web/                             # Next.js: verdict overlay, claim dashboard, cost meter
├── demo/
│   └── screenplay/                  # the original demo script (§10) — ours, no rights issues
├── a2a/agent_card.json              # spec
├── eval/
│   ├── litigation_set/              # reconstructed real cases
│   ├── labeled_script/              # hand-labelled ground truth
│   ├── fixtures/                    # recorded provider responses
│   └── run_eval.py
├── infra/                           # Terraform: IAM, services, secrets
└── docs/ARCHITECTURE.md
```

`eval/` is the differentiator. Almost no hackathon submission ships one.

---

## 14. Evaluation — The Litigation Set

Two evals, both producing numbers stated on camera.

### 14.1 Eval A — recall/precision on the labelled demo script

Two people **independently** hand-label every claim and clearable element in the demo screenplay (~200 subjects); adjudicate disagreements; that is ground truth. Run ingest + claims + ledger; report **claim recall**, **element recall**, **precision**, **dedup accuracy**, and **verdict accuracy against the seeded answers** (we know which claims are false — we wrote them). Report honestly: a 0.92 stated plainly beats a claimed 1.00.

### 14.2 Eval B — the Litigation Set (what wins the track)

For each real dispute in §7: reconstruct the offending element/claim as it appeared, embed it in a neutral scene, run TRUE STORY **blind**, record whether the specific item at issue was flagged, at what tier, with what verdict, and whether the evidence supports the correct call.

**Include the defence-side cases** (Sarver, Greene, de Havilland, Louis Vuitton): a system that flags everything is useless, so correctly returning `CLEAR_WITH_CONDITIONS` on First-Amendment-protected uses matters as much as catching the failures.

> *"We ran the pipeline blind against the decade's most famous entertainment lawsuits. It flagged the exact line at issue in the Queen's Gambit case, the identifiability cluster in Baby Reindeer, and the unsupported-conduct scenes in When They See Us — and correctly declined to flag the cases the studios went on to win."*

If that sentence is true, it wins the track. The judges know these cases; the number lands as recognition, not statistics. **Nobody can fake this in the final week.**

---

## 15. Build Plan — 26 Days

### 15.1 Workstreams

| Stream | Owner | Scope |
|---|---|---|
| **A. Ingest, Claims & Ledger** | 2 eng | Gemini parsing, claim decomposition, coref, dedupe — hardest quality problem |
| **B. Research & Providers** | 2 eng | Provider layer, MCP server, Parallel schemas, BudgetGovernor |
| **C. Adjudication & Remedy** | 1–2 eng | Rubric, forced fn calling, verdict post-checks, remedy loop |
| **D. Verdict Overlay & Artifacts** | 2 eng | **Best frontend engineer solely on the overlay.** PDF/CSV generation second. |
| **E. Infra & Async** | 1 eng | Agent Engine, Cloud Run, webhooks, Pub/Sub, IAM, Terraform |
| **F. Screenplay, Eval & Legal Research** | 2 people | Write the demo script (§10), label ground truth, build the Litigation Set, **verify every ⚠️ against primary sources** |
| **G. Video & Submission** | 1 person | Owns the video from day 1, not day 23 |

### 15.2 Timeline

| Days | Milestone |
|---|---|
| **1–2** | GCP + Parallel credit applications. Repo, LICENSE, CI. Taxonomy + `FactualClaim` model locked. Demo-subject counsel check. |
| **1–4** | **Parallel output schemas designed** — highest-leverage work; get the JSON right and downstream is easy. ADK hello-world deployed to Agent Engine **on day 3**. Webhook receiver live. Demo screenplay drafted. |
| **5–12** | Ingest + ClaimExtractor + ledger + router. Swarm on `-fast` processors. **Ground truth labelled this week.** Overlay skeleton rendering with mock verdicts. |
| **13–18** | Adjudicator + post-checks, remedy loop, overlay polish, claim dashboard, report PDFs, IAM roles, masking. |
| **19–22** | Monitor end-to-end (recorded insert if flaky). Diff re-verification. Litigation Set blind runs. Storyboard-still multimodal beat. |
| **23–25** | Video. README. URL hardening. **Three outsiders follow the README from scratch.** Every ⚠️ re-verified. |
| **26** | Buffer. **Submit a day early** — Devpost slows near a 5pm EDT deadline. |

### 15.3 Cut list (cut from the bottom)

```
── THE SUBMISSION ────────────────────────────────
 1. Ingest + claim extraction + ledger
 2. Risk routing (incl. truth-claim escalation)
 3. Research swarm (Parallel Task, -fast live path)
 4. Adjudication with evidence + post-checks
 5. Verdict Overlay UI
 6. E&O report + claim register PDFs
── THE WIN ───────────────────────────────────────
 7. Remedy loop (propose → re-verify)
 8. Monitor / Living Clearance (recorded insert acceptable)
 9. Litigation Set eval
10. Diff-based re-verification
── UPSIDE ────────────────────────────────────────
11. Storyboard-still multimodal beat
12. Provider hot-swap on camera
13. BigQuery precedent RAG
── ALREADY CUT (roadmap) ─────────────────────────
    Art-dept sheet · live A2A endpoint (spec ships) ·
    .fdx write-back (PDF redline ships) · dailies video path
```

### 15.4 Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Claim decomposition quality (atomicity, opinion filter) | **High** | It is Workstream A's second engineer's whole job; seeded script gives known-answer tests from day 5 |
| Entity dedup harder than expected | **High** | Dedicated owner; character-cue blocks give free structure |
| Judge-taste mismatch | **Low (by design)** | The demo *is* a drama about a real person; famous cases open the video |
| Demo fragility on judging day | **Low–medium** | Live path = one Cloud Run URL + one cache-warmed run on `-fast`; Monitor + multimodal as recorded inserts |
| A legal fact wrong on camera | Low / **catastrophic** | Appendix C two-person verification; nothing flagged ⚠️ ships unchecked |
| Track crowding assumption wrong | Medium | Gallery check ~31 Aug; response = push the eval, never panic-switch |
| Agent Engine deployment friction | Medium | Hello-world deployed day 3 |
| Demo URL dead | Medium | Clean-network test; warm min-instances through judging |

---

## 16. Demo Video — 3 Minutes

Rules: **the project functioning as built, not a cinematic trailer.** Fast, real, dense. Pre-recorded inserts of the system genuinely running are compliant; staged mockups are not.

| Time | Beat |
|---|---|
| **0:00–0:20** | Cold open: the *Baby Reindeer* title card. The *Queen's Gambit* line. *When They See Us*. **"$175 million in claims from three shows. Each began as a single unverified line in a script."** |
| **0:20–0:35** | Drag the screenplay in. "THIS IS A TRUE STORY" card detected → escalation banner fires. Timer starts. |
| **0:35–1:15** | **The overlay fills in live.** Verdicts stream: lines turn green, amber — then one turns **red**. Cost meter ticking in cents. 84 claims, 212 elements on the counters. |
| **1:15–1:50** | Click the red line. Evidence panel: the decomposed claim, CONTRADICTED, the Parallel citations with excerpts, confidence 0.94. **RemedyLoop proposes a rewrite → re-verifies it against the record → VERIFIED → Apply → the redline lands.** *(The Queen's Gambit lawsuit, prevented, in 35 seconds.)* |
| **1:50–2:10** | The masked collision panel ("3 matching individuals · withheld pending counsel review") + role switch to counsel (4 seconds). Person view: the amber-density meter — the *Fairstein* rule on screen. |
| **2:10–2:30** | **Monitor fires** (recorded insert): week 3, a music licence enters its expiry window → webhook → Slack alert. *"A clearance report is a photograph. Rights are a film."* |
| **2:30–2:45** | The E&O PDF + claim register. **"Six minutes. $2.32."** Then the eval: *"Blind against the decade's most famous entertainment lawsuits, it caught the exact item at issue in each — and cleared the ones the studios won."* |
| **2:45–3:00** | Architecture card. *"ADK for orchestration, MCP for tools, A2A at the boundary."* Live URL. |

---

## 17. Legal and Ethical Guardrails

**Non-negotiable — in the product, the README, and the video.**

1. **Decision support for a clearance attorney, not legal advice.** Every clearance report in the industry is reviewed by production counsel; we automate the research and the document, not the judgement. Said plainly, the legal angle is a strength; left ambiguous, one sharp question ends the pitch.
2. **Never run the demo on a living private individual.** The demo subject is deceased and public (§10); collision hits on living people render masked, always.
3. **Masking on by default**, reveal role-gated and audited (§9.12).
4. **The Litigation Set is retrospective only** — published disputes, public record.
5. **The human review queue is visible in the UI.** Do not hide it.
6. **Claim only measured accuracy** — report the eval numbers including the misses.
7. **Nothing flagged ⚠️ ships unverified.** Appendix C, two-person rule.
8. **Verdicts about real people carry the system's own epistemic honesty:** `UNSUPPORTED` is not `FALSE`; the UI language and the report language keep that distinction, because collapsing it is exactly the defamation the tool exists to prevent.

---

## 18. Post-Hackathon Roadmap

| Phase | Product |
|---|---|
| **Now** | TRUE STORY: fact verification + clearance report + claim register for adapted-reality productions. One-off fee replacing a $1–3K manual report. |
| **+3 mo** | **Living Clearance** subscription — Monitors for the commercial life of the title (facts, licences, litigation, deaths). Recurring revenue no incumbent offers. |
| **+6 mo** | **Full E&O package automation** — title report, copyright report, chain-of-title assembly, cue sheets: own the whole insurer checklist (§5.4). Broaden from true-story to all narrative (the full COVERAGE scope). |
| **+9 mo** | **The AI provenance layer** (§8): `AI_GENERATED_ASSET` + `DIGITAL_REPLICA` types; training-data provenance and human-authorship logs; the dossier an underwriter needs for affirmative AI coverage. True-story productions are exactly where digital replicas are heading — same wedge. |
| **+12 mo** | **Carrier partnership** — an insurer accepting TRUE STORY output natively or pricing premium off it. Following HSB's AI Liability launch (March 2026), an active market. |

**Strategic fit with an AI-filmmaking studio:** compliance infrastructure adjacent to generative filmmaking, zero overlap with generative-model IP — and the single hardest problem an AI-native production faces, since AI productions are currently the hardest projects in the world to insure. We are our own first customer. The moat is not the open-sourced pipeline; it is the **precedent corpus, jurisdiction rulebook, calibrated rubric, and carrier relationships** — none of which is in the repo.

---

## Appendix A — Subject Type → Parallel Configuration Matrix

| Subject | Tier | Processor | Schema | Also |
|---|---|---|---|---|
| Claim, negative polarity, living subject | CRITICAL | core | `claim_verification_v1` | counsel if not VERIFIED |
| Claim, QUOTE | HIGH | base | `quote_attribution_v1` | — |
| Claim, other | HIGH | base | `claim_verification_v1` | — |
| Claim, CHARACTERIZATION → OPINION | NONE | — | — | grey; no spend |
| `REAL_PERSON_DEPICTED` | CRITICAL | core | `real_person_v2` | FindAll, Monitor |
| `REAL_PERSON_IDENTIFIABLE` | CRITICAL | core | `identifiability_v1` | FindAll |
| `ARTWORK_VISUAL`/`TATTOO`/`FILM_CLIP` | CRITICAL | core | `visual_copyright_v1` | Extract |
| `MUSIC_CUE` | HIGH | base | `music_rights_v1` | **Monitor** |
| `BUSINESS_NAME`/`TRADEMARK_LOGO` | HIGH | base | `trademark_v1` | FindAll, Monitor |
| `PERSON_NAME_FICTIONAL` ≥5 occ. | HIGH | base | `person_collision_v1` | FindAll |
| `PERSON_NAME_FICTIONAL` | MEDIUM | lite | `person_collision_v1` | — |
| `REAL_LOCATION`/`ORGANIZATION` | MEDIUM | lite | `entity_v1` | — |
| `SOURCE_MATERIAL` | HIGH | base | `public_domain_v1` | — |
| `PHONE`/`PLATE`/`URL_HANDLE` | LOW | deterministic | — | — |
| *(project)* `TRUTH_CLAIM_FRAMING` | — | — | — | +1 tier on all person-adjacent |

## Appendix B — Sample Parallel Output Schemas

```jsonc
// claim_verification_v1 — the TRUE STORY workhorse
{
  "claim_restated": "…",
  "verdict": "supported|contradicted|no_record",
  "supporting_facts": [
    {"fact": "…", "source_url": "…", "source_type": "primary|secondary", "date": "…"}
  ],
  "contradicting_facts": [ /* same shape */ ],
  "subject_alive": true,
  "subject_public_figure_status": "public|limited_purpose|private",
  "record_quality": "strong|moderate|thin"
}

// quote_attribution_v1
{
  "quote_documented": true,
  "earliest_source": {"url": "…", "date": "…", "context": "…"},
  "commonly_misattributed": false,
  "actual_originator": "…"
}

// real_person_v2
{
  "person_exists": true,
  "alive": false,
  "death_year": 1998,
  "domicile_state": "CA",
  "postmortem_publicity_term_years": 70,
  "public_figure_status": "public|limited_purpose|private",
  "estate_representative": "…"
}

// music_rights_v1
{
  "composition_rights_holder": "…",
  "master_rights_holder": "…",
  "public_domain_status": "pd|in_copyright|disputed",
  "publication_year": 1971,
  "territories_verified": ["US","EU"],
  "sync_contact": "…", "master_contact": "…",
  "typical_license_term_years": 10        // drives Monitor cadence
}

// person_collision_v1
{
  "real_persons_matching": [
    {"name":"…","city":"…","profession":"…","source_url":"…","prominence":"low|medium|high"}
  ],
  "collision_risk": "none|low|medium|high",
  "same_profession_same_locale": true,
  "recommended_action": "clear|rename|add_disclaimer|counsel_review"
}
```

## Appendix C — Verification Checklist ⚠️

**Nothing here goes on camera or into the README until a human has checked it against a primary source. Two-person rule.**

- [ ] **Baby Reindeer status at the Ninth Circuit** — the fact most likely to have moved; check the docket the week of recording
- [ ] **Queen's Gambit** ruling judge's name (Virginia Phillips per one source only)
- [ ] **Ringgold v. BET** — citation and holding
- [ ] **Caterpillar v. Walt Disney** — citation and outcome
- [ ] **NO FAKES Act** current status (trackers disagree)
- [ ] **EU AI Act** — specific transparency article and phase-in date
- [ ] **Act One / De Forest Research** brand relationship (inferred from shared website)
- [ ] **Parallel pricing** — re-check `docs.parallel.ai/getting-started/pricing`; several figures date to the launch post
- [ ] **Demo-subject estate posture** and the relevant state's post-mortem publicity term (counsel check, §10)
- [ ] Any **documented AI-likeness dispute in film/TV** — gap; assert none without a source
- [ ] Any **production permanently blocked by E&O denial** — gap; brokers assert generically, no named example confirmed
- [ ] True-crime **commissioning-volume statistic**, if wanted for the deck — none asserted here

## Appendix D — Known Gaps

| Gap | Handling |
|---|---|
| No public E&O claim-frequency statistics | Say so; do not invent a percentage |
| Market-size vendor estimates disagree ~2× | Ranges, attributed; lead with bottom-up production-volume TAM |
| Premium figures are broker self-published | Label as estimates |
| Case law is US-centric (First Amendment / anti-SLAPP) | Clearance risk differs by jurisdiction; `jurisdictions.yaml` is a real product surface |
| `UNSUPPORTED` ≠ `FALSE` | The epistemics are load-bearing (§17.8); UI and report language preserve the distinction |
| A stealth competitor may exist | Claim "no *publicly available* product does this" — accurate |
| Track-crowding estimates are inference | Gallery check ~31 Aug; response is the eval, not a track switch |

---

*End of document.*
