"""
TC-02 — the RSK-01 proof: a production-worksheet close cannot lose or double-count stock.

**This module requires live PostgreSQL** (``DATABASE_URL``), like ``tests/test_schema.py``. Row
locks, transaction visibility and the ``UPDATE ... WHERE version = :expected`` guard are database
behaviour; a mocked session cannot exercise any of them. ``tests/integration/test_concurrency.py``
is mock-based and, by construction, could never have detected a lost update — that gap is the
reason this file exists.

Each concurrent closer gets its **own session**, and therefore its own connection. Sharing one
session would serialize the closers through a single connection and quietly delete the race.

Test 1 is the negative control and is deliberately written first: it drives an *unsafe*
read-modify-write close and asserts that it **does** lose an update. Without it, the green results
below would only prove that the harness is asleep.

**Mutation-verified.** A negative control on raw SQL is not enough — it says nothing about whether
these tests exercise the real service. Each guard was deleted from ``close_worksheet`` in turn and
the suite re-run:

===========================================  ==========================================
Guard removed from the service                Tests that turn red
===========================================  ==========================================
optimistic version guard (the ``WHERE``)      tests 2 and 3
both ``with_for_update()`` row locks          test 4 (oversell)
===========================================  ==========================================

Every guard the close relies on is covered by at least one test that fails without it. Re-run that
check before weakening any assertion here — an earlier draft of test 2 drew 6000 from a 10000 lot
and stayed green with the version guard deleted, because "insufficient stock" quietly stood in for
the guard. That is why ``ABUNDANT_STOCK`` exists.
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import WorksheetCloseLine, WorksheetCloseRequest
from app.services.production_worksheet_service import close_worksheet

PARALLEL_CLOSERS = 8
REPEAT_ROUNDS = 5
# Far more than the parallel closers could ever consume, so "insufficient stock" can never stand in
# for the version guard and make a broken guard look green. See test 2's docstring.
ABUNDANT_STOCK = 100_000

_USER = TokenUser(
    user_id=0,  # replaced per scenario with the real seeded id
    full_name="TC-02 Runner",
    roles=["company_admin"],
    preferred_language="en",
    effective_privileges=["production.worksheet.close"],
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def sessionmaker_():
    engine = create_async_engine(
        settings.database_url,
        # Room for PARALLEL_CLOSERS simultaneous connections plus the setup/assert session.
        pool_size=PARALLEL_CLOSERS + 4,
        max_overflow=4,
    )
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


class Scenario:
    """Ids of the rows one scenario owns, so teardown can remove exactly those."""

    def __init__(self, user_id: int, product_id: int):
        self.user_id = user_id
        self.product_id = product_id
        self.lot_ids: list[int] = []
        self.worksheet_ids: list[int] = []
        self.line_ids: list[int] = []

    def user(self) -> TokenUser:
        return _USER.model_copy(update={"user_id": self.user_id})


async def _seed(sessionmaker_, *, lot_quantities, worksheets, planned=6000) -> Scenario:
    """Create a user, a product, ``lot_quantities`` lots, and N single-line worksheets."""
    async with sessionmaker_() as db:
        user_id = await db.scalar(
            text(
                "INSERT INTO users (username, password_hash, full_name, preferred_language, status)"
                " VALUES (:u, 'x', 'TC-02 Runner', 'en', 'active') RETURNING id"
            ),
            {"u": f"tc02_{uuid.uuid4().hex[:12]}"},
        )
        product_id = await db.scalar(
            text(
                "INSERT INTO products (name, category) VALUES (:n, 'raw') RETURNING id"
            ),
            {"n": f"TC-02 Material {user_id}"},
        )
        scenario = Scenario(user_id, product_id)

        for i, qty in enumerate(lot_quantities):
            lot_id = await db.scalar(
                text(
                    "INSERT INTO inventory_lots"
                    " (product_id, lot_number, storage_location, status, quantity_on_hand)"
                    " VALUES (:p, :ln, 'TC-02', 'in_storage', :q) RETURNING id"
                ),
                {"p": product_id, "ln": f"TC02-{user_id}-{i}", "q": qty},
            )
            scenario.lot_ids.append(lot_id)

        for _ in range(worksheets):
            ws_id = await db.scalar(
                text(
                    "INSERT INTO production_worksheets"
                    " (production_line, scheduled_date, status, version, created_by)"
                    " VALUES ('TC-02', '2026-07-24', 'draft', 0, :u) RETURNING id"
                ),
                {"u": user_id},
            )
            line_id = await db.scalar(
                text(
                    "INSERT INTO production_worksheet_lines"
                    " (worksheet_id, product_id, planned_quantity)"
                    " VALUES (:w, :p, :q) RETURNING id"
                ),
                {"w": ws_id, "p": product_id, "q": planned},
            )
            scenario.worksheet_ids.append(ws_id)
            scenario.line_ids.append(line_id)

        await db.commit()
    return scenario


async def _teardown(sessionmaker_, scenario: Scenario) -> None:
    async with sessionmaker_() as db:
        await db.execute(
            text("DELETE FROM inventory_transactions WHERE lot_id = ANY(:ids)"),
            {"ids": scenario.lot_ids},
        )
        await db.execute(
            text(
                "DELETE FROM audit_logs WHERE entity_type = 'production_worksheet'"
                " AND entity_id = ANY(:ids)"
            ),
            {"ids": scenario.worksheet_ids},
        )
        await db.execute(
            text("DELETE FROM production_worksheet_lines WHERE worksheet_id = ANY(:ids)"),
            {"ids": scenario.worksheet_ids},
        )
        await db.execute(
            text("DELETE FROM production_worksheets WHERE id = ANY(:ids)"),
            {"ids": scenario.worksheet_ids},
        )
        await db.execute(
            text("DELETE FROM inventory_lots WHERE id = ANY(:ids)"), {"ids": scenario.lot_ids}
        )
        await db.execute(
            text("DELETE FROM products WHERE id = :id"), {"id": scenario.product_id}
        )
        await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": scenario.user_id})
        await db.commit()


async def _on_hand(sessionmaker_, scenario: Scenario) -> int:
    async with sessionmaker_() as db:
        return await db.scalar(
            text(
                "SELECT COALESCE(SUM(quantity_on_hand), 0) FROM inventory_lots"
                " WHERE id = ANY(:ids)"
            ),
            {"ids": scenario.lot_ids},
        )


async def _movements(sessionmaker_, scenario: Scenario) -> list[tuple[str, int]]:
    """Every movement written against this scenario's worksheets, as (type, quantity)."""
    async with sessionmaker_() as db:
        rows = await db.execute(
            text(
                "SELECT transaction_type, quantity FROM inventory_transactions"
                " WHERE reference_type = 'production_worksheet' AND reference_id = ANY(:ids)"
                " ORDER BY id"
            ),
            {"ids": scenario.worksheet_ids},
        )
        return [(r[0], r[1]) for r in rows.all()]


