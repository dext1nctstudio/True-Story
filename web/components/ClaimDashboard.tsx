"use client";

/**
 * The per person view.
 *
 * Two things at once: the actual claims the draft makes about each named
 * person, and the amber density meter across them.
 *
 * The meter is the Fairstein rule made visible. That case did not turn on one
 * provably false sentence. It turned on a set of scenes attributing specific
 * conduct to a named living person that the record could not support. Amber is
 * not "probably fine" — it is the category that settles, so density is counted
 * per person rather than only flagging individual lines. But density is a
 * summary of the claims, so the claims themselves lead and the meter supports
 * them, not the other way round.
 */

import { useState } from "react";
import type { Claim, PersonRollup } from "@/lib/types";

interface Props {
  persons: PersonRollup[];
  onSelectPerson?: (person: PersonRollup) => void;
}

export function ClaimDashboard({ persons }: Props) {
  if (persons.length === 0) {
    return (
      <div className="empty">
        No real people carrying factual claims were found in this draft.
      </div>
    );
  }

  return (
    <div className="person-list">
      {persons.map((person) => (
        <PersonCard key={person.element_id} person={person} />
      ))}
    </div>
  );
}

function PersonCard({ person }: { person: PersonRollup }) {
  const [open, setOpen] = useState(true);
  const threshold = person.amber_threshold ?? 0.3;
  const over = person.exceeds_amber_threshold ?? person.amber_density > threshold;
  const researched = person.total_claims - person.opinion;
  const claims = person.claims ?? [];

  return (
    <section className="person-card">
      <header className="person-card-head">
        <div className="person-name">
          <span>
            {person.person_name}
            {person.alive === true && <span className="person-tag">living</span>}
            {person.public_figure_status === "private" && (
              <span className="person-tag private">private</span>
            )}
          </span>
          {over && <span className="counsel-flag">counsel</span>}
        </div>

        <div className="person-tallies">
          {person.verified > 0 && (
            <span className="tally green">{person.verified} verified</span>
          )}
          {person.amber_count > 0 && (
            <span className="tally amber">{person.amber_count} unsupported</span>
          )}
          {person.contradicted > 0 && (
            <span className="tally red">{person.contradicted} contradicted</span>
          )}
          {person.opinion > 0 && <span className="tally">{person.opinion} opinion</span>}
        </div>

        {/* The meter only earns its space once something is actually
            unsupported. At zero density it is a bar of empty track. */}
        {person.amber_count > 0 && (
          <>
            <div className="density-track" title={`${Math.round(threshold * 100)}% threshold`}>
              <div
                className={`density-fill ${over ? "over" : ""}`}
                style={{ width: `${Math.min(100, person.amber_density * 100)}%` }}
              />
              <div className="density-threshold" style={{ left: `${threshold * 100}%` }} />
            </div>
            <p className="person-meta">
              {person.amber_count} of {researched} researched claims unsupported ·{" "}
              {Math.round(person.amber_density * 100)}% density
            </p>
          </>
        )}
      </header>

      {claims.length > 0 && (
        <>
          <button className="person-toggle" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide" : "Show"} {claims.length}{" "}
            {claims.length === 1 ? "claim" : "claims"}
          </button>
          {open && (
            <ul className="person-claims">
              {claims.map((claim, index) => (
                <ClaimRow key={`${claim.claim_id}:${index}`} claim={claim} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  const color = claim.color ?? "grey";
  return (
    <li className={`person-claim ${color}`}>
      <div className="person-claim-head">
        <span className={`verdict-pill ${color}`}>{claim.verdict}</span>
        {claim.citation_count > 0 && (
          <span className="person-claim-sources">
            {claim.citation_count} {claim.citation_count === 1 ? "source" : "sources"}
          </span>
        )}
        {claim.needs_counsel && <span className="counsel-flag">counsel</span>}
      </div>
      <p className="person-claim-text">{claim.claim_text}</p>
      {claim.rationale && <p className="person-claim-why">{claim.rationale}</p>}
    </li>
  );
}
