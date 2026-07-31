"""A8-5 — each ablation arm behaves the way the study reports it does.

**The five arm tests require live PostgreSQL.** Row locks, `SET TRANSACTION ISOLATION LEVEL
SERIALIZABLE` and the `UPDATE ... WHERE version = :expected` guard are database behaviour; a mocked
session exercises none of them, which is the same reason `test_worksheet_close_concurrency.py`
exists. The three oracle tests at the bottom are pure and always run — see `requires_db`.

Point the arm tests at a **scratch** database — they seed and delete rows:

    ACRA_BENCH_IT_DSN=postgresql+asyncpg://postgres:postgres@localhost:5441/acra_bench \\
        pytest tests/integration/test_concurrency_bench_arms.py

A benchmark whose arms are not independently verified is a table of numbers with no claim attached.
Each test below pins the one property the writeup will assert about that arm — and the unguarded
test is the negative control: if it ever comes back clean, every other row in the study is
meaningless, so it is asserted rather than observed.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.benchmark import Outcome


def _load_bench_module():
    """Import the runner from the repo-root `scripts/` tree, which is not on the backend path.

    tests/integration/<this file> -> tests -> backend -> repo root.
    """
    path = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "concurrency_bench.py"
    spec = importlib.util.spec_from_file_location("acra_concurrency_bench", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_bench = _load_bench_module()
AttemptResult = _bench.AttemptResult
_apply_correctness_oracle = _bench._apply_correctness_oracle
_on_hand = _bench._on_hand
_run_attempt = _bench._run_attempt
_seed = _bench._seed
_teardown = _bench._teardown

BENCH_IT_DSN = os.getenv("ACRA_BENCH_IT_DSN")

#: Applied per-test rather than as a module-level `pytestmark`, so the pure oracle tests at the
#: bottom still run in CI. Blanket-skipping the module would take them dark along with the live-DB
#: ones — the same trap that currently pins the seed module's coverage at 40%.
requires_db = pytest.mark.skipif(
    not BENCH_IT_DSN,
    reason="Set ACRA_BENCH_IT_DSN to a scratch database (never your dev DB) to run the A8-5 "
    "ablation-arm tests — they seed and delete rows.",
)

CLOSERS = 8
STOCK = 1_000_000
DRAW = 1_000


@pytest.fixture
async def sessionmaker_():
    engine = create_async_engine(BENCH_IT_DSN, pool_size=CLOSERS + 4, max_overflow=4)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


ROUNDS = 3


async def _run_arm(sessionmaker_, arm: str, closers: int = CLOSERS):
    """One round of `closers` concurrent attempts, returning (results, final_on_hand, lost)."""
    scenario = await _seed(sessionmaker_, stock=STOCK, worksheets=closers, planned=DRAW)
    try:
        barrier = asyncio.Barrier(closers)
        results = await asyncio.wait_for(
            asyncio.gather(
                *[
                    _run_attempt(sessionmaker_, arm, scenario, i, DRAW, barrier)
                    for i in range(closers)
                ]
            ),
            timeout=120,
        )
        final = await _on_hand(sessionmaker_, scenario)
        lost = _apply_correctness_oracle(results, final_on_hand=final, stock=STOCK, draw=DRAW)
        return results, final, lost
    finally:
        await _teardown(sessionmaker_, scenario)


async def _run_arm_rounds(sessionmaker_, arm: str, rounds: int = ROUNDS):
    """`rounds` independent rounds, with every attempt pooled into one list.

    The barrier guarantees the closers *start* together; it cannot guarantee they *overlap*. On a
    loaded machine the first closer can finish its whole transaction before the second issues its
    SELECT, and a single round then observes no contention at all — which silently turns an
    assertion about contention into an assertion about nothing. Pooling rounds makes the collision
    reliable without weakening any claim, and mirrors how the benchmark itself samples.
    """
    pooled = []
    total_lost = 0
    for _ in range(rounds):
        results, _, lost = await _run_arm(sessionmaker_, arm)
        pooled += results
        total_lost += lost
    return pooled, total_lost


# ---------------------------------------------------------------------------
# 1 — NEGATIVE CONTROL


@requires_db
async def test_unguarded_arm_loses_updates(sessionmaker_):
    """The control. An unguarded read-modify-write under contention must corrupt the books.

    Asserted, not observed: a clean result here would mean the harness never actually raced the
    closers, and every other arm's zero would be meaningless by association.
    """
    results, lost = await _run_arm_rounds(sessionmaker_, "unguarded")

    assert lost > 0, (
        f"the unguarded arm must lose updates under {CLOSERS}-way contention over {ROUNDS} rounds. "
        "If this is clean the closers are not overlapping and the whole study is asleep."
    )
    assert any(r.outcome is Outcome.LOST_UPDATE for r in results), (
        "lost updates must be visible in the arm's own outcomes, not only in the oracle"
    )


# ---------------------------------------------------------------------------
# 2 — the shipping implementation


@requires_db
async def test_optimistic_arm_is_correct_and_loses_nothing(sessionmaker_):
    """ADR-02's protocol, exercised through the real `close_worksheet`.

    Every closer holds its own worksheet over shared lots, so with abundant stock all of them
    should win — and the books must agree exactly.
    """
    results, final, lost = await _run_arm(sessionmaker_, "optimistic")

    assert lost == 0
    assert all(r.outcome is Outcome.OK for r in results), [r.outcome for r in results]
    assert final == STOCK - CLOSERS * DRAW, "on-hand must match exactly what won"


# ---------------------------------------------------------------------------
# 3 — the approach ADR-02 rejected


@requires_db
async def test_serializable_arm_is_correct_but_aborts_losers(sessionmaker_):
    """Correct *and* hostile — which is precisely ADR-02's stated reason for rejecting it.

    Aborts must surface as SQLSTATE 40001 rather than as a generic error: the whole retry argument
    depends on the caller being able to tell a retryable abort from a bug.
    """
    results, lost = await _run_arm_rounds(sessionmaker_, "serializable")

    assert lost == 0, "SERIALIZABLE must not corrupt the books"
    assert any(r.outcome is Outcome.SERIALIZATION_FAILURE for r in results), (
        f"expected 40001 aborts over {ROUNDS} rounds, got {[r.outcome for r in results]}"
    )
    assert not any(r.outcome is Outcome.ERROR for r in results), (
        "a serialization abort must be classified as retryable, not as a generic error — "
        "if this fires, _is_serialization_failure stopped recognising the SQLSTATE"
    )


@requires_db
async def test_serializable_retry_arm_actually_retries(sessionmaker_):
    """The retry loop must be shown to have run, not to have won on lucky timing.

    Without the retry-counter assertion this test passes on a machine where the closers happen not
    to collide, which would silently turn ADR-02's central claim into an untested one.
    """
    results, lost = await _run_arm_rounds(sessionmaker_, "serializable-retry")

    assert lost == 0
    assert sum(r.retries for r in results) > 0, (
        "no attempt retried — the arm cannot be said to have measured the retry loop"
    )
    succeeded = sum(1 for r in results if r.outcome is Outcome.OK)
    assert succeeded > 0


@requires_db
async def test_retry_arm_beats_naked_serializable_on_success_rate(sessionmaker_):
    """The comparison the writeup rests on: retrying converts aborts into completed work."""
    naked, _ = await _run_arm_rounds(sessionmaker_, "serializable")
    retried, _ = await _run_arm_rounds(sessionmaker_, "serializable-retry")

    naked_ok = sum(1 for r in naked if r.outcome is Outcome.OK)
    retried_ok = sum(1 for r in retried if r.outcome is Outcome.OK)
    assert retried_ok > naked_ok, (
        f"bounded retry should complete more work than bare SERIALIZABLE "
        f"({retried_ok} vs {naked_ok} of {ROUNDS * CLOSERS} attempts)"
    )


# ---------------------------------------------------------------------------
# 4 — the oracle itself


def test_oracle_relabels_exactly_the_updates_that_vanished():
    """Pure logic, so it runs without a database and pins the arithmetic the study depends on.

    Three closers each believe they drew 1000 from 10000, but only 1000 left the books: two
    updates were lost, so exactly two OK samples must be relabelled.
    """
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(3)]

    lost = _apply_correctness_oracle(results, final_on_hand=9000, stock=10_000, draw=1_000)

    assert lost == 2
    assert sum(1 for r in results if r.outcome is Outcome.LOST_UPDATE) == 2
    assert sum(1 for r in results if r.outcome is Outcome.OK) == 1


def test_oracle_is_silent_when_the_books_agree():
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(3)]

    assert _apply_correctness_oracle(results, final_on_hand=7000, stock=10_000, draw=1_000) == 0
    assert all(r.outcome is Outcome.OK for r in results)


def test_oracle_ignores_non_successes():
    """A closer that was correctly refused did not lose an update — it never had one."""
    results = [AttemptResult(Outcome.OK, 0.01), AttemptResult(Outcome.CONFLICT, 0.01)]

    assert _apply_correctness_oracle(results, final_on_hand=9000, stock=10_000, draw=1_000) == 0