async def _run_close(sessionmaker_, scenario, ws_index, actual, barrier=None):
    """One closer on its own session/connection. Returns the HTTP status it would produce."""
    request = WorksheetCloseRequest(
        expected_version=0,
        lines=[WorksheetCloseLine(line_id=scenario.line_ids[ws_index], actual_quantity=actual)],
    )
    if barrier is not None:
        await barrier.wait()  # release every closer at the same instant
    async with sessionmaker_() as db:
        try:
            await close_worksheet(
                db, scenario.worksheet_ids[ws_index], request, scenario.user()
            )
            return 200
        except HTTPException as exc:
            return exc.status_code


# ---------------------------------------------------------------------------
# 1 — NEGATIVE CONTROL. Proves the harness can see a lost update.
# ---------------------------------------------------------------------------


async def test_negative_control_unsafe_close_loses_an_update(sessionmaker_):
    """An unguarded read-modify-write close double-consumes. If this ever passes cleanly, every
    other test in this file is worthless — so it is asserted, not commented.

    Both transactions are held genuinely **open and overlapping**: A reads, then B reads before A
    has written, and only then do they write. Interleaving them by hand rather than racing them
    makes the control deterministic — it fails the same way every run, instead of only when the
    scheduler happens to cooperate. That overlap is precisely the window ``SELECT ... FOR UPDATE``
    plus the version guard closes.
    """
    scenario = await _seed(sessionmaker_, lot_quantities=[10000], worksheets=2)
    draw = 6000
    try:
        lot_id = scenario.lot_ids[0]
        read_sql = text("SELECT quantity_on_hand FROM inventory_lots WHERE id = :id")
        write_sql = text("UPDATE inventory_lots SET quantity_on_hand = :q WHERE id = :id")

        # Two sessions, two connections, both transactions open at the same time. Nothing is
        # returned out of the `async with`, so neither transaction closes early.
        async with sessionmaker_() as db_a, sessionmaker_() as db_b:
            read_a = await db_a.scalar(read_sql, {"id": lot_id})
            read_b = await db_b.scalar(read_sql, {"id": lot_id})

            # No lock was taken, so B sees the pre-A value. This is the lost update forming.
            assert read_a == read_b == 10000

            await db_a.execute(write_sql, {"q": read_a - draw, "id": lot_id})
            await db_a.commit()

            # B still writes the total it computed from its stale read, erasing A's decrement.
            await db_b.execute(write_sql, {"q": read_b - draw, "id": lot_id})
            await db_b.commit()

        final = await _on_hand(sessionmaker_, scenario)
        intended = 2 * draw  # what the two closers together believed they consumed
        actual_decrement = 10000 - final

        assert actual_decrement == draw, (
            f"expected only one closer's {draw} to survive, saw {actual_decrement}"
        )
        assert actual_decrement < intended, (
            f"the unsafe path must lose an update: {intended} was consumed but only "
            f"{actual_decrement} left the books. If these are equal, the control is not proving "
            "what it claims and every other test in this file is unverified."
        )
    finally:
        await _teardown(sessionmaker_, scenario)


