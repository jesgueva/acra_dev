"""A8-1 integration — the seed writer against a real database.

`tests/test_seed_scaling.py` proves the *plan* scales. This proves the *writer* does: that the
counts actually land, that re-running is a no-op, that raising the scale is additive, and that
`allocate_inventory` does not abort mid-run at volume (the trap that would otherwise only surface
during a benchmark setup).

**Why this one is opt-in.** Every other integration test cleans up the rows it creates. Seeding is
global by nature — it writes the demo fixture into whatever database it is pointed at — so running
it against a developer's working database would silently replace their state. It therefore requires
an explicit, separate DSN:

    createdb acra_seed_test
    ACRA_SEED_IT_DSN=postgresql+asyncpg://postgres:postgres@localhost:5441/acra_seed_test \\
      pytest tests/integration/test_seed_scaling.py -v

The database must already have `alembic upgrade head` applied. A10-3 wires this DSN into CI; until
then it is skipped by default, which is recorded as a known gap on the ticket.
"""
import os
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.delivery import Delivery, DeliveryItem
from app.models.delivery_note import DeliveryNote, DeliveryNoteType
from app.models.inventory import InventoryLot
from app.models.product import Product
from app.models.work_order import WorkOrder, WorkOrderMaterial
from scripts import seed_fake_data as seeder

SEED_IT_DSN = os.getenv("ACRA_SEED_IT_DSN")

pytestmark = pytest.mark.skipif(
    not SEED_IT_DSN,
    reason="Set ACRA_SEED_IT_DSN to a scratch database (never your dev DB) to run the seed "
    "integration tests — they write the demo fixture globally and do not clean up.",
)

DELIVERIES_PER_UNIT = 24
DELIVERY_ITEMS_PER_UNIT = 72
WORK_ORDERS_PER_UNIT = 8
WORK_ORDER_MATERIALS_PER_UNIT = 21


async def _counts() -> dict[str, int]:
    engine = create_async_engine(SEED_IT_DSN)
    try:
        async with AsyncSession(engine) as session:
            out = {}
            for label, model, where in [
                ("delivery_notes", DeliveryNote, DeliveryNote.type == DeliveryNoteType.INBOUND.value),
                ("deliveries", Delivery, None),
                ("delivery_items", DeliveryItem, None),
                ("inventory_lots", InventoryLot, None),
                ("work_orders", WorkOrder, None),
                ("work_order_materials", WorkOrderMaterial, None),
                ("products", Product, None),
            ]:
                stmt = select(func.count()).select_from(model)
                if where is not None:
                    stmt = stmt.where(where)
                out[label] = (await session.execute(stmt)).scalar_one()
            return out
    finally:
        await engine.dispose()


async def _truncate() -> None:
    """Wipe the fixture tables so each test starts from a known floor."""
    engine = create_async_engine(SEED_IT_DSN)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE material_allocations, work_order_materials, work_orders, "
                    "inventory_transactions, inventory_lots, delivery_items, deliveries, "
                    "delivery_notes, low_stock_alerts, products RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _point_seeder_at_the_scratch_db(monkeypatch):
    """The seeder reads its DSN at import time; redirect it for the duration of the test."""
    monkeypatch.setattr(seeder, "DATABASE_URL", SEED_IT_DSN)


