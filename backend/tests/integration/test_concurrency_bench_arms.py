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
_comparison_lines = _bench._comparison_lines
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
#: Ceiling on the rounds an `until` escalation may spend before the caller's assertion is allowed
#: to fail. Generous, because the cost of exhausting it is one slow failure while the cost of it
#: being too small is a flaky suite.
MAX_ROUNDS = 12


async def _run_arm(sessionmaker_, arm: str, closers: int = CLOSERS):
    """One round of `closers` concurrent attempts → (results, final_on_hand, OracleVerdict)."""
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
        verdict = _apply_correctness_oracle(
            results, final_on_hand=final, stock=STOCK, draw=DRAW
        )
        return results, final, verdict
    finally:
        await _teardown(sessionmaker_, scenario)


async def _run_arm_rounds(
    sessionmaker_, arm: str, *, rounds: int = ROUNDS, until=None, max_rounds: int = MAX_ROUNDS
):
    """`rounds` independent rounds pooled into one list, extended until contention actually shows.

    The barrier guarantees the closers *start* together; it cannot guarantee they *overlap*. Under
    SERIALIZABLE the snapshot is taken at the first statement of the transaction, so a closer that
    issues its SELECT after an earlier closer has already committed reads a snapshot that already
    contains that write — and conflicts with nothing. On a fast local database a whole close costs
    about a millisecond, so a round can complete with every closer serialized and no contention
    observed at all, which silently turns an assertion about contention into an assertion about
    nothing. This is exactly how these tests flaked: green in isolation, three red under a full-suite
    run, with no code difference between the two.

    `until(pooled)` names the collision the caller's assertion depends on. Rounds are added until it
    is satisfied or `max_rounds` is spent — and when it is never satisfied the caller's own assertion
    fires with its own message, so a genuinely broken arm still fails. It buys reliability, not
    leniency: no assertion is weakened, the harness is just made to keep trying until the race it
    claims to measure has actually happened.
    """
    pooled: list = []
    #: Units, not updates. `lost_updates` floors the discrepancy by `draw`, so a drift smaller than a
    #: single close reports as 0 — and an arm asserting only `lost == 0` would pass over a ledger that
    #: is provably wrong. Summing units is the exactness check, and it subsumes the whole-update one.
    drift = 0
    total_over = 0
    limit = max(rounds, max_rounds) if until else rounds
    for completed in range(limit):
        results, _, verdict = await _run_arm(sessionmaker_, arm)
        pooled += results
        drift += verdict.lost_units
        total_over += verdict.overconsumed_units
        if until and completed + 1 >= rounds and until(pooled):
            break
    return pooled, drift, total_over


def _saw_lost_update(results) -> bool:
    return any(r.outcome is Outcome.LOST_UPDATE for r in results)


def _saw_abort(results) -> bool:
    return any(r.outcome is Outcome.SERIALIZATION_FAILURE for r in results)


# ---------------------------------------------------------------------------
# 1 — NEGATIVE CONTROL


@requires_db
async def test_unguarded_arm_loses_updates(sessionmaker_):
    """The control. An unguarded read-modify-write under contention must corrupt the books.

    Asserted, not observed: a clean result here would mean the harness never actually raced the
    closers, and every other arm's zero would be meaningless by association.
    """
    results, drift, _ = await _run_arm_rounds(sessionmaker_, "unguarded", until=_saw_lost_update)

    assert drift > 0, (
        f"the unguarded arm must lose stock under {CLOSERS}-way contention within {MAX_ROUNDS} "
        "rounds. If this is clean the closers are not overlapping and the whole study is asleep."
    )
    assert _saw_lost_update(results), (
        "lost updates must be visible in the arm's own outcomes, not only in the oracle"
    )


# ---------------------------------------------------------------------------
# 2 — the shipping implementation


