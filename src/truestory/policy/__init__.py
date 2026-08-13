"""Policy as data.

Three YAML files at the repository root hold every decision a clearance
attorney should be able to read, argue with, and change without touching
Python:

    policy/routing.yaml        which subject goes to which processor, and why
    policy/rubric.yaml         the deterministic post checks and fixed wording
    policy/jurisdictions.yaml  territory rules and post mortem publicity terms

This package compiles them, validates them, and exposes the matcher. The
routing table is the RiskRouter agent in its entirety. There is no model
anywhere in the routing path.
"""

from truestory.policy.loader import (
    Jurisdictions,
    PolicyError,
    RoutingDecision,
    RoutingPolicy,
    RoutingRule,
    Rubric,
    load_jurisdictions,
    load_routing,
    load_rubric,
    load_schema,
    reload_all,
)

__all__ = [
    "Jurisdictions",
    "PolicyError",
    "RoutingDecision",
    "RoutingPolicy",
    "RoutingRule",
    "Rubric",
    "load_jurisdictions",
    "load_routing",
    "load_rubric",
    "load_schema",
    "reload_all",
]
