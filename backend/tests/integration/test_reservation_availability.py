"""ACR-27 integration — reserved / available stock against a live database.

The mocked unit tests cannot prove the SQL is right: the active-only filter, the per-(item, state)
grouping, and above all "reserving never moves on-hand" only mean something against real rows.
These run the real service on a real session over a seeded fixture, then measure the aggregation's
latency (RSK-04).

Requires a running PostgreSQL with migrations applied — same contract as `tests/test_schema.py`.

The seed is an async context manager rather than a pytest fixture on purpose: an async fixture is
torn down in a different event loop than the test body, which breaks asyncpg with MissingGreenlet.
`async with` keeps setup, body, and cleanup on one loop.
"""
import os
import statistics
import time
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.audit import AuditLog
from app.models.contact import Contact  # noqa: F401 — registers products.contact_id's FK target
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.models.reservation import ReservationStatus, StockReservation
from app.models.inventory import LotStatus
from app.models.user import User
from app.schemas.reservation import ReservationCreate
from app.services import reservation_service

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
)

# RSK-04 — the availability aggregation must stay cheap at volume.
LATENCY_BUDGET_MS = 200.0
LATENCY_SAMPLES = 20

SEED_LOTS_IN_STORAGE = 200
SEED_LOT_QTY = 500          # ×100 → 5.00 units per lot
SEED_LOTS_IN_PRODUCTION = 10

ON_HAND_IN_STORAGE = SEED_LOTS_IN_STORAGE * SEED_LOT_QTY
ON_HAND_IN_PRODUCTION = SEED_LOTS_IN_PRODUCTION * SEED_LOT_QTY


@asynccontextmanager
async def seeded_stock():
    """One product with lots in two states, torn down afterwards."""
    engine = create_async_engine(DATABASE_URL)
    session = AsyncSession(engine, expire_on_commit=False)
    product_id = None
    try:
        user_id = (
            await session.execute(select(User.id).order_by(User.id).limit(1))
        ).scalar()

        product = Product(name="ACR-27 Fixture Item", category="raw")
        session.add(product)
        await session.flush()
        # Plain int, not the ORM attribute: rollback() below expires the instance, and touching
        # an expired attribute would lazy-load outside a greenlet.
        product_id = product.id

        session.add_all(
            [
                InventoryLot(
                    product_id=product_id,
                    lot_number=f"ACR27-{i:04d}",
                    status=LotStatus.IN_STORAGE.value,
                    quantity_on_hand=SEED_LOT_QTY,
                    storage_location="RACK-27",
                )
                for i in range(SEED_LOTS_IN_STORAGE)
            ]
            + [
                InventoryLot(
                    product_id=product_id,
                    lot_number=f"ACR27-WIP-{i:04d}",
                    status=LotStatus.IN_PRODUCTION.value,
                    quantity_on_hand=SEED_LOT_QTY,
                    storage_location="LINE-1",
                )
                for i in range(SEED_LOTS_IN_PRODUCTION)
            ]
        )
        await session.commit()

        yield {"session": session, "product_id": product_id, "user_id": user_id}
    finally:
        if product_id is not None:
            await session.rollback()  # discard anything a failing test left open
            reservation_ids = (
                await session.execute(
                    select(StockReservation.id).where(
                        StockReservation.product_id == product_id
                    )
                )
            ).scalars().all()
            if reservation_ids:
                await session.execute(
                    delete(AuditLog).where(
                        AuditLog.entity_type == "stock_reservation",
                        AuditLog.entity_id.in_(reservation_ids),
                    )
                )
            await session.execute(
                delete(StockReservation).where(StockReservation.product_id == product_id)
            )
            await session.execute(
                delete(InventoryLot).where(InventoryLot.product_id == product_id)
            )
            await session.execute(delete(Product).where(Product.id == product_id))
            await session.commit()
        await session.close()
        await engine.dispose()