@requires_db
async def test_optimistic_arm_is_correct_and_loses_nothing(sessionmaker_):
    """ADR-02's protocol, exercised through the real `close_worksheet`.

    Every closer holds its own worksheet over shared lots, so with abundant stock all of them should
    win and the books must agree exactly.

    **The unguarded arm is run first, in this same test, as a contention witness.** On its own,
    "optimistic lost nothing" is vacuous: if the closers never actually overlapped, there was no
    race to survive and the assertion passes while proving nothing. The optimistic arm emits no
    CONFLICT or SERIALIZATION_FAILURE either, so it has no outcome-based tell of its own. Running
    the unguarded arm against the identical scenario shape establishes that these conditions *do*
    produce collisions — and only then does the optimistic arm's clean sheet mean anything.

    The negative control in a different test function cannot do this job: it proves the mechanism
    can collide on *its* invocation, not on this one.
    """
    witness, witness_drift, _ = await _run_arm_rounds(
        sessionmaker_, "unguarded", until=_saw_lost_update
    )
    assert witness_drift > 0, (
        "contention witness failed: the unguarded arm lost nothing, so these conditions did not "
        "produce a race at all. The optimistic result below would be vacuous — fix the harness "
        f"rather than trusting it. Outcomes: {[r.outcome.value for r in witness]}"
    )

    results, drift, over = await _run_arm_rounds(sessionmaker_, "optimistic")

    # Counted in units rather than whole updates, so on-hand must land on exactly what the successes
    # claim — a drift of even one unit fails. `close_worksheet` draws FIFO across lots, and a
    # truncation in that loop is precisely a sub-`draw` discrepancy that a whole-update count floors
    # to zero and reports as clean.
    assert drift == 0, "on-hand must match exactly what won, to the unit"
    assert over == 0, "the books must not move further than the successes claim either"
    assert all(r.outcome is Outcome.OK for r in results), [r.outcome for r in results]


# ---------------------------------------------------------------------------
# 3 — the approach ADR-02 rejected


@requires_db
async def test_serializable_arm_is_correct_but_aborts_losers(sessionmaker_):
    """Correct *and* hostile — which is precisely ADR-02's stated reason for rejecting it.

    Aborts must surface as SQLSTATE 40001 rather than as a generic error: the whole retry argument
    depends on the caller being able to tell a retryable abort from a bug.
    """
    results, drift, over = await _run_arm_rounds(sessionmaker_, "serializable", until=_saw_abort)

    assert drift == 0, "SERIALIZABLE must not corrupt the books, to the unit"
    assert over == 0, "SERIALIZABLE must not over-consume either"
    assert _saw_abort(results), (
        f"expected 40001 aborts within {MAX_ROUNDS} rounds, got {[r.outcome for r in results]}"
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
    results, drift, _ = await _run_arm_rounds(
        sessionmaker_,
        "serializable-retry",
        until=lambda pooled: sum(r.retries for r in pooled) > 0,
    )

    assert drift == 0
    assert sum(r.retries for r in results) > 0, (
        f"no attempt retried in {MAX_ROUNDS} rounds — the arm cannot be said to have measured the "
        "retry loop"
    )
    succeeded = sum(1 for r in results if r.outcome is Outcome.OK)
    assert succeeded > 0


@requires_db
async def test_retry_arm_beats_naked_serializable_on_success_rate(sessionmaker_):
    """The comparison the writeup rests on: retrying converts aborts into completed work.

    Compared as *rates*, not counts: each arm escalates rounds independently until it has seen the
    contention it needs, so the two pools are not guaranteed to be the same size and comparing raw
    totals would let a difference in round count masquerade as a difference in behaviour.
    """
    naked, _, _ = await _run_arm_rounds(sessionmaker_, "serializable", until=_saw_abort)
    assert _saw_abort(naked), (
        "bare SERIALIZABLE never aborted, so there is no contention here for retrying to rescue — "
        "the comparison below would be vacuous"
    )
    retried, _, _ = await _run_arm_rounds(
        sessionmaker_,
        "serializable-retry",
        until=lambda pooled: sum(r.retries for r in pooled) > 0,
    )

    naked_rate = sum(1 for r in naked if r.outcome is Outcome.OK) / len(naked)
    retried_rate = sum(1 for r in retried if r.outcome is Outcome.OK) / len(retried)
    assert retried_rate > naked_rate, (
        f"bounded retry should complete a larger share of its attempts than bare SERIALIZABLE "
        f"({retried_rate:.0%} of {len(retried)} vs {naked_rate:.0%} of {len(naked)})"
    )


# ---------------------------------------------------------------------------
# 4 — the oracle itself


def test_oracle_relabels_exactly_the_updates_that_vanished():
    """Pure logic, so it runs without a database and pins the arithmetic the study depends on.

    Three closers each believe they drew 1000 from 10000, but only 1000 left the books: two
    updates were lost, so exactly two OK samples must be relabelled.
    """
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(3)]

    verdict = _apply_correctness_oracle(results, final_on_hand=9000, stock=10_000, draw=1_000)

    assert verdict.lost_updates == 2
    assert verdict.lost_units == 2_000
    assert verdict.overconsumed_units == 0
    assert sum(1 for r in results if r.outcome is Outcome.LOST_UPDATE) == 2
    assert sum(1 for r in results if r.outcome is Outcome.OK) == 1


