"""One place where a model name becomes a call, so a bad name degrades.

Model identifiers are configuration, and configuration is the part of a system
that is wrong on the machine you did not test on. A preview model can be
unavailable in a region, retired on a published schedule, or spelled correctly
and simply not enabled for a project. Every one of those returns a 404 from the
first call of the run, and without this module that ends the run.

The pattern is the one `ProviderRegistry` already uses for research providers:
prefer the configured choice, degrade to something that works, and stamp the
fact that a degradation happened rather than hiding it.

**Only availability triggers a fallback.** A schema rejection, a safety block, a
quota error or a malformed request is a real defect and is raised, because
retrying it against a different model turns a loud bug into a quiet one. That
distinction is the whole reason this is a module rather than a try/except.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("truestory.model")

#: Tried in order when the configured model is unavailable. Newest stable
#: first, then the generation this project was built and measured against.
#: Every entry must be a model that has actually served this workload.
FALLBACK_CHAIN: tuple[str, ...] = (
    "gemini-3.7-flash",
    "gemini-2.5-flash",
)

#: Wording that means "this model is not available to you", as opposed to
#: "your request was wrong". Matched against the string form of the exception
#: because the SDK raises several unrelated types for the same condition.
_UNAVAILABLE_MARKERS = (
    "not found",
    "not_found",
    "404",
    "was not found",
    "does not exist",
    "is not supported",
    "not supported for",
    "unsupported model",
    "invalid model",
    "model not available",
    "permission denied on resource model",
)

#: Wording that must never trigger a fallback. Checked first, because some
#: quota and permission errors also contain the word "model".
_NEVER_FALLBACK = (
    "quota",
    "resource exhausted",
    "rate limit",
    "429",
    "safety",
    "blocked",
    "recitation",
    "invalid argument",
    "controlled generation",
    "credential",
    "unauthenticated",
)


def is_model_unavailable(exc: BaseException) -> bool:
    """Whether this failure means the model itself cannot be reached."""
    text = f"{type(exc).__name__}: {exc}".casefold()
    if any(marker in text for marker in _NEVER_FALLBACK):
        return False
    return any(marker in text for marker in _UNAVAILABLE_MARKERS)


def chain_for(model: str) -> list[str]:
    """The configured model, then the fallbacks that are not already it."""
    return [model, *(m for m in FALLBACK_CHAIN if m != model)]


#: Backoff before each retry of a quota rejection, in seconds. Vertex returns
#: 429 RESOURCE_EXHAUSTED under burst load, and the swarm bursts by design: a
#: live run drove the attribution gate hard enough to lose several calls and
#: both remedy proposals to 429 while the account was nowhere near its quota.
#: Losing a remedy to a transient quota rejection is losing the fix the product
#: exists to offer, so it is worth waiting for.
_QUOTA_BACKOFF = (2.0, 6.0, 15.0)

_QUOTA_MARKERS = ("429", "resource exhausted", "resource_exhausted", "quota")


def is_quota_rejection(exc: BaseException) -> bool:
    """Whether this failure is a transient quota rejection worth waiting out."""
    text = f"{type(exc).__name__}: {exc}".casefold()
    return any(marker in text for marker in _QUOTA_MARKERS)


async def generate(client: Any, model: str, **kwargs: Any) -> Any:
    """`client.aio.models.generate_content`, with quota backoff and availability fallback.

    Every argument other than `model` is passed through untouched, so a call
    site reads the same as it did before and the request is not reshaped on the
    way through.

    The two failure modes are handled differently on purpose. A quota rejection
    is the same model saying "not right now", so it waits and asks again. An
    unavailable model is the wrong name, so waiting cannot help and it moves
    down the chain.
    """
    last: BaseException | None = None
    candidates = chain_for(model)

    for index, candidate in enumerate(candidates):
        try:
            response = await _with_quota_backoff(client, candidate, **kwargs)
        except Exception as exc:
            if not is_model_unavailable(exc):
                raise
            last = exc
            remaining = candidates[index + 1 :]
            if remaining:
                log.warning(
                    "model %r is unavailable (%s); falling back to %r",
                    candidate,
                    str(exc)[:160],
                    remaining[0],
                )
            continue

        if index:
            # Said once per call rather than once per run, because a run that
            # silently used a different model than the one on the report is
            # exactly the kind of thing this project refuses to do quietly.
            log.warning("model %r served this call after %r was unavailable", candidate, model)
        return response

    raise RuntimeError(
        f"no usable model: tried {', '.join(candidates)}. Last error: {last}"
    ) from last


async def _with_quota_backoff(client: Any, model: str, **kwargs: Any) -> Any:
    """One model, retried while it is rejecting on quota rather than on merit.

    Raises the quota error once the backoff is spent, so the caller sees the
    real reason instead of a model that mysteriously produced nothing. It is
    deliberately not routed into the fallback chain: a different model does not
    fix a project quota, and quietly answering a legal question with a weaker
    model because a stronger one was briefly busy is the wrong trade.
    """
    attempt = 0
    while True:
        try:
            return await client.aio.models.generate_content(model=model, **kwargs)
        except Exception as exc:
            if not is_quota_rejection(exc) or attempt >= len(_QUOTA_BACKOFF):
                raise
            delay = _QUOTA_BACKOFF[attempt]
            attempt += 1
            log.warning(
                "model %r rejected on quota, retrying in %.0fs (attempt %d of %d)",
                model,
                delay,
                attempt,
                len(_QUOTA_BACKOFF),
            )
            await asyncio.sleep(delay)
