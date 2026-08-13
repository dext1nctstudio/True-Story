"use client";

/**
 * The per person view, and the amber density meter.
 *
 * This is the Fairstein rule made visible. That case did not turn on one
 * provably false sentence. It turned on a set of scenes attributing specific
 * conduct to a named living person that the record could not support.
 *
 * Amber is not "probably fine". Amber is the category that settles: not
 * provably false, and therefore not defensible either. So the product counts
 * unsupported claims per named living person and escalates the person once the
 * density crosses the rubric threshold, rather than only ever flagging
 * individual lines.
 */

import type { PersonRollup } from "@/lib/types";

interface Props {
  persons: PersonRollup[];
  onSelectPerson?: (person: PersonRollup) => void;
}

export function ClaimDashboard({ persons, onSelectPerson }: Props) {
  if (persons.length === 0) {
    return (
      <div className="empty">
        No real people carrying factual claims were found in this draft.
      </div>
    );
  }

  return (
    <div className="panel">
      <p className="panel-title">claims by person</p>

      {persons.map((person) => (
        <PersonRow key={person.element_id} person={person} onSelect={onSelectPerson} />
      ))}

      <p style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 12, lineHeight: 1.45 }}>
        Density counts claims the record can neither support nor contradict.
        A high proportion about a named living person is a finding in itself,
        independent of whether any single line is provably false.
      </p>
    </div>
  );
}

function PersonRow({
  person,
  onSelect,
}: {
  person: PersonRollup;
  onSelect?: (person: PersonRollup) => void;
}) {
  const threshold = person.amber_threshold ?? 0.3;
  const over = person.exceeds_amber_threshold ?? person.amber_density > threshold;
  const researched = person.total_claims - person.opinion;

  return (
    <div
      className="person-row"
      onClick={() => onSelect?.(person)}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      style={{ cursor: onSelect ? "pointer" : "default" }}
    >
      <div className="person-name">
        <span>
          {person.person_name}
          {person.alive === true && (
            <span style={{ color: "var(--text-faint)", fontWeight: 400 }}> · living</span>
          )}
          {person.public_figure_status === "private" && (
            <span style={{ color: "var(--verdict-amber)", fontWeight: 400 }}> · private</span>
          )}
        </span>
        {over && <span className="counsel-flag">counsel</span>}
      </div>

      <div className="density-track">
        <div
          className={`density-fill ${over ? "over" : ""}`}
          style={{ width: `${Math.min(100, person.amber_density * 100)}%` }}
        />
        {/* The threshold marker. Seeing the bar cross it is the whole point. */}
        <div className="density-threshold" style={{ left: `${threshold * 100}%` }} />
      </div>

      <div className="person-meta">
        {person.amber_count} of {researched} researched claims unsupported
        {" · "}
        {Math.round(person.amber_density * 100)}% density
        {person.contradicted > 0 && (
          <span style={{ color: "var(--verdict-red)", fontWeight: 600 }}>
            {" · "}
            {person.contradicted} contradicted
          </span>
        )}
      </div>

      <div className="person-meta" style={{ marginTop: 3 }}>
        <span style={{ color: "var(--verdict-green)" }}>{person.verified} verified</span>
        {" · "}
        <span style={{ color: "var(--verdict-amber)" }}>{person.amber_count} unsupported</span>
        {" · "}
        <span>{person.opinion} opinion, not researched</span>
      </div>
    </div>
  );
}
