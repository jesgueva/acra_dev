"""TC-02 — N-parallel worksheet close against **real Postgres** (ACR-30 / RSK-01).

The guarantee under test: a production-worksheet close cannot lose or double-count stock when
several closers race on the same worksheet or the same stock.

Why this file is not like the rest of `tests/` — every other suite mocks the session, and a mock
cannot exhibit a lost update. Each concurrent closer here gets its **own `AsyncSession` on its own
connection**; sharing one would serialize the race away and the test would pass while proving
nothing.

The negative control (`test_negative_control_*`) is the load-bearing test: it implements the
*unguarded* read-modify-write close and asserts that it **does** corrupt stock. If it ever starts
passing, the harness has gone blind and every other assertion in this file is worthless.

Requires a live database (`DATABASE_URL`), as `tests/test_schema.py` does. CI provides one.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.contact import Contact  # noqa: F401 — registers `contacts` for products.contact_id
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.models.production_worksheet import ProductionWorksheet, ProductionWorksheetLine
from app.models.user import User
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import WorksheetCloseLine, WorksheetCloseRequest
from app.services import production_worksheet_service as svc

# Resolved through pydantic-settings, not os.getenv, so this reads `backend/.env` exactly as the
# application does. `os.getenv` would silently fall back to a different database than the one the
# app is configured against — and this module seeds and DELETEs rows.
DATABASE_URL = settings.database_url

# Deterministic knobs — raise locally for a heavier sweep without editing the file.
CLOSERS = int(os.getenv("SPIKE_CLOSERS", "8"))
ROUNDS = int(os.getenv("SPIKE_ROUNDS", "5"))

_MARKER = "__tc02__"


@pytest.fixture(scope="module")
def engine():
    # NullPool: every session gets a genuinely separate connection, which is the whole point.
    eng = create_async_engine(DATABASE_URL, poolclass=NullPool)
    yield eng


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


def _user(user_id: int) -> TokenUser:
    return TokenUser(
        user_id=user_id,
        full_name="TC-02 Supervisor",
        roles=["production_supervisor"],
        preferred_language="en",
        effective_privileges=["production.worksheet.close"],
        production_line="LINE-1",
    )


class Fixture:
    """Ids of the rows one scenario owns, so teardown can be exact."""

    def __init__(self):
        self.user_id = None
        self.product_ids = []
        self.lot_ids = []
        self.worksheet_ids = []
        self.line_ids = []


async def _seed(session_factory, *, products, lots, worksheets):
    """Create an isolated scenario.

    products:   [name, ...]
    lots:       [(product_idx, qty), ...]
    worksheets: [[(product_idx, planned_qty), ...], ...]   one inner list per worksheet
    """
    fx = Fixture()
    async with session_factory() as db:
        user = User(
            username=f"{_MARKER}user_{os.getpid()}_{id(fx)}",
            password_hash="x",
            full_name="TC-02 Supervisor",
            status="active",
        )
        db.add(user)
        await db.flush()
        fx.user_id = user.id

        for name in products:
            p = Product(name=f"{_MARKER}{name}", category="raw")
            db.add(p)
            await db.flush()
            fx.product_ids.append(p.id)

        for product_idx, qty in lots:
            lot = InventoryLot(
                product_id=fx.product_ids[product_idx],
                lot_number=f"{_MARKER}LOT",
                storage_location="A-01",
                status="in_storage",
                quantity_on_hand=qty,
            )
            db.add(lot)
            await db.flush()
            fx.lot_ids.append(lot.id)

        for ws_lines in worksheets:
            ws = ProductionWorksheet(
                production_line="LINE-1",
                scheduled_date="2026-07-23",
                status="draft",
                version=0,
                created_by=fx.user_id,
            )
            db.add(ws)
            await db.flush()
            fx.worksheet_ids.append(ws.id)

            ids = []
            for product_idx, planned in ws_lines:
                ln = ProductionWorksheetLine(
                    worksheet_id=ws.id,
                    product_id=fx.product_ids[product_idx],
                    planned_quantity=planned,
                )
                db.add(ln)
                await db.flush()
                ids.append(ln.id)
            fx.line_ids.append(ids)

        await db.commit()
    return fx


async def _teardown(session_factory, fx: Fixture):
    async with session_factory() as db:
        if fx.lot_ids:
            await db.execute(
                delete(InventoryTransaction).where(InventoryTransaction.lot_id.in_(fx.lot_ids))
            )
        if fx.worksheet_ids:
            await db.execute(
                delete(ProductionWorksheetLine).where(
                    ProductionWorksheetLine.worksheet_id.in_(fx.worksheet_ids)
                )
            )
            await db.execute(
                delete(ProductionWorksheet).where(ProductionWorksheet.id.in_(fx.worksheet_ids))
            )
        if fx.lot_ids:
            await db.execute(delete(InventoryLot).where(InventoryLot.id.in_(fx.lot_ids)))
        if fx.product_ids:
            await db.execute(delete(Product).where(Product.id.in_(fx.product_ids)))
        if fx.user_id:
            await db.execute(delete(AuditLog).where(AuditLog.user_id == fx.user_id))
            await db.execute(delete(User).where(User.id == fx.user_id))
        await db.commit()


async def _close(session_factory, fx, worksheet_id, expected_version, lines):
    """One closer, on its own connection. Returns ('ok', version) or ('conflict', detail)."""
    async with session_factory() as db:
        try:
            resp = await svc.close_worksheet(
                db=db,
                worksheet_id=worksheet_id,
                body=WorksheetCloseRequest(
                    expected_version=expected_version,
                    lines=[WorksheetCloseLine(line_id=lid, actual_quantity=q) for lid, q in lines],
                ),
                current_user=_user(fx.user_id),
            )
            return ("ok", resp.version)
        except HTTPException as exc:
            return ("conflict", f"{exc.status_code}:{exc.detail}")


async def _on_hand(session_factory, lot_ids):
    async with session_factory() as db:
        res = await db.execute(
            select(InventoryLot.quantity_on_hand).where(InventoryLot.id.in_(lot_ids))
        )
        return sum(r[0] for r in res.fetchall())


async def _consume_rows(session_factory, worksheet_id, fx: "Fixture | None" = None):
    """Movements this worksheet wrote.

    Scoped to the fixture's own lots when one is given. `reference_id` alone is not enough:
    these tests run against a real, potentially long-lived database, and worksheet ids restart
    from 1 whenever migration 010 is rolled back and re-applied — so a stale row from an earlier
    life of the schema can collide with a freshly created worksheet and inflate the count.
    """
    async with session_factory() as db:
        q = select(InventoryTransaction).where(
            InventoryTransaction.reference_type == "production_worksheet",
            InventoryTransaction.reference_id == worksheet_id,
        )
        if fx is not None:
            q = q.where(InventoryTransaction.lot_id.in_(fx.lot_ids))
        res = await db.execute(q)
        return list(res.scalars().all())


# ---------------------------------------------------------------------------
# Scenario 5 (written first) — NEGATIVE CONTROL
# ---------------------------------------------------------------------------


async def _unguarded_close(session_factory, lot_id, amount, barrier_delay=0.15):
    """The naive close: read on-hand, compute, write. No row lock, no version guard.

    This is the shape of `inventory_service.adjust_quantity` today. The sleep between read and
    write makes the interleaving deterministic rather than timing-dependent — the race is real
    either way, this just stops the test from being flaky about it.
    """
    async with session_factory() as db:
        res = await db.execute(select(InventoryLot).where(InventoryLot.id == lot_id))
        lot = res.scalar_one()
        current = lot.quantity_on_hand

        await asyncio.sleep(barrier_delay)  # both readers are now holding the same stale value

        await db.execute(
            text("UPDATE inventory_lots SET quantity_on_hand = :q WHERE id = :i"),
            {"q": current - amount, "i": lot_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_negative_control_unguarded_close_loses_updates(session_factory):
    """The harness must be able to SEE a lost update, or nothing else here means anything.

    Two unguarded closers each consume 3000 from a lot of 10000. Correct on-hand is 4000.
    Read-modify-write yields 7000 — one decrement silently vanishes.
    """
    fx = await _seed(session_factory, products=["ctl"], lots=[(0, 10000)], worksheets=[])
    try:
        await asyncio.gather(
            _unguarded_close(session_factory, fx.lot_ids[0], 3000),
            _unguarded_close(session_factory, fx.lot_ids[0], 3000),
        )
        final = await _on_hand(session_factory, fx.lot_ids)

        assert final != 4000, (
            "NEGATIVE CONTROL FAILED TO FAIL — the unguarded close did not lose an update, "
            "so this suite can no longer detect the bug it exists to catch."
        )
        assert final == 7000, f"expected the classic lost update (7000), got {final}"
    finally:
        await _teardown(session_factory, fx)


# ---------------------------------------------------------------------------
# Scenario 1 — same worksheet, N parallel closes (double-close / F1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_close_same_worksheet_exactly_one_wins(session_factory):
    """N=8 closers, one worksheet: exactly one 200, N-1 × 409, stock decremented ONCE."""
    fx = await _seed(
        session_factory, products=["p"], lots=[(0, 10000)], worksheets=[[(0, 10000)]]
    )
    try:
        ws_id = fx.worksheet_ids[0]
        line_id = fx.line_ids[0][0]

        results = await asyncio.gather(
            *[
                _close(session_factory, fx, ws_id, 0, [(line_id, 6000)])
                for _ in range(CLOSERS)
            ]
        )

        oks = [r for r in results if r[0] == "ok"]
        conflicts = [r for r in results if r[0] == "conflict"]

        assert len(oks) == 1, f"expected exactly 1 winner, got {len(oks)}: {results}"
        assert len(conflicts) == CLOSERS - 1
        assert all("409" in c[1] for c in conflicts), f"all losses must be 409: {conflicts}"

        assert await _on_hand(session_factory, fx.lot_ids) == 4000

        txns = await _consume_rows(session_factory, ws_id, fx)
        assert len(txns) == 1, f"stock must move exactly once, saw {len(txns)} movements"
        assert txns[0].transaction_type == "consume"
        assert txns[0].quantity == -6000

        async with session_factory() as db:
            ws = (
                await db.execute(select(ProductionWorksheet).where(ProductionWorksheet.id == ws_id))
            ).scalar_one()
            assert ws.status == "closed"
            assert ws.version == 1, "version must advance exactly once"
    finally:
        await _teardown(session_factory, fx)


# ---------------------------------------------------------------------------
# Scenario 2 — repeatability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_close_is_repeatable(session_factory):
    """Scenario 1 over R rounds on fresh rows. A single flake fails the ticket."""
    for round_no in range(ROUNDS):
        fx = await _seed(
            session_factory, products=["p"], lots=[(0, 10000)], worksheets=[[(0, 10000)]]
        )
        try:
            ws_id = fx.worksheet_ids[0]
            line_id = fx.line_ids[0][0]

            results = await asyncio.gather(
                *[
                    _close(session_factory, fx, ws_id, 0, [(line_id, 6000)])
                    for _ in range(CLOSERS)
                ]
            )

            oks = [r for r in results if r[0] == "ok"]
            assert len(oks) == 1, f"round {round_no}: {len(oks)} winners — {results}"
            final = await _on_hand(session_factory, fx.lot_ids)
            assert final == 4000, f"round {round_no}: on-hand {final}, expected 4000"

            # Assert the same invariants scenario 1 does. Checking only the winner count and the
            # total would let a regression that writes two consume rows, or bumps the version
            # twice, pass all R rounds and be caught by the single-shot test alone.
            txns = await _consume_rows(session_factory, ws_id, fx)
            assert len(txns) == 1, f"round {round_no}: {len(txns)} movements, expected 1"
            assert txns[0].quantity == -6000, f"round {round_no}: {txns[0].quantity}"

            async with session_factory() as db:
                ws = (
                    await db.execute(
                        select(ProductionWorksheet).where(ProductionWorksheet.id == ws_id)
                    )
                ).scalar_one()
                assert ws.version == 1, f"round {round_no}: version {ws.version}, expected 1"
                assert ws.status == "closed"
        finally:
            await _teardown(session_factory, fx)


# ---------------------------------------------------------------------------
# Scenario 3 — different worksheets competing for the same stock (oversell / F2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_close_different_worksheets_never_oversells(session_factory):
    """6 worksheets × 2000 against 10000 on hand — demand exceeds supply by one worksheet.

    5 must succeed and 1 must be refused with an explicit 409. On-hand must land on exactly 0
    and must never go negative — and the `quantity_on_hand >= 0` CHECK constraint must never be
    the thing that catches it, because a constraint violation is a 500 to the operator.
    """
    fx = await _seed(
        session_factory,
        products=["p"],
        lots=[(0, 10000)],
        worksheets=[[(0, 2000)] for _ in range(6)],
    )
    try:
        results = await asyncio.gather(
            *[
                _close(session_factory, fx, fx.worksheet_ids[i], 0, [(fx.line_ids[i][0], 2000)])
                for i in range(6)
            ]
        )

        oks = [r for r in results if r[0] == "ok"]
        conflicts = [r for r in results if r[0] == "conflict"]

        assert len(oks) == 5, f"expected 5 winners, got {len(oks)}: {results}"
        assert len(conflicts) == 1
        assert "Insufficient stock" in conflicts[0][1], conflicts[0][1]

        final = await _on_hand(session_factory, fx.lot_ids)
        assert final == 0, f"expected exactly 0 left, got {final}"
        assert final >= 0

        total_consumed = 0
        for ws_id in fx.worksheet_ids:
            total_consumed += sum(-t.quantity for t in await _consume_rows(session_factory, ws_id, fx))
        assert total_consumed == 10000, "ledger must account for every unit that left"
    finally:
        await _teardown(session_factory, fx)


# ---------------------------------------------------------------------------
# Scenario 4 — multi-line / multi-lot, opposing lock order (deadlock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_line_close_does_not_deadlock(session_factory):
    """Two worksheets whose lines touch products A and B in opposite order.

    Without a deterministic lock order this is the textbook deadlock. The close orders lots by
    `id ASC` for every caller, so both must complete.
    """
    fx = await _seed(
        session_factory,
        products=["A", "B"],
        lots=[(0, 5000), (0, 5000), (1, 5000), (1, 5000)],
        worksheets=[
            [(0, 3000), (1, 3000)],  # A then B
            [(1, 3000), (0, 3000)],  # B then A
        ],
    )
    try:
        async def close_ws(idx, pairs):
            return await _close(session_factory, fx, fx.worksheet_ids[idx], 0, pairs)

        results = await asyncio.wait_for(
            asyncio.gather(
                close_ws(0, [(fx.line_ids[0][0], 3000), (fx.line_ids[0][1], 3000)]),
                close_ws(1, [(fx.line_ids[1][0], 3000), (fx.line_ids[1][1], 3000)]),
            ),
            timeout=20,
        )

        assert all(r[0] == "ok" for r in results), f"both should close: {results}"

        # 10000 of each product, 6000 consumed of each → 4000 each, 8000 total.
        assert await _on_hand(session_factory, fx.lot_ids) == 8000
    finally:
        await _teardown(session_factory, fx)


# ---------------------------------------------------------------------------
# §7.1 — the delta is computed, never written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_writes_no_delta_adjustment(session_factory):
    """planned 10000, actual 6000 — a 4000 variance that must NOT reach the ledger.

    Asserted on movement kind, not just the total: an adjustment row would net out against a
    compensating consume and still leave inventory drifting (`client_domain_model.md` §7.1).
    """
    fx = await _seed(
        session_factory, products=["p"], lots=[(0, 10000)], worksheets=[[(0, 10000)]]
    )
    try:
        ws_id = fx.worksheet_ids[0]
        status, _ = await _close(
            session_factory, fx, ws_id, 0, [(fx.line_ids[0][0], 6000)]
        )
        assert status == "ok"

        txns = await _consume_rows(session_factory, ws_id, fx)
        assert [t.transaction_type for t in txns] == ["consume"]
        assert [t.quantity for t in txns] == [-6000]
        assert await _on_hand(session_factory, fx.lot_ids) == 4000

        async with session_factory() as db:
            line = (
                await db.execute(
                    select(ProductionWorksheetLine).where(
                        ProductionWorksheetLine.id == fx.line_ids[0][0]
                    )
                )
            ).scalar_one()
            # The variance is recoverable by subtraction, which is the whole point.
            assert line.planned_quantity - line.actual_quantity == 4000
    finally:
        await _teardown(session_factory, fx)