# ---------------------------------------------------------------------------
# 2 — N parallel closes of the SAME worksheet: exactly one wins.
# ---------------------------------------------------------------------------


async def test_parallel_closes_of_same_worksheet_consume_exactly_once(sessionmaker_):
    """Stock is deliberately **abundant** (100000 on hand for a 6000 draw).

    With a scarce lot this test passes even with the version guard deleted: the second closer is
    stopped by "insufficient stock" rather than by the guard, and the assertions cannot tell the
    two apart. Abundance removes that alibi — if the guard fails, all eight closers succeed and
    both the on-hand and the movement count are wrong. Verified by deleting the guard and watching
    this test go red.
    """
    scenario = await _seed(sessionmaker_, lot_quantities=[ABUNDANT_STOCK], worksheets=1)
    try:
        barrier = asyncio.Barrier(PARALLEL_CLOSERS)
        results = await asyncio.wait_for(
            asyncio.gather(
                *[
                    _run_close(sessionmaker_, scenario, 0, 6000, barrier)
                    for _ in range(PARALLEL_CLOSERS)
                ]
            ),
            timeout=30,
        )

        assert results.count(200) == 1, f"expected exactly one winner, got {results}"
        assert results.count(409) == PARALLEL_CLOSERS - 1, results

        # 6000 left the books once, not eight times.
        assert await _on_hand(sessionmaker_, scenario) == ABUNDANT_STOCK - 6000

        # By kind and count, not just the total (plan §9.1): one consume, zero adjust.
        movements = await _movements(sessionmaker_, scenario)
        assert movements == [("consume", -6000)], movements
        assert [m for m in movements if m[0] == "adjust"] == []

        async with sessionmaker_() as db:
            row = await db.execute(
                text("SELECT status, version FROM production_worksheets WHERE id = :id"),
                {"id": scenario.worksheet_ids[0]},
            )
            status_, version = row.one()
        assert (status_, version) == ("closed", 1)
    finally:
        await _teardown(sessionmaker_, scenario)


