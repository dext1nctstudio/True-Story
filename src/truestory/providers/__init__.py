"""The swap layer.

Nothing above this package knows that Parallel exists. Agents call domain tools
over MCP, the tools call this registry, and the registry decides which vendor,
at which depth, under which budget, answers the question. That indirection is
what makes the vendor swappable and, more importantly for a legal product, what
makes every answer arrive in one envelope shape with citations attached.

Providers are imported lazily. In mock mode no live client is ever constructed,
so the pipeline runs with no credentials at all.
"""

from truestory.providers.base import (
    EnumerationProvider,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    ResearchProvider,
    ResearchRequest,
)
from truestory.providers.budget import BudgetExhausted, BudgetGovernor, Ledger
from truestory.providers.cached import (
    CacheBackend,
    CachedProvider,
    GcsCacheBackend,
    LocalCacheBackend,
)
from truestory.providers.mock import MockProvider
from truestory.providers.registry import ProviderRegistry, Selection

__all__ = [
    "BudgetExhausted",
    "BudgetGovernor",
    "CacheBackend",
    "CachedProvider",
    "EnumerationProvider",
    "GcsCacheBackend",
    "Ledger",
    "LocalCacheBackend",
    "MockProvider",
    "ProviderError",
    "ProviderRegistry",
    "ProviderUnavailable",
    "RateLimited",
    "ResearchProvider",
    "ResearchRequest",
    "Selection",
]


def load_parallel_providers() -> dict[str, ResearchProvider]:
    """Construct the live Parallel providers.

    Imported here rather than at module scope so that mock mode and CI never
    touch the vendor SDK or require a key to be present.
    """
    from truestory.providers.gemini_grounded import GeminiGroundedProvider
    from truestory.providers.parallel_extract import ParallelExtractProvider
    from truestory.providers.parallel_findall import ParallelFindAllProvider
    from truestory.providers.parallel_monitor import ParallelMonitorProvider
    from truestory.providers.parallel_search import ParallelSearchProvider
    from truestory.providers.parallel_task import ParallelTaskProvider

    return {
        "parallel_task": ParallelTaskProvider(),
        "parallel_search": ParallelSearchProvider(),
        "parallel_findall": ParallelFindAllProvider(),
        "parallel_extract": ParallelExtractProvider(),
        "parallel_monitor": ParallelMonitorProvider(),
        "gemini_grounded": GeminiGroundedProvider(),
    }
