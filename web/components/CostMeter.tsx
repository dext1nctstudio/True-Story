"use client";

/**
 * The live cost meter.
 *
 * It ticks in cents as the swarm completes, which is the demo's best recurring
 * visual: the audience watches two hundred research subjects resolve against
 * the live public record while the number climbs to a couple of dollars, set
 * against a manual report priced in the low thousands and delivered in days.
 *
 * The number is real. Every Evidence record carries its own cost, provider and
 * cache status, so this is the same data the report and the BigQuery unit
 * economics read from, not a display estimate.
 */

import { formatPercent, formatUsd } from "@/lib/api";
import type { BudgetSnapshot } from "@/lib/types";

interface Props {
  budget: BudgetSnapshot | null;
  visible: boolean;
}

export function CostMeter({ budget, visible }: Props) {
  // Cost is visible to counsel and producers. A writer does not need to see
  // the production's research spend to fix their own line.
  if (!visible || !budget) return null;

  const utilisation = Math.min(1, budget.utilisation);
  const state = utilisation >= 1 ? "over" : utilisation >= 0.8 ? "warn" : "";

  return (
    <div className="cost-meter" title={tooltip(budget)}>
      <div className="cost-row">
        <span className="cost-value">{formatUsd(budget.spent_usd)}</span>
        <span className="counter-label">
          of {formatUsd(budget.ceiling_usd)}
        </span>
      </div>

      <div className="cost-bar">
        <div className={`cost-fill ${state}`} style={{ width: `${utilisation * 100}%` }} />
      </div>

      <div className="cost-row">
        <span className="counter-label">
          {budget.calls} lookups
          {budget.cache_hits > 0 && `, ${formatPercent(budget.cache_hit_rate)} cached`}
        </span>
        {budget.degradations > 0 && (
          <span className="counter-label" style={{ color: "var(--verdict-amber)" }}>
            {budget.degradations} degraded
          </span>
        )}
      </div>
    </div>
  );
}

function tooltip(budget: BudgetSnapshot): string {
  const lines = [
    `Spent ${formatUsd(budget.spent_usd)} of a ${formatUsd(budget.ceiling_usd)} ceiling`,
    `${budget.calls} lookups, ${budget.cache_hits} served from cache`,
  ];
  if (budget.degradations > 0) {
    // Depth degrades before a run fails, and critical work never degrades at
    // all because it draws on a reserve nothing else can reach.
    lines.push(
      `${budget.degradations} subjects researched at reduced depth to stay inside budget`,
    );
  }
  lines.push(...budget.warnings);
  return lines.join("\n");
}

/**
 * Header counters. These are the numbers on screen during the demo, and each
 * verdict count doubles as a filter: click "4 verified" to dim every other
 * line in the script pane down to just the green ones, click again to clear.
 * Counsel has no colour of its own in the overlay, so it stays informational.
 */
export function VerdictCounters({
  green,
  amber,
  red,
  grey,
  counsel,
  pending = 0,
  activeFilter = null,
  onFilter,
}: {
  green: number;
  amber: number;
  red: number;
  grey: number;
  counsel: number;
  /** Claims extracted but not yet adjudicated. Only meaningful mid run. */
  pending?: number;
  activeFilter?: string | null;
  onFilter?: (color: string | null) => void;
}) {
  const toggle = (color: string) => onFilter?.(activeFilter === color ? null : color);

  return (
    <div className="counters">
      {pending > 0 && <Counter value={pending} label="researching" />}
      <Counter
        value={green}
        label="verified"
        tone="green"
        active={activeFilter === "green"}
        onClick={onFilter && green > 0 ? () => toggle("green") : undefined}
      />
      <Counter
        value={amber}
        label="unsupported"
        tone="amber"
        active={activeFilter === "amber"}
        onClick={onFilter && amber > 0 ? () => toggle("amber") : undefined}
      />
      <Counter
        value={red}
        label="contradicted"
        tone="red"
        active={activeFilter === "red"}
        onClick={onFilter && red > 0 ? () => toggle("red") : undefined}
      />
      <Counter
        value={grey}
        label="opinion"
        active={activeFilter === "grey"}
        onClick={onFilter && grey > 0 ? () => toggle("grey") : undefined}
      />
      <Counter value={counsel} label="counsel" />
    </div>
  );
}

function Counter({
  value,
  label,
  tone = "",
  active = false,
  onClick,
}: {
  value: number;
  label: string;
  tone?: string;
  active?: boolean;
  onClick?: () => void;
}) {
  const className = `counter ${tone} ${active ? "active" : ""} ${onClick ? "clickable" : ""}`.trim();
  const title = active
    ? `Showing only ${label} lines. Click to clear.`
    : `Show only ${label} lines`;

  if (!onClick) {
    return (
      <div className={className}>
        <span className="counter-value">{value}</span>
        <span className="counter-label">{label}</span>
      </div>
    );
  }

  return (
    <button className={className} onClick={onClick} title={title}>
      <span className="counter-value">{value}</span>
      <span className="counter-label">{label}</span>
    </button>
  );
}
