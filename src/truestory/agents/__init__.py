"""The eight agents.

Four of them call a language model and four do not. That ratio is the design,
not an accident: the brief asks for a deterministic multi step agent and a
legal product cannot have a model improvising control flow.

    1  IngestAgent      LlmAgent        script text to typed spans
    2  ClaimExtractor   LlmAgent        spans to atomic factual claims
    3  LedgerAgent      deterministic   coreference and deduplication
    4  RiskRouter       deterministic   policy table lookup
    5  ResearchSwarm    ParallelAgent   bounded, metered fan out
    6  Adjudicator      LlmAgent        evidence to verdicts, forced calling
    7  RemedyLoop       LoopAgent       propose then verify, max three
    8  ReportAgent      deterministic   templated artifacts

Every prompt in the system lives in `prompts.py`, so the count of model
decision points is visible in one file and a fifth one cannot appear quietly.
"""

from truestory.agents.adjudicator import Adjudicator
from truestory.agents.claims import ClaimExtractor
from truestory.agents.ingest import IngestAgent
from truestory.agents.ledger import LedgerAgent
from truestory.agents.pipeline import (
    ProjectConfig,
    RunState,
    TrueStoryPipeline,
    build_adk_pipeline,
    run_pipeline,
)
from truestory.agents.remedy import RemedyLoop
from truestory.agents.report import ReportAgent, build_summary
from truestory.agents.router import RiskRouter, RoutingPlan
from truestory.agents.swarm import ResearchSwarm, SwarmResult

__all__ = [
    "Adjudicator",
    "ClaimExtractor",
    "IngestAgent",
    "LedgerAgent",
    "ProjectConfig",
    "RemedyLoop",
    "ReportAgent",
    "ResearchSwarm",
    "RiskRouter",
    "RoutingPlan",
    "RunState",
    "SwarmResult",
    "TrueStoryPipeline",
    "build_adk_pipeline",
    "build_summary",
    "run_pipeline",
]
