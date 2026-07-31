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
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


@pytest.fixture
async def sessions():
    """An async_sessionmaker bound to the scratch DSN.

    Yields the *maker*, not a live session — same shape as
    `test_worksheet_close_concurrency.py`. Handing back a session instead would tear it down in a
    different event loop than the test body ran in, which is the `MissingGreenlet` trap
    `test_reservation_availability.py` documents.
    """
    engine = create_async_engine(SEED_IT_DSN)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


COUNTED_TABLES = [
    ("delivery_notes", DeliveryNote, DeliveryNote.type == DeliveryNoteType.INBOUND.value),
    ("deliveries", Delivery, None),
    ("delivery_items", DeliveryItem, None),
    ("inventory_lots", InventoryLot, None),
    ("work_orders", WorkOrder, None),
    ("work_order_materials", WorkOrderMaterial, None),
    ("products", Product, None),
]

# The seeder's own output tables, children first — `products` must trail the rows referencing it.
FIXTURE_TABLES = (
    "material_allocations, work_order_materials, work_orders, inventory_transactions, "
    "inventory_lots, delivery_items, deliveries, delivery_notes, low_stock_alerts, products"
)

# CASCADE reaches further than that list. Measured against this schema, truncating FIXTURE_TABLES
# also empties every table below — none written by the seeder, all referencing products or lots.
# Named so the blast radius is visible in the code rather than discovered against a real database.
CASCADED_TABLES = (
    "shipments",
    "shipment_items",
    "stock_reservations",
    "production_worksheets",
    "production_worksheet_lines",
    "invoices",
    "invoice_lines",
)

# Deliberately NOT truncated: roles, role_privilege_assignments, users, user_role_assignments,
# contacts. The seeder upserts them, no test here asserts their counts, and wiping users would
# cascade into audit_logs. The trade-off is real though: `ensure_role_privileges` only ever adds
# grants, never removes them, so a long-lived scratch database can drift from ROLE_DEFINITIONS
# without anything here noticing. A10-5's privilege-parity test is the right place to catch that.


async def _counts(sessions) -> dict[str, int]:
    async with sessions() as session:
        out = {}
        for label, model, where in COUNTED_TABLES:
            stmt = select(func.count()).select_from(model)
            if where is not None:
                stmt = stmt.where(where)
            out[label] = (await session.execute(stmt)).scalar_one()
        return out