async def test_scale_two_writes_the_expected_volume():
    await _truncate()
    counts = await seeder.seed_fake_data(delivery_count=48, work_order_count=16)

    assert counts["deliveries"] == DELIVERIES_PER_UNIT * 2
    assert counts["delivery_items"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert counts["raw_inventory_lots"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert counts["work_orders"] == WORK_ORDERS_PER_UNIT * 2
    assert counts["work_order_materials"] == WORK_ORDER_MATERIALS_PER_UNIT * 2

    live = await _counts()
    assert live["delivery_notes"] == DELIVERIES_PER_UNIT * 2
    assert live["delivery_items"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert live["work_orders"] == WORK_ORDERS_PER_UNIT * 2


async def test_rerunning_the_same_scale_creates_nothing():
    await _truncate()
    await seeder.seed_fake_data(delivery_count=48, work_order_count=16)
    before = await _counts()

    repeat = await seeder.seed_fake_data(delivery_count=48, work_order_count=16)

    assert repeat["deliveries"] == 0
    assert repeat["delivery_items"] == 0
    assert repeat["raw_inventory_lots"] == 0
    assert repeat["work_orders"] == 0
    assert repeat["work_order_materials"] == 0
    assert await _counts() == before


async def test_raising_the_scale_is_additive():
    await _truncate()
    await seeder.seed_fake_data(delivery_count=48, work_order_count=16)
    before = await _counts()

    increment = await seeder.seed_fake_data(delivery_count=72, work_order_count=24)

    # Exactly one more scale unit, not a re-seed of everything.
    assert increment["deliveries"] == DELIVERIES_PER_UNIT
    assert increment["work_orders"] == WORK_ORDERS_PER_UNIT

    after = await _counts()
    assert after["delivery_notes"] == before["delivery_notes"] + DELIVERIES_PER_UNIT
    assert after["work_orders"] == before["work_orders"] + WORK_ORDERS_PER_UNIT
    assert after["delivery_items"] == before["delivery_items"] + DELIVERY_ITEMS_PER_UNIT


@pytest.mark.parametrize("scale", [2, 10])
async def test_allocation_does_not_starve_at_scale(scale):
    """The trap: `allocate_inventory` raises rather than degrading, aborting the whole seed."""
    await _truncate()
    counts = await seeder.seed_fake_data(
        delivery_count=DELIVERIES_PER_UNIT * scale,
        work_order_count=WORK_ORDERS_PER_UNIT * scale,
    )
    assert counts["work_orders"] == WORK_ORDERS_PER_UNIT * scale
    assert counts["material_allocations"] > 0


async def test_existence_precheck_survives_the_bind_parameter_limit():
    """The batched pre-check must not reintroduce a scale ceiling.

    asyncpg binds one parameter per IN element and the wire protocol caps a statement at 32 767.
    Measured on this schema: 24 000 elements succeed, 65 000 raise InterfaceError. An unchunked
    pre-check would therefore have failed somewhere around --scale 1 365. This asserts the chunking
    holds well past that, using the query directly so the test stays cheap — actually seeding
    40 000 deliveries would take minutes.
    """
    await _truncate()
    references = [f"DEMO-BOL-2026-{i:03d}" for i in range(1, 40_001)]

    engine = create_async_engine(SEED_IT_DSN)
    try:
        async with AsyncSession(engine) as session:
            found = await seeder._existing_values(
                session,
                DeliveryNote.document_number,
                references,
                DeliveryNote.type == DeliveryNoteType.INBOUND.value,
            )
    finally:
        await engine.dispose()

    assert found == set()  # truncated table, but the query must not raise


async def test_existence_precheck_finds_seeded_rows():
    """Chunking must not lose rows — the pre-check is what makes re-seeding idempotent."""
    await _truncate()
    await seeder.seed_fake_data(delivery_count=48, work_order_count=0)

    planned = [s.bol_reference for s in seeder.plan_deliveries(48, date.today())]
    engine = create_async_engine(SEED_IT_DSN)
    try:
        async with AsyncSession(engine) as session:
            found = await seeder._existing_values(
                session,
                DeliveryNote.document_number,
                planned,
                DeliveryNote.type == DeliveryNoteType.INBOUND.value,
            )
    finally:
        await engine.dispose()

    assert found == set(planned)


async def test_extended_catalogue_creates_distinct_products():
    """A8-6 stresses the per-(item, state) aggregation, which needs products, not just lots."""
    await _truncate()
    await seeder.seed_fake_data(delivery_count=480, work_order_count=0, material_count=60)

    live = await _counts()
    assert live["products"] == 60

    engine = create_async_engine(SEED_IT_DSN)
    try:
        async with AsyncSession(engine) as session:
            distinct = (
                await session.execute(
                    select(func.count(func.distinct(InventoryLot.product_id))).where(
                        InventoryLot.product_id.isnot(None)
                    )
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    assert distinct == 60, "every material in the catalogue should carry lots"
