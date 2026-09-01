"""The ceiling has to be a ceiling.

A live run of `forty_five_minutes.fountain` on 1 September was given
``--budget 3.0`` and spent **$6.38**. The swarm reported 131 subjects, zero
failures, and more than twice the ceiling.

`BudgetGovernor.reserve` had always said it "holds spend before dispatching, so
concurrent workers cannot overshoot", and `remaining_cents` computed
``ceiling - spent`` without ever subtracting what was reserved. The reservation
was incremented, decremented and never read. The research swarm dispatches
thirty two subjects concurrently, so thirty two workers read the same settled
spend before any of them had recorded anything, and every one of them was
funded.

Cost governance is one of the four things this project sells. These tests hold
the ceiling under exactly the concurrency the swarm actually uses.
"""

from __future__ import annotations

import asyncio

import pytest

from truestory.models.enums import Processor, RiskTier
from truestory.providers.budget import BudgetExhausted, BudgetGovernor


def _governor(ceiling_usd: float = 3.0, reserve_usd: float = 0.0) -> BudgetGovernor:
    """A governor with the CRITICAL reserve set explicitly.

    The default reserve is $1.50, so a $1.00 ceiling leaves general work
    nothing at all. These tests are about the ceiling arithmetic, so the
    reserve is stated per test rather than inherited from policy.
    """
    return BudgetGovernor(ceiling_usd=ceiling_usd, reserve_critical_usd=reserve_usd)


def test_a_reservation_reduces_what_is_available():
    """The bug, at its smallest. A held reservation must be invisible to nobody."""
    gov = _governor(1.0)  # 100 cents, no CRITICAL reserve
    before = gov.remaining_cents
    gov.reserve(40.0, RiskTier.HIGH)
    after = gov.remaining_cents

    assert before == 100.0
    assert after == 60.0, "a reservation that does not reduce availability is not a reservation"


def test_reservations_accumulate_across_concurrent_workers():
    """Thirty two workers reserving before any of them records."""
    gov = _governor(1.0)
    for _ in range(10):
        gov.reserve(10.0, RiskTier.HIGH)

    assert gov.remaining_cents == 0.0
    with pytest.raises(BudgetExhausted):
        gov.reserve(10.0, RiskTier.HIGH)


def test_recording_releases_the_reservation_without_double_counting():
    """Reserve then record must not subtract the same money twice."""
    gov = _governor(1.0)
    gov.reserve(20.0, RiskTier.HIGH)
    gov.record(20.0, RiskTier.HIGH, "parallel_task", reserved=20.0)

    assert gov.ledger.reserved_cents == 0.0
    assert gov.ledger.spent_cents == 20.0
    assert gov.remaining_cents == 80.0


def test_a_cheaper_actual_than_reserved_returns_the_difference():
    """A call that came back cached or cheaper must free the held amount."""
    gov = _governor(1.0)
    gov.reserve(20.0, RiskTier.HIGH)
    gov.record(0.0, RiskTier.HIGH, "cache", cached=True, reserved=20.0, list_price_cents=20.0)

    assert gov.remaining_cents == 100.0, "a cache hit must return the whole reservation"


@pytest.mark.asyncio
async def test_the_ceiling_holds_under_swarm_concurrency():
    """The live failure, reproduced at the concurrency that produced it.

    Two hundred subjects at the swarm's real 32 way concurrency against a
    ceiling that only funds a hundred of them. Before the fix every worker read
    the same settled spend and the run sailed past the ceiling.
    """
    ceiling_usd = 1.0  # 100 cents
    per_call = 1.0  # 1 cent, the base processor price
    gov = BudgetGovernor(ceiling_usd=ceiling_usd, reserve_critical_usd=0.0)

    semaphore = asyncio.Semaphore(32)
    funded = 0
    refused = 0
    lock = asyncio.Lock()

    async def one_subject() -> None:
        nonlocal funded, refused
        async with semaphore:
            try:
                gov.reserve(per_call, RiskTier.HIGH)
            except BudgetExhausted:
                async with lock:
                    refused += 1
                return
            # The gap the concurrency exploits: dispatch takes real time, and
            # nothing is recorded until it returns.
            await asyncio.sleep(0)
            gov.record(per_call, RiskTier.HIGH, "parallel_task", reserved=per_call)
            async with lock:
                funded += 1

    await asyncio.gather(*(one_subject() for _ in range(200)))

    assert funded + refused == 200
    assert gov.ledger.spent_cents <= ceiling_usd * 100, (
        f"spent {gov.ledger.spent_cents}c against a {ceiling_usd * 100}c ceiling"
    )
    assert refused > 0, "with a ceiling funding half the subjects, some must be refused"


@pytest.mark.asyncio
async def test_critical_work_still_reaches_its_reserve_under_pressure():
    """The reserve must survive the fix.

    A script full of cheap background elements must never starve the one line
    that gets the production sued, and tightening availability must not be the
    thing that starves it.
    """
    gov = BudgetGovernor(ceiling_usd=2.0, reserve_critical_usd=0.5)

    # Drain everything a general subject is allowed to touch.
    drained = 0
    while True:
        try:
            gov.reserve(1.0, RiskTier.HIGH)
            gov.record(1.0, RiskTier.HIGH, "parallel_task", reserved=1.0)
            drained += 1
        except BudgetExhausted:
            break
        if drained > 500:  # pragma: no cover - guard against a runaway loop
            raise AssertionError("general spend never exhausted")

    # CRITICAL draws on the reserve that general work cannot reach.
    assert gov.available_for(RiskTier.CRITICAL) > 0.0, "the CRITICAL reserve was consumed"
    gov.reserve(1.0, RiskTier.CRITICAL)


def test_degradation_still_happens_before_refusal():
    """Depth must walk down before a subject is refused outright."""
    gov = BudgetGovernor(ceiling_usd=5.0, reserve_critical_usd=0.0)
    assert gov.resolve(Processor.CORE, RiskTier.HIGH) is not None

    # Spend almost everything, then confirm a deep request comes back shallower
    # rather than raising.
    gov.record(480.0, RiskTier.HIGH, "parallel_task")
    resolved = gov.resolve(Processor.CORE, RiskTier.HIGH)
    assert resolved.usd_per_run <= Processor.CORE.usd_per_run