async def _truncate(sessions) -> None:
    """Empty the seeder's tables so each test starts from a known floor.

    Destructive well beyond the seeder's own output — see CASCADED_TABLES. That blast radius is
    exactly why this module demands a dedicated ACRA_SEED_IT_DSN instead of reusing the dev DSN.
    """
    async with sessions() as session:
        await session.execute(text(f"TRUNCATE {FIXTURE_TABLES} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture(autouse=True)
def _point_seeder_at_the_scratch_db(monkeypatch):
    """The seeder reads its DSN at import time; redirect it for the duration of the test."""
    monkeypatch.setattr(seeder, "DATABASE_URL", SEED_IT_DSN)


async def test_scale_two_writes_the_expected_volume(sessions):
    await _truncate(sessions)
    counts = await seeder.seed_fake_data(delivery_count=48, work_order_count=16)

    assert counts["deliveries"] == DELIVERIES_PER_UNIT * 2
    assert counts["delivery_items"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert counts["raw_inventory_lots"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert counts["work_orders"] == WORK_ORDERS_PER_UNIT * 2
    assert counts["work_order_materials"] == WORK_ORDER_MATERIALS_PER_UNIT * 2

    live = await _counts(sessions)
    assert live["delivery_notes"] == DELIVERIES_PER_UNIT * 2
    assert live["delivery_items"] == DELIVERY_ITEMS_PER_UNIT * 2
    assert live["work_orders"] == WORK_ORDERS_PER_UNIT * 2


async def test_rerunning_the_same_scale_creates_nothing(sessions):
    await _truncate(sessions)
    await seeder.seed_fake_data(delivery_count=48, work_order_count=16)
    before = await _counts(sessions)

    repeat = await seeder.seed_fake_data(delivery_count=48, work_order_count=16)

    assert repeat["deliveries"] == 0
    assert repeat["delivery_items"] == 0
    assert repeat["raw_inventory_lots"] == 0
    assert repeat["work_orders"] == 0
    assert repeat["work_order_materials"] == 0
    assert await _counts(sessions) == before


async def test_raising_the_scale_is_additive(sessions):
    await _truncate(sessions)
    await seeder.seed_fake_data(delivery_count=48, work_order_count=16)
    before = await _counts(sessions)

    increment = await seeder.seed_fake_data(delivery_count=72, work_order_count=24)

    # Exactly one more scale unit, not a re-seed of everything.
    assert increment["deliveries"] == DELIVERIES_PER_UNIT
    assert increment["work_orders"] == WORK_ORDERS_PER_UNIT

    after = await _counts(sessions)
    assert after["delivery_notes"] == before["delivery_notes"] + DELIVERIES_PER_UNIT
    assert after["work_orders"] == before["work_orders"] + WORK_ORDERS_PER_UNIT
    assert after["delivery_items"] == before["delivery_items"] + DELIVERY_ITEMS_PER_UNIT


@pytest.mark.parametrize("scale", [2, 10])
async def test_allocation_does_not_starve_at_scale(scale, sessions):
    """The trap: `allocate_inventory` raises rather than degrading, aborting the whole seed."""
    await _truncate(sessions)
    counts = await seeder.seed_fake_data(
        delivery_count=DELIVERIES_PER_UNIT * scale,
        work_order_count=WORK_ORDERS_PER_UNIT * scale,
    )
    assert counts["work_orders"] == WORK_ORDERS_PER_UNIT * scale
    assert counts["material_allocations"] > 0


async def test_existence_precheck_survives_the_bind_parameter_limit(sessions):
    """The batched pre-check must not reintroduce a scale ceiling.

    asyncpg binds one parameter per IN element and the wire protocol caps a statement at 32 767.
    Measured on this schema: 24 000 elements succeed, 65 000 raise InterfaceError. An unchunked
    pre-check would therefore have failed somewhere around --scale 1 365. This asserts the chunking
    holds well past that, using the query directly so the test stays cheap — actually seeding
    40 000 deliveries would take minutes.
    """
    await _truncate(sessions)
    references = [f"DEMO-BOL-2026-{i:03d}" for i in range(1, 40_001)]

    async with sessions() as session:
        found = await seeder._existing_values(
            session,
            DeliveryNote.document_number,
            references,
            DeliveryNote.type == DeliveryNoteType.INBOUND.value,
        )

    assert found == set()  # truncated table, but the query must not raise


async def test_existence_precheck_finds_seeded_rows(sessions):
    """Chunking must not lose rows — the pre-check is what makes re-seeding idempotent."""
    await _truncate(sessions)
    await seeder.seed_fake_data(delivery_count=48, work_order_count=0)

    planned = [s.bol_reference for s in seeder.plan_deliveries(48, date.today())]
    async with sessions() as session:
        found = await seeder._existing_values(
            session,
            DeliveryNote.document_number,
            planned,
            DeliveryNote.type == DeliveryNoteType.INBOUND.value,
        )

    assert found == set(planned)


async def test_existence_precheck_unions_matches_across_chunks(sessions, monkeypatch):
    """Matches must accumulate across chunks, not be overwritten by the last one.

    This is the case that actually matters, and the one the two tests above miss: they either query
    an empty table (where any return value passes) or stay inside a single chunk. An
    `_existing_values` that assigned instead of `update()`-ing would pass both of them and still
    break re-seeding past the chunk size — the seeder would conclude that already-present BOLs were
    missing, then collide with the unique constraint on `delivery_notes`.

    Shrinking the chunk size is what makes this cheap: 48 real rows across a chunk size of 10 spans
    five chunks, versus the ~20 000 rows it would take at the production value.
    """
    await _truncate(sessions)
    await seeder.seed_fake_data(delivery_count=48, work_order_count=0)
    planned = [s.bol_reference for s in seeder.plan_deliveries(48, date.today())]

    monkeypatch.setattr(seeder, "IN_CLAUSE_CHUNK", 10)

    async with sessions() as session:
        found = await seeder._existing_values(
            session,
            DeliveryNote.document_number,
            planned,
            DeliveryNote.type == DeliveryNoteType.INBOUND.value,
        )

    assert len(found) == 48, "every chunk must contribute its matches, not replace them"
    assert found == set(planned)


async def test_today_reaches_both_halves_of_the_seed(sessions):
    """`today=` must drive work-order target dates, not just delivery dates.

    `create_demo_work_orders` used to call `date.today()` itself, so the caller's `today` silently
    applied to deliveries only — invisible in normal use, but it made the determinism the module
    docstring promises untrue for half the fixture, and let a run straddling midnight date the two
    halves against different days.
    """
    await _truncate(sessions)
    fixed = date(2026, 1, 15)
    await seeder.seed_fake_data(delivery_count=24, work_order_count=8, today=fixed)

    async with sessions() as session:
        notes = (await session.execute(select(DeliveryNote.document_number))).scalars().all()
        targets = (await session.execute(select(WorkOrder.target_date))).scalars().all()

    assert all(ref.startswith("DEMO-BOL-2026-") for ref in notes)

    # Every seeded work order's target is `fixed` plus its own offset, so all of them must sit
    # within the spread of offsets the fixture declares — impossible if the writer used the clock.
    offsets = [s.target_in_days for s in seeder.plan_work_orders(8)]
    assert sorted(targets) == sorted(fixed + timedelta(days=d) for d in offsets)


async def test_extended_catalogue_creates_distinct_products(sessions):
    """A8-6 stresses the per-(item, state) aggregation, which needs products, not just lots."""
    await _truncate(sessions)
    await seeder.seed_fake_data(delivery_count=480, work_order_count=0, material_count=60)

    live = await _counts(sessions)
    assert live["products"] == 60

    async with sessions() as session:
        distinct = (
            await session.execute(
                select(func.count(func.distinct(InventoryLot.product_id))).where(
                    InventoryLot.product_id.isnot(None)
                )
            )
        ).scalar_one()

    assert distinct == 60, "every material in the catalogue should carry lots"