# ---------------------------------------------------------------------------
# 3 — Repeatability. "Correct on-hand EVERY run" is the acceptance criterion.
# ---------------------------------------------------------------------------


async def test_parallel_closes_are_repeatable(sessionmaker_):
    for round_no in range(REPEAT_ROUNDS):
        scenario = await _seed(sessionmaker_, lot_quantities=[ABUNDANT_STOCK], worksheets=1)
        try:
            barrier = asyncio.Barrier(PARALLEL_CLOSERS)
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        _run_close(sessionmaker_, scenario, 0, 6000, barrier)
                        for _ in range(PARALLEL_CLOSERS)
                    ]
                ),
                timeout=30,
            )
            assert results.count(200) == 1, f"round {round_no}: {results}"
            assert (
                await _on_hand(sessionmaker_, scenario) == ABUNDANT_STOCK - 6000
            ), f"round {round_no}"
            assert await _movements(sessionmaker_, scenario) == [
                ("consume", -6000)
            ], f"round {round_no}"
        finally:
            await _teardown(sessionmaker_, scenario)


# ---------------------------------------------------------------------------
# 4 — Different worksheets, same stock: oversell must be refused, never negative.
# ---------------------------------------------------------------------------


async def test_parallel_closes_on_shared_stock_never_oversell(sessionmaker_):
    """6 worksheets × 2000 = 12000 demanded against 10000 on hand. Five may win, one must lose."""
    worksheets = 6
    scenario = await _seed(
        sessionmaker_, lot_quantities=[10000], worksheets=worksheets, planned=2000
    )
    try:
        barrier = asyncio.Barrier(worksheets)
        results = await asyncio.wait_for(
            asyncio.gather(
                *[
                    _run_close(sessionmaker_, scenario, i, 2000, barrier)
                    for i in range(worksheets)
                ]
            ),
            timeout=30,
        )

        successes = results.count(200)
        assert successes == 5, f"expected 5 winners against 10000 on hand, got {results}"
        assert results.count(409) == 1, results

        final = await _on_hand(sessionmaker_, scenario)
        assert final >= 0, "on-hand went negative — the CHECK constraint should never be the guard"
        assert final == 10000 - successes * 2000, "on-hand must match exactly what won"
        assert final == 0, "the five winners should have drained the lot"

        # Five movements of -2000 and nothing else: no partial draw from the closer that lost.
        movements = await _movements(sessionmaker_, scenario)
        assert movements == [("consume", -2000)] * 5, movements
    finally:
        await _teardown(sessionmaker_, scenario)


# ---------------------------------------------------------------------------
# 5 — Multi-lot FIFO under contention, and no deadlock.
# ---------------------------------------------------------------------------


async def test_parallel_closes_across_multiple_lots_do_not_deadlock(sessionmaker_):
    """Two closes draw 6000 each across three lots. Ascending-id lock order must prevent a
    deadlock; the timeout is the assertion."""
    scenario = await _seed(
        sessionmaker_, lot_quantities=[2500, 2500, 5000], worksheets=2, planned=6000
    )
    try:
        barrier = asyncio.Barrier(2)
        results = await asyncio.wait_for(
            asyncio.gather(*[_run_close(sessionmaker_, scenario, i, 6000, barrier) for i in (0, 1)]),
            timeout=20,
        )

        # 10000 on hand, 6000 each: exactly one can be satisfied.
        assert results.count(200) == 1, results
        assert results.count(409) == 1, results
        assert await _on_hand(sessionmaker_, scenario) == 4000

        # FIFO: drains lot 1 and lot 2, part-draws lot 3.
        movements = await _movements(sessionmaker_, scenario)
        assert movements == [("consume", -2500), ("consume", -2500), ("consume", -1000)], movements
    finally:
        await _teardown(sessionmaker_, scenario)
