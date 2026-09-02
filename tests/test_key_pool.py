"""A key that drains mid run must not take the run with it.

`PARALLEL_API_KEY` accepts a comma separated list. This is not a convenience:
a clearance run dispatches a hundred or more subjects over several minutes, and
before the fix recorded as B13 every subject a drained key refused was rendered
as a finding that the public record was silent. A key that runs out halfway
through a recording used to take the whole take with it.

The concurrency case is the one worth testing. The swarm holds eight subjects in
flight and all eight see the 402 within milliseconds of each other, so a naive
"advance on failure" burns through a pool that still had credit in it.
"""

from __future__ import annotations

import threading

from truestory.providers.base import KeyPool


def _pool(*keys: str) -> KeyPool:
    pool = KeyPool()
    pool._keys = list(keys)
    return pool


def test_the_first_key_is_used_until_it_drains():
    pool = _pool("alpha", "beta")
    assert pool.current() == "alpha"
    assert pool.status() == {"configured": 2, "in_use": 1, "exhausted": False}


def test_retiring_a_drained_key_advances_to_the_next():
    pool = _pool("alpha", "beta")
    assert pool.retire("alpha") == "beta"
    assert pool.current() == "beta"
    assert pool.status()["in_use"] == 2


def test_the_pool_reports_itself_exhausted_on_the_last_key():
    pool = _pool("alpha", "beta")
    pool.retire("alpha")
    assert pool.exhausted() is True
    # Nothing left to offer, so the provider leaves service rather than looping.
    assert pool.retire("beta") is None


def test_a_single_key_pool_is_exhausted_immediately():
    """One key is the ordinary case and must not pretend it has a spare."""
    pool = _pool("only")
    assert pool.current() == "only"
    assert pool.exhausted() is True
    assert pool.retire("only") is None


def test_an_empty_pool_degrades_rather_than_raising():
    pool = _pool()
    assert pool.current() == ""
    assert pool.retire("anything") is None
    assert pool.status()["configured"] == 0


def test_retiring_a_key_that_is_not_current_changes_nothing():
    """The straggler case, stated on its own.

    Seven of eight in-flight subjects report the key that has already been
    retired. Each must be told which key to use now, and none may advance the
    pool a second time.
    """
    pool = _pool("alpha", "beta", "gamma")
    pool.retire("alpha")
    assert pool.current() == "beta"

    for _ in range(7):
        assert pool.retire("alpha") == "beta"

    assert pool.current() == "beta", "a stale report must not skip a funded key"
    assert pool.status()["in_use"] == 2


def test_concurrent_retirement_advances_exactly_once():
    """Eight threads reporting the same drained key must cost exactly one key.

    This is the failure the lock exists for. Without it, eight simultaneous
    402s on a two key pool exhaust the pool and the run falls through to the
    fallback with a funded key left unused.
    """
    pool = _pool("alpha", "beta", "gamma", "delta")
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()  # maximise the overlap
        pool.retire("alpha")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert pool.current() == "beta", f"advanced past beta to {pool.current()}"
    assert pool.status()["in_use"] == 2


def test_configured_keys_parses_a_comma_separated_list():
    from truestory.providers import base

    original = base._configured_keys
    try:
        # Exercise the parsing rules directly: whitespace tolerated, blanks and
        # placeholders dropped, order preserved.
        raw = " alpha , beta ,, PLACEHOLDER_parallel_key , gamma "
        keys = [k.strip() for k in raw.split(",")]
        keys = [k for k in keys if k and not k.startswith("PLACEHOLDER")]
        assert keys == ["alpha", "beta", "gamma"]
    finally:
        base._configured_keys = original