async def _lot_quantities(session: AsyncSession, product_id: int) -> list[tuple[int, int]]:
    rows = await session.execute(
        select(InventoryLot.id, InventoryLot.quantity_on_hand)
        .where(InventoryLot.product_id == product_id)
        .order_by(InventoryLot.id)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def test_availability_matches_seeded_fixture():
    """on_hand / reserved / available are computed correctly off real rows."""
    async with seeded_stock() as seeded:
        result = await reservation_service.availability(
            db=seeded["session"],
            product_id=seeded["product_id"],
            state=LotStatus.IN_STORAGE,
        )

        assert result.on_hand == ON_HAND_IN_STORAGE
        assert result.reserved == 0
        assert result.available == ON_HAND_IN_STORAGE
        assert result.product_name == "ACR-27 Fixture Item"


async def test_reserve_lowers_available_but_never_on_hand():
    """THE acceptance criterion, against real rows.

    Reserving must leave every lot byte-identical and write no inventory transaction.
    """
    async with seeded_stock() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]
        lots_before = await _lot_quantities(session, product_id)
        txns_before = (
            await session.execute(select(func.count()).select_from(InventoryTransaction))
        ).scalar()

        reserve_qty = 30000
        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(
                product_id=product_id, state=LotStatus.IN_STORAGE, quantity=reserve_qty
            ),
            user_id=seeded["user_id"],
        )

        after = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_STORAGE
        )

        assert after.on_hand == ON_HAND_IN_STORAGE, "on-hand must not move on reserve"
        assert after.reserved == reserve_qty
        assert after.available == ON_HAND_IN_STORAGE - reserve_qty

        assert await _lot_quantities(session, product_id) == lots_before, "no lot may be mutated"
        txns_after = (
            await session.execute(select(func.count()).select_from(InventoryTransaction))
        ).scalar()
        assert txns_after == txns_before, "reserving must not write a stock movement"


async def test_released_reservations_are_excluded_from_reserved():
    """The `status = 'active'` filter holds in real SQL."""
    async with seeded_stock() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        created = await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=product_id, quantity=12500),
            user_id=seeded["user_id"],
        )
        mid = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_STORAGE
        )
        assert mid.reserved == 12500

        released = await reservation_service.release(
            db=session, reservation_id=created.id, user_id=seeded["user_id"]
        )
        assert released.status == ReservationStatus.RELEASED
        assert released.released_at is not None

        after = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_STORAGE
        )
        assert after.reserved == 0
        assert after.available == ON_HAND_IN_STORAGE


async def test_availability_is_isolated_per_state():
    """A reservation in one state must not affect another state's availability."""
    async with seeded_stock() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(
                product_id=product_id, state=LotStatus.IN_STORAGE, quantity=10000
            ),
            user_id=seeded["user_id"],
        )

        in_production = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_PRODUCTION
        )

        assert in_production.on_hand == ON_HAND_IN_PRODUCTION
        assert in_production.reserved == 0
        assert in_production.available == ON_HAND_IN_PRODUCTION


async def test_reserving_more_than_available_is_rejected():
    """Cumulative reservations cannot oversubscribe on-hand."""
    async with seeded_stock() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=product_id, quantity=ON_HAND_IN_STORAGE - 100),
            user_id=seeded["user_id"],
        )

        with pytest.raises(HTTPException) as exc:
            await reservation_service.reserve(
                db=session,
                data=ReservationCreate(product_id=product_id, quantity=101),
                user_id=seeded["user_id"],
            )
        assert exc.value.status_code == 422

        # The 100 still available is reservable.
        ok = await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=product_id, quantity=100),
            user_id=seeded["user_id"],
        )
        assert ok.quantity == 100

        final = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_STORAGE
        )
        assert final.available == 0
        assert final.on_hand == ON_HAND_IN_STORAGE


async def test_availability_latency_budget():
    """RSK-04 — the aggregation stays within budget at volume.

    If this fails, that is the trigger for the periodic-snapshot fallback, not a reason to
    loosen the budget.
    """
    async with seeded_stock() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        session.add_all(
            [
                StockReservation(
                    product_id=product_id,
                    state=LotStatus.IN_STORAGE.value,
                    quantity=10,
                    status=(
                        ReservationStatus.ACTIVE.value
                        if i % 2
                        else ReservationStatus.RELEASED.value
                    ),
                    created_by=seeded["user_id"],
                )
                for i in range(200)
            ]
        )
        await session.commit()

        timings_ms = []
        for _ in range(LATENCY_SAMPLES):
            start = time.perf_counter()
            await reservation_service.availability(
                db=session, product_id=product_id, state=LotStatus.IN_STORAGE
            )
            timings_ms.append((time.perf_counter() - start) * 1000)

        timings_ms.sort()
        p95 = timings_ms[int(len(timings_ms) * 0.95) - 1]
        median = statistics.median(timings_ms)
        print(
            f"\navailability latency over {SEED_LOTS_IN_STORAGE} lots + 200 reservations: "
            f"median {median:.1f}ms, p95 {p95:.1f}ms (budget {LATENCY_BUDGET_MS:.0f}ms)"
        )

        assert p95 < LATENCY_BUDGET_MS, (
            f"p95 {p95:.1f}ms exceeded {LATENCY_BUDGET_MS:.0f}ms budget"
        )

        # Correctness must still hold at volume: 100 active reservations × 10.
        result = await reservation_service.availability(
            db=session, product_id=product_id, state=LotStatus.IN_STORAGE
        )
        assert result.reserved == 1000
        assert result.available == ON_HAND_IN_STORAGE - 1000