def test_oracle_is_silent_when_the_books_agree():
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(3)]

    verdict = _apply_correctness_oracle(results, final_on_hand=7000, stock=10_000, draw=1_000)

    assert verdict == (0, 0, 0)
    assert all(r.outcome is Outcome.OK for r in results)


def test_oracle_ignores_non_successes():
    """A closer that was correctly refused did not lose an update — it never had one."""
    results = [AttemptResult(Outcome.OK, 0.01), AttemptResult(Outcome.CONFLICT, 0.01)]

    verdict = _apply_correctness_oracle(results, final_on_hand=9000, stock=10_000, draw=1_000)

    assert verdict == (0, 0, 0)


def test_oracle_reports_over_consumption():
    """The books moving *further* than the successes claim is corruption too.

    Two successes account for 2000 drawn from 10000, but 3000 actually left — an attempt decremented
    and then failed, or drew twice. An earlier version returned a bare 0 here, reporting a corrupt
    ledger as clean, because the discrepancy was negative and got floored away.
    """
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(2)]

    verdict = _apply_correctness_oracle(results, final_on_hand=7000, stock=10_000, draw=1_000)

    assert verdict.overconsumed_units == 1_000
    assert verdict.lost_updates == 0
    assert all(r.outcome is Outcome.OK for r in results), (
        "over-consumption is not a lost update — it must not be relabelled as one"
    )


def test_oracle_reports_a_partial_discrepancy_that_is_not_a_whole_update():
    """A discrepancy smaller than one draw still means the ledger is wrong.

    Reporting only whole updates would floor 1500 to 1 and silently drop the remaining 500, so the
    unit count is carried alongside the update count.
    """
    results = [AttemptResult(Outcome.OK, 0.01) for _ in range(3)]

    verdict = _apply_correctness_oracle(results, final_on_hand=8_500, stock=10_000, draw=1_000)

    assert verdict.lost_updates == 1
    assert verdict.lost_units == 1_500, "the 500-unit remainder must not vanish from the report"


def test_oracle_catches_a_discrepancy_smaller_than_a_single_draw():
    """The case a whole-update count cannot see at all.

    One success claims 1000 of 10000, and 9200 remains — 200 units short of the 9000 the ledger
    should show. `lost_updates` floors that to 0 and nothing is relabelled, so `lost_units` is the
    *only* surviving signal that the books are wrong. `close_worksheet` draws FIFO across lots, so a
    truncation in that loop lands exactly here.
    """
    results = [AttemptResult(Outcome.OK, 0.01)]

    verdict = _apply_correctness_oracle(results, final_on_hand=9_200, stock=10_000, draw=1_000)

    assert verdict.lost_updates == 0, "200 is less than one draw, so no whole update was lost"
    assert verdict.lost_units == 200, (
        "a sub-draw discrepancy is still a corrupt ledger — if this is 0, every caller asserting "
        "only on lost_updates is passing over books that do not balance"
    )
    assert all(r.outcome is Outcome.OK for r in results)


# ---------------------------------------------------------------------------
# 5 — the report the oracle feeds


def test_comparison_table_shows_a_sub_draw_discrepancy():
    """A wrong ledger must never render as a clean row.

    `lost` alone floors a sub-draw discrepancy to 0, so the table carries `lostu` beside it. Pure —
    `_comparison_lines` takes plain dicts — so this guards the reporting path without a database.
    """
    row = {
        "arm": "unguarded",
        "concurrency": 8,
        "lost_updates": 0,
        "lost_units": 200,
        "overconsumed_units": 0,
        "success_rate": 1.0,
        "retry_rate": 0.0,
        "p50_ms": 1.0,
        "p95_ms": 2.0,
        "goodput_ops_s": 100.0,
        "throughput_ops_s": 100.0,
    }

    body = _comparison_lines([row])[2]

    assert "200" in body, f"the 200 lost units must appear in the row, got: {body!r}"
