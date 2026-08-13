"""TRUE STORY.

A fact and rights engine for "based on a true story" productions, built on the
COVERAGE clearance pipeline.

The package is layered strictly downward. Nothing in an upper layer imports
from a lower one in the wrong direction:

    api / webhooks / cli        service tier, thin
      -> agents                 ADK orchestration, eight stages
        -> mcp                  domain tool boundary
          -> providers          ResearchProvider registry, vendor swappable
            -> models           frozen dataclasses, the contracts
              -> policy         routing table, rubric, jurisdictions

The one rule that matters: no verdict may exist without evidence. That is
enforced structurally in `models.evidence` and `agents.adjudicator`, not by
prompt instruction.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
