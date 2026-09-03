"use client";

/**
 * TRUE STORY · the public one-pager.
 *
 * Home, About, The Engine, Contact, on one cinematic scroll. Everything here
 * is a pitch for the product; the product itself lives at /workspace, reached
 * by the "Enter workspace" button. Content is drawn from the README and kept
 * to what the system actually does — the same honesty the report demands.
 */

import Image from "next/image";
import Link from "next/link";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";
import "./marketing.css";

const CONTACT_EMAIL = "d.ext1nctstudio@gmail.com";
const REPO_URL = "https://github.com/dext1nctstudio/True-Story";

const NAV = [
  { href: "#home", label: "Home" },
  { href: "#about", label: "About" },
  { href: "#engine", label: "The Engine" },
  { href: "#contact", label: "Contact" },
];

const STAGES = [
  { i: "01", name: "Ingest", kind: "LLM", llm: true, desc: "Script text to typed spans." },
  { i: "02", name: "Claims", kind: "LLM", llm: true, desc: "Spans to atomic factual claims." },
  { i: "03", name: "Ledger", kind: "Deterministic", llm: false, desc: "Coreference and deduplication." },
  { i: "04", name: "Router", kind: "Deterministic", llm: false, desc: "Risk routing by policy table." },
  { i: "05", name: "Research", kind: "Parallel", llm: false, desc: "Bounded, metered fan-out." },
  { i: "06", name: "Adjudicator", kind: "LLM", llm: true, desc: "Evidence to verdicts. A citation is required." },
  { i: "07", name: "Remedy", kind: "LLM", llm: true, desc: "Propose a rewrite, verify it, at most three times." },
  { i: "08", name: "Report", kind: "Deterministic", llm: false, desc: "Templated clearance artifacts." },
];

const GATES = [
  {
    h: "Identity, before anything is researched",
    p: "Who is this subject? Wikidata answers first, free and immediate. Nobody bears the name means no dispatch, no spend, no citations about somebody else.",
  },
  {
    h: "Every citation classified from its host",
    p: "Official record, registry, archive, reporting, trade, reference or user-generated. The table wins in both directions, and machine encyclopaedias are excluded at the API.",
  },
  {
    h: "No source is evidence until it is quoted",
    p: "Per source, a stance and a verbatim span, then located in the retrieved page by string search. A quote the model invented cannot be found, and is dropped.",
  },
  {
    h: "Corroboration sets the ceiling",
    p: "Independent registrable domains are counted, and confidence may not exceed what the record supports. A negative claim about a living person needs a recognised record.",
  },
];

const VERDICTS = [
  { k: "green", name: "Verified", desc: "The record supports the claim, with the citations attached." },
  { k: "amber", name: "Unsupported", desc: "The record cannot speak to it. Not false, and not defensible either." },
  { k: "red", name: "Contradicted", desc: "The record contradicts it, with a recognised source behind the call." },
  { k: "grey", name: "Opinion", desc: "Protected speech. Classified, never researched, never coloured." },
];

const FACTS = [
  { n: "~$2", label: "Cost per feature", text: "A two-to-three-dollar run against a one-to-three-thousand-dollar manual report." },
  { n: "min", label: "Turnaround", text: "Minutes, not the three to seven business days a manual clearance takes." },
  { n: "3×", label: "Atomic claims", text: "“A twice-convicted stalker sentenced to five years” is three claims, each checked alone." },
  { n: "∞", label: "Living clearance", text: "A report is a photograph; rights are a film. Monitors keep watching after filing." },
];

function IconSearch() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
function IconMail() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}
function IconCode() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m8 8-4 4 4 4M16 8l4 4-4 4" />
    </svg>
  );
}
function IconFilm() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4" />
    </svg>
  );
}

export default function Marketing() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const [form, setForm] = useState({ email: "", name: "", subject: "", message: "" });
  const mailto = useMemo(() => {
    const subject = form.subject || "TRUE STORY enquiry";
    const body = `${form.message}\n\nFrom: ${form.name || "Anonymous"}${form.email ? ` (${form.email})` : ""}`;
    return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }, [form]);

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="mk">
      {/* ── nav ─────────────────────────────────────────────────────────── */}
      <nav className={`mk-nav ${scrolled ? "scrolled" : ""}`}>
        <a href="#home" className="mk-brand" aria-label="True Story home">
          <Image src="/logo-light.png" alt="True Story" width={1580} height={553} priority />
        </a>
        <div className={`mk-nav-links ${menuOpen ? "open" : ""}`} onClick={() => setMenuOpen(false)}>
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="mk-nav-link">
              {n.label}
            </a>
          ))}
          <Link href="/workspace" className="mk-cta mobile-only-cta">
            Enter workspace
          </Link>
        </div>
        <span className="mk-nav-spacer" />
        <Link href="/workspace" className="mk-cta desktop">
          Enter workspace
          <span className="mk-arrow" aria-hidden>
            &rarr;
          </span>
        </Link>
        <button
          className="mk-burger"
          aria-label="Menu"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <span />
          <span />
          <span />
        </button>
      </nav>

      {/* ── hero ────────────────────────────────────────────────────────── */}
      <header className="mk-hero" id="home">
        <div className="mk-hero-inner">
          <div className="mk-hero-copy">
            <span className="mk-eyebrow">A fact &amp; rights engine</span>
            <h1>
              Based on a true story<span className="mk-hero-accent">, without the lawsuit.</span>
            </h1>
            <p className="mk-hero-sub">
              TRUE STORY reads a screenplay, checks every factual claim about every real
              person against the live public record, and clears every name, brand, song and
              location that could trigger a suit, documented to the standard insurers require
              before a film can ship.
            </p>
            <div className="mk-hero-actions">
              <Link href="/workspace" className="mk-cta">
                Enter workspace
                <span className="mk-arrow" aria-hidden>
                  &rarr;
                </span>
              </Link>
              <a href="#engine" className="mk-cta ghost">
                See how it works
              </a>
            </div>
            <p className="mk-hero-note">
              Runs offline with no credentials and no spend. Decision support, not legal advice.
            </p>
          </div>

          {/* the product, as the hero image */}
          <div className="mk-proof" aria-hidden>
            <div className="mk-proof-bar">
              <span className="mk-proof-dot" />
              <span className="mk-proof-dot" />
              <span className="mk-proof-dot" />
              <span className="mk-proof-title">Verdict overlay</span>
            </div>
            <div className="mk-proof-paper">
              <div className="mk-proof-scene">INT. NEWSREEL BOOTH. BERLIN, 1936</div>
              <p className="mk-proof-line mk-proof-cue">NARRATOR</p>
              <p className="mk-proof-line mk-proof-dialogue">
                Owens took <span className="mk-mark-green">four world records</span> in a single
                afternoon, in a stadium <span className="mk-mark-red">Hitler had already left.</span>
              </p>
            </div>
            <div className="mk-proof-evidence">
              <span className="mk-proof-verdict">
                <span
                  style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--red)", display: "inline-block" }}
                />
                Contradicted
              </span>
              <p className="mk-proof-claim">
                &ldquo;Hitler left the stadium before Owens competed.&rdquo;
              </p>
              <p className="mk-proof-cite">
                <b>2 records &middot; 8 domains</b>
                <span>the record places him in the stadium during the events</span>
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* ── guarantee strip ─────────────────────────────────────────────── */}
      <div className="mk-strip">
        <div className="mk-strip-inner">
          <span className="mk-strip-item">
            <b>8</b> stage pipeline
          </span>
          <span className="mk-strip-item">
            <b>5</b> of Parallel&rsquo;s web APIs
          </span>
          <span className="mk-strip-item">
            <b>4</b> role workspaces
          </span>
          <span className="mk-strip-item">
            <b>0</b> verdicts without evidence
          </span>
        </div>
      </div>

      {/* ── about ───────────────────────────────────────────────────────── */}
      <section className="mk-section" id="about">
        <span className="mk-eyebrow">The problem</span>
        <div className="mk-about-grid">
          <div className="mk-about-head">
            <h2 className="mk-h2">
              The five most valuable words in television are also the five most dangerous.
            </h2>
            <div className="mk-pullbar">
              <p>Clearance is mandatory. No clearance, no E&amp;O policy. No policy, no distribution.</p>
            </div>
          </div>
          <div className="mk-about-body">
            <p>
              When a production tells a story about real people, <strong>every line of dialogue
              is a claim about someone&rsquo;s life.</strong> One wrong line has cost streamers
              nine-figure defamation claims and settlements days before trial. Each time, the
              problem was the same thing: a statement about a real person that nobody had checked
              against the record.
            </p>
            <p>
              The existing fix is a cottage industry of a few dozen expert researchers serving a
              global content machine. A feature clearance report costs <strong>one to three
              thousand dollars</strong> and takes <strong>three to seven business days</strong>,
              and every revised draft or one-off name change bills again.
            </p>
            <p>
              TRUE STORY does the structured research and produces the document, in minutes, for
              a couple of dollars. It decomposes and checks every claim, filters opinion out
              before it costs anything, and keeps watching after the report is filed. <span className="mk-em">It automates the research and the document, never the judgement.</span>
            </p>

            <div className="mk-facts">
              {FACTS.map((f) => (
                <div className="mk-fact" key={f.label}>
                  <span className="mk-fact-num">{f.n}</span>
                  <span>
                    <span className="mk-fact-label">{f.label}</span>
                    <span className="mk-fact-text">{f.text}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── the engine ──────────────────────────────────────────────────── */}
      <section className="mk-section mk-engine" id="engine">
        <div className="mk-engine-head">
          <span className="mk-eyebrow">The engine</span>
          <h2 className="mk-h2">Eight stages. Four of them think.</h2>
          <p className="mk-lede">
            A deterministic spine with a language model at exactly the four points that need
            judgement, and nowhere else. Stage order is fixed by the domain, concurrency is
            infrastructure, and termination is objective, because a legal product cannot have a
            model improvising control flow.
          </p>
        </div>

        <div className="mk-stages">
          {STAGES.map((s) => (
            <div className="mk-stage" key={s.i}>
              <span className="mk-stage-index">{s.i}</span>
              <span className="mk-stage-name">{s.name}</span>
              <span className={`mk-stage-kind ${s.llm ? "llm" : ""}`}>{s.kind}</span>
              <span className="mk-stage-desc">{s.desc}</span>
            </div>
          ))}
        </div>

        <div className="mk-cols">
          <div>
            <h3 className="mk-col-title">How a verdict earns its place</h3>
            <div className="mk-list">
              {GATES.map((g, idx) => (
                <div className="mk-list-item" key={g.h}>
                  <span className="mk-list-icon">
                    {[<IconSearch key="s" />, <IconFilm key="f" />, <IconCode key="c" />, <IconMail key="m" />][idx]}
                  </span>
                  <span>
                    <p className="mk-list-h">{g.h}</p>
                    <p className="mk-list-p">{g.p}</p>
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="mk-col-title">Built on Parallel and Gemini</h3>
            <p className="mk-lede" style={{ marginBottom: "var(--space-4)" }}>
              Five of Parallel&rsquo;s six web APIs, each doing a distinct job, every response
              carrying citations that map onto the evidence envelope almost one-to-one. Gemini on
              Vertex AI covers what Parallel does not reach, visibly and at a stated discount in
              confidence, and the whole pipeline runs on Google&rsquo;s Agent Development Kit.
            </p>
            <div className="mk-apis">
              {["Task", "Search", "FindAll", "Extract", "Monitor"].map((a) => (
                <span className="mk-api" key={a}>
                  {a}
                </span>
              ))}
            </div>

            <div className="mk-verdicts" style={{ marginTop: "var(--space-6)", gridTemplateColumns: "1fr 1fr" }}>
              {VERDICTS.map((v) => (
                <div className={`mk-verdict ${v.k}`} key={v.k}>
                  <p className="mk-verdict-name">{v.name}</p>
                  <p className="mk-verdict-desc">{v.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── contact ─────────────────────────────────────────────────────── */}
      <section className="mk-section mk-contact" id="contact">
        <div className="mk-contact-grid">
          <div>
            <span className="mk-eyebrow">Contact</span>
            <h2 className="mk-h2">Bring us a draft.</h2>
            <p className="mk-lede">
              Questions about the engine, the evaluation, or running it against a real script?
              Send a note and we&rsquo;ll get back to you.
            </p>
            <div className="mk-contact-detail">
              <a className="mk-contact-row" href={`mailto:${CONTACT_EMAIL}`}>
                <span className="mk-list-icon">
                  <IconMail />
                </span>
                <span>
                  <span className="mk-contact-k">Email</span>
                  <span className="mk-contact-v">{CONTACT_EMAIL}</span>
                </span>
              </a>
              <a className="mk-contact-row" href={REPO_URL} target="_blank" rel="noreferrer">
                <span className="mk-list-icon">
                  <IconCode />
                </span>
                <span>
                  <span className="mk-contact-k">Source</span>
                  <span className="mk-contact-v">github.com/dext1nctstudio/True-Story</span>
                </span>
              </a>
            </div>
          </div>

          <form
            className="mk-form"
            onSubmit={(e) => {
              e.preventDefault();
              window.location.href = mailto;
            }}
          >
            <div className="mk-form-row">
              <div className="mk-field">
                <label htmlFor="mk-email">Your email</label>
                <input id="mk-email" type="email" placeholder="you@studio.com" value={form.email} onChange={set("email")} />
              </div>
              <div className="mk-field">
                <label htmlFor="mk-name">Your name</label>
                <input id="mk-name" type="text" placeholder="Jane Producer" value={form.name} onChange={set("name")} />
              </div>
            </div>
            <div className="mk-field">
              <label htmlFor="mk-subject">Subject</label>
              <input id="mk-subject" type="text" placeholder="A clearance question" value={form.subject} onChange={set("subject")} />
            </div>
            <div className="mk-field">
              <label htmlFor="mk-message">Message</label>
              <textarea id="mk-message" placeholder="Tell us about the project…" value={form.message} onChange={set("message")} />
            </div>
            <button type="submit" className="mk-form-submit">
              Send message
            </button>
            <p className="mk-form-hint">Opens your mail client. Nothing is sent to a server.</p>
          </form>
        </div>
      </section>

      {/* ── footer ──────────────────────────────────────────────────────── */}
      <footer className="mk-footer">
        <div className="mk-footer-inner">
          <div className="mk-footer-brand">
            <Image src="/logo-light.png" alt="True Story" width={1580} height={553} />
            <p className="mk-footer-tag">
              A fact and rights engine for based-on-a-true-story productions. Decision support for
              a clearance attorney, not legal advice.
            </p>
          </div>
          <div className="mk-footer-col">
            <h4>Product</h4>
            <a href="#about">About</a>
            <a href="#engine">The Engine</a>
            <Link href="/workspace">Enter workspace</Link>
          </div>
          <div className="mk-footer-col">
            <h4>Contact</h4>
            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
            <a href={REPO_URL} target="_blank" rel="noreferrer">
              GitHub
            </a>
          </div>
        </div>
        <div className="mk-footer-bar">
          <span>&copy; 2026 dxtinct studio. All rights reserved.</span>
          <p className="mk-disclaimer">
            Every clearance report in this industry is reviewed by a qualified attorney before a
            policy is bound.
          </p>
        </div>
      </footer>
    </div>
  );
}
