"""A8-6 integration — the four aggregation read paths, against real rows at real volume.

RSK-04 is about behaviour that only exists in PostgreSQL: which plan the optimiser picks, and how
that plan scales. A mocked session proves none of it. These tests seed ten thousand lots, run the
**real service functions**, and assert two different things:

* **Correctness at volume** — the numbers must not move because an index was added. An index that
  changes an answer is a bug, and this is where that would surface.
* **The index is actually used** — `test_index_is_used_not_merely_present` is the negative control.
  It drops the index inside a transaction, confirms the plan degrades to a sequential scan, then
  rolls back so the schema is untouched. Without it, "we added an index" is an assertion about a
  `CREATE INDEX` statement rather than about the query, and an index the planner ignores looks
  exactly like one that works.

Requires a running PostgreSQL with migrations applied — same contract as `tests/test_schema.py`.
Everything created here is tagged so teardown removes exactly its own rows: lots by
`storage_location = 'A86-IT'`, products and the fixture user by an `A86-IT` name prefix, and
reservations — which have no `storage_location` column — by the sentinel
`production_worksheet_line_id = -87`.

The seed is an async context manager rather than a pytest fixture on purpose: an async fixture is
torn down in a different event loop than the test body, which breaks asyncpg with MissingGreenlet.
`async with` keeps setup, body, and cleanup on one loop — the same reason
`test_reservation_availability.py` is shaped this way.
"""
import importlib.util
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.benchmark import percentiles
from app.models.contact import Contact  # noqa: F401 — registers products.contact_id's FK target
from app.models.inventory import LotStatus
from app.schemas.inventory import LowStockAlertCreate
from app.services import inventory_service, reservation_service

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5434/acra_db",
)

TAG = "A86-IT"
INDEX_NAME = "ix_inventory_lots_item_state"


def _load_bench_module():
    """Import the runner from the repo-root `scripts/` tree, which is not on the backend path.

    tests/integration/<this file> -> tests -> backend -> repo root.
    """
    path = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "aggregation_bench.py"
    if not path.is_file():
        # The backend image is built from `backend/` alone, so the repo-root `scripts/` tree is not
        # in the container. That is a packaging boundary, not a broken test — skip the module the way
        # `test_packaging.py`'s `requires_repo_root` does. Raising here fails *collection*, which
        # takes the whole suite down rather than this file.
        pytest.skip(
            "repo-root scripts/validation/ not available (running from the backend image)",
            allow_module_level=True,
        )
    spec = importlib.util.spec_from_file_location("acra_aggregation_bench_it", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench_module = _load_bench_module()

# The fixture has to be both big enough and **selective** enough.
#
# Size alone is not sufficient: an index is only the cheaper plan when the predicate matches a
# small fraction of the table. An earlier version of this fixture put all 5 000 lots on one
# product, which made that product 23% of every row in the table — and at that selectivity
# PostgreSQL correctly prefers a sequential scan even with the index in place, so the negative
# control failed depending on what else had been seeded. That is the planner being right, not a
# flaky test.
#
# So the shape here mirrors a real warehouse: one item under test holding a small slice of stock,
# and many other items making up the rest. `availability` is always a single-item question.
FOCUS_LOTS = 500                 # lots belonging to the product under test
FILLER_LOTS = 9_500              # lots belonging to other products
FILLER_PRODUCTS = 40
SEED_LOTS = FOCUS_LOTS + FILLER_LOTS

LOT_QTY = 500                    # ×100 → 5.00 units per lot
IN_PRODUCTION_EVERY = 10         # a tenth of the lots sit in the other state
RESERVATION_ROWS = 400           # half active, half released
RESERVATION_QTY = 10
BENCH_LINE_MARKER = -87          # production_worksheet_line_id tag for this file's reservations

FOCUS_IN_PRODUCTION_LOTS = FOCUS_LOTS // IN_PRODUCTION_EVERY
FOCUS_IN_STORAGE_LOTS = FOCUS_LOTS - FOCUS_IN_PRODUCTION_LOTS
ON_HAND_IN_STORAGE = FOCUS_IN_STORAGE_LOTS * LOT_QTY
ON_HAND_IN_PRODUCTION = FOCUS_IN_PRODUCTION_LOTS * LOT_QTY
ACTIVE_RESERVED = (RESERVATION_ROWS // 2) * RESERVATION_QTY

# RSK-04's budget, tightened from the 200 ms carried by test_reservation_availability.py. See
# test_availability_latency_budget_at_volume for where this number comes from.
LATENCY_BUDGET_MS = 50.0
LATENCY_SAMPLES = 40


@asynccontextmanager
async def seeded_volume():
    """A focus product plus filler products, sized so the focus item is a selective slice."""
    engine = create_async_engine(DATABASE_URL)
    session = AsyncSession(engine, expire_on_commit=False)
    product_id = None
    user_id = None
    try:
        user_id = await session.scalar(
            text(
                "INSERT INTO users (username, password_hash, full_name, status)"
                " VALUES (:username, 'not-used', :full_name, 'active') RETURNING id"
            ),
            {
                "username": f"{TAG.lower()}-{time.time_ns()}",
                "full_name": f"{TAG} Fixture User",
            },
        )
        product_id = await session.scalar(
            text("INSERT INTO products (name, category) VALUES (:n, 'raw') RETURNING id"),
            {"n": f"{TAG} Fixture Item"},
        )
        filler_ids = []
        for i in range(FILLER_PRODUCTS):
            filler_ids.append(
                await session.scalar(
                    text("INSERT INTO products (name, category) VALUES (:n, 'raw') RETURNING id"),
                    {"n": f"{TAG} Filler {i:03d}"},
                )
            )

        await session.execute(
            text(
                "INSERT INTO inventory_lots"
                " (product_id, lot_number, storage_location, status, quantity_on_hand)"
                " SELECT :pid, :tag || '-' || g, :tag,"
                "        CASE WHEN g % :every = 0 THEN 'in_production' ELSE 'in_storage' END,"
                "        :qty"
                " FROM generate_series(CAST(1 AS bigint), CAST(:n AS bigint)) g"
            ),
            {
                "pid": product_id,
                "tag": TAG,
                "every": IN_PRODUCTION_EVERY,
                "qty": LOT_QTY,
                "n": FOCUS_LOTS,
            },
        )
        # Filler rows so the focus product is a small fraction of the table — see the note on
        # FOCUS_LOTS. Without these the planner sensibly ignores the index and the negative
        # control asserts something untrue.
        await session.execute(
            text(
                "INSERT INTO inventory_lots"
                " (product_id, lot_number, storage_location, status, quantity_on_hand)"
                " SELECT (CAST(:pids AS int[]))[1 + (g % :np)], :tag || '-F-' || g, :tag,"
                "        CASE WHEN g % :every = 0 THEN 'in_production' ELSE 'in_storage' END,"
                "        :qty"
                " FROM generate_series(CAST(1 AS bigint), CAST(:n AS bigint)) g"
            ),
            {
                "pids": filler_ids,
                "np": len(filler_ids),
                "tag": TAG,
                "every": IN_PRODUCTION_EVERY,
                "qty": LOT_QTY,
                "n": FILLER_LOTS,
            },
        )
        await session.execute(
            text(
                "INSERT INTO stock_reservations"
                " (product_id, state, quantity, production_worksheet_line_id, status, created_by)"
                " SELECT :pid, 'in_storage', :qty, :marker,"
                "        CASE WHEN g % 2 = 0 THEN 'active' ELSE 'released' END,"
                "        :uid"
                " FROM generate_series(CAST(1 AS bigint), CAST(:n AS bigint)) g"
            ),
            {
                "pid": product_id,
                "qty": RESERVATION_QTY,
                "marker": BENCH_LINE_MARKER,
                "uid": user_id,
                "n": RESERVATION_ROWS,
            },
        )
        # Trap 2 — the planner reads pg_statistic, not row counts. Without this the tests below
        # would plan against a table PostgreSQL still believes is empty.
        await session.execute(text("ANALYZE inventory_lots, stock_reservations"))
        await session.commit()

        yield {"session": session, "product_id": product_id, "user_id": user_id}
    finally:
        await session.rollback()
        if product_id is not None:
            await session.execute(
                text("DELETE FROM low_stock_alerts WHERE product_id = :pid"),
                {"pid": product_id},
            )
            await session.execute(
                text("DELETE FROM stock_reservations WHERE production_worksheet_line_id = :m"),
                {"m": BENCH_LINE_MARKER},
            )
            await session.execute(
                text("DELETE FROM inventory_lots WHERE storage_location = :t"), {"t": TAG}
            )
            await session.execute(
                text("DELETE FROM products WHERE name LIKE :p"), {"p": f"{TAG} %"}
            )
        if user_id is not None:
            await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
        if product_id is not None or user_id is not None:
            await session.commit()
        await session.close()
        await engine.dispose()


async def _explain(session: AsyncSession, product_id: int) -> str:
    """The plan for `_on_hand`'s aggregate — the query the index exists to serve."""
    rows = await session.execute(
        text(
            "EXPLAIN ANALYZE SELECT COALESCE(SUM(quantity_on_hand), 0) FROM inventory_lots"
            " WHERE product_id = :pid AND status = 'in_storage'"
        ),
        {"pid": product_id},
    )
    return "\n".join(r[0] for r in rows.all())


async def _index_exists(session: AsyncSession) -> bool:
    found = await session.scalar(
        text("SELECT 1 FROM pg_indexes WHERE tablename = 'inventory_lots' AND indexname = :n"),
        {"n": INDEX_NAME},
    )
    return bool(found)


# ── Correctness at volume — an index must never change an answer ──────────────


async def test_availability_is_correct_at_volume():
    async with seeded_volume() as seeded:
        result = await reservation_service.availability(
            db=seeded["session"],
            product_id=seeded["product_id"],
            state=LotStatus.IN_STORAGE,
        )

        assert result.on_hand == ON_HAND_IN_STORAGE
        assert result.reserved == ACTIVE_RESERVED
        assert result.available == ON_HAND_IN_STORAGE - ACTIVE_RESERVED


async def test_released_reservations_stay_excluded_at_volume():
    """The `status = 'active'` filter must survive the composite index.

    A `(product_id, status)` index on the *lots* table has no bearing on the reservation filter,
    but an index that made the planner switch strategies here is exactly the kind of change that
    silently alters a total, so it is asserted rather than assumed.
    """
    async with seeded_volume() as seeded:
        result = await reservation_service.availability(
            db=seeded["session"], product_id=seeded["product_id"], state=LotStatus.IN_STORAGE
        )
        # Half the seeded reservations are released; only the active half may count.
        assert result.reserved == ACTIVE_RESERVED
        assert result.reserved != RESERVATION_ROWS * RESERVATION_QTY


async def test_availability_is_isolated_per_state_at_volume():
    async with seeded_volume() as seeded:
        in_production = await reservation_service.availability(
            db=seeded["session"], product_id=seeded["product_id"], state=LotStatus.IN_PRODUCTION
        )

        assert in_production.on_hand == ON_HAND_IN_PRODUCTION
        assert in_production.reserved == 0


async def test_list_alerts_totals_match_an_independent_sum():
    """`list_alerts` groups over the whole table with no WHERE clause.

    Its per-product total is checked against a separately computed SUM rather than against a
    constant, so the assertion holds whatever else is already seeded in the database.
    """
    async with seeded_volume() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        await inventory_service.create_alert(
            db=session,
            data=LowStockAlertCreate(product_id=product_id, threshold=10),
            user_id=seeded["user_id"],
        )

        expected = await session.scalar(
            text("SELECT SUM(quantity_on_hand) FROM inventory_lots WHERE product_id = :pid"),
            {"pid": product_id},
        )
        result = await inventory_service.list_alerts(db=session)
        mine = [a for a in result.alerts if a.product_id == product_id]

        assert len(mine) == 1
        assert mine[0].current_quantity == expected
        assert mine[0].is_triggered is False  # 500 lots of stock is far above a threshold of 10

        await session.execute(
            text("DELETE FROM low_stock_alerts WHERE product_id = :pid"), {"pid": product_id}
        )
        await session.commit()


async def test_list_inventory_pages_without_gap_or_duplicate_at_volume():
    """Pagination stability — the `order_by(id)` total order at `inventory_service.py:43-48`.

    Without a total order PostgreSQL may return rows in a different order per page request, so
    paging past page 1 can show a row twice and skip another. That is silent data loss, and it only
    becomes reachable once the table outgrows one page — which is precisely this fixture.
    """
    async with seeded_volume() as seeded:
        session = seeded["session"]

        page_1 = await inventory_service.list_inventory(db=session, page=1, page_size=100)
        page_2 = await inventory_service.list_inventory(db=session, page=2, page_size=100)

        ids_1 = [lot.id for lot in page_1.results]
        ids_2 = [lot.id for lot in page_2.results]

        assert len(ids_1) == 100
        assert len(ids_2) == 100
        assert not set(ids_1) & set(ids_2), "a lot appeared on two pages"
        assert ids_1 == sorted(ids_1)
        assert max(ids_1) < min(ids_2), "pages must not interleave"
        assert page_1.total == page_2.total >= SEED_LOTS


async def test_export_csv_emits_every_lot_exactly_once():
    """`export_csv` is unpaginated — it fetches the whole table into memory.

    Asserted here so the row count is pinned, and flagged in the A8-6 writeup as an availability
    risk that grows linearly with the table.
    """
    async with seeded_volume() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        csv_text = await inventory_service.export_csv(db=session)
        lines = [line for line in csv_text.splitlines() if line.strip()]

        assert lines[0].startswith("id,product_name,lot_number,status")

        total = await session.scalar(text("SELECT count(*) FROM inventory_lots"))
        assert len(lines) - 1 == total, "every lot must appear exactly once"

        mine = [line for line in lines if f"{TAG}-" in line]
        assert len(mine) == SEED_LOTS


# ── The negative control — is the index used, or merely present? ──────────────


async def test_index_is_used_not_merely_present():
    """Drop the index inside a transaction, prove the plan degrades, then roll back.

    This is the assertion that turns "we created an index" into "the optimiser chose it". DDL is
    transactional in PostgreSQL, so the rollback restores the index and the schema is untouched —
    verified explicitly at the end rather than assumed.

    Skipped when the index is absent, so the file is honest on a checkout where migration 015 has
    not been applied instead of failing for an unrelated reason.
    """
    async with seeded_volume() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        if not await _index_exists(session):
            pytest.skip(f"{INDEX_NAME} not present — migration 015 not applied on this database")

        with_index = await _explain(session, product_id)
        assert "Seq Scan on inventory_lots" not in with_index, (
            f"the index exists but the planner ignored it:\n{with_index}"
        )

        await session.execute(text(f"DROP INDEX {INDEX_NAME}"))
        await session.execute(text("ANALYZE inventory_lots"))
        without_index = await _explain(session, product_id)
        await session.rollback()

        assert "Seq Scan on inventory_lots" in without_index, (
            "dropping the index did not degrade the plan, so the index was never what made it "
            f"fast:\n{without_index}"
        )
        assert await _index_exists(session), "rollback must restore the index"


async def test_bench_teardown_restores_the_migrations_index():
    """The benchmark must give the database back exactly as it found it.

    `aggregation_bench` deliberately reuses migration 015's index *name* — measuring a lookalike
    would not be measuring the real thing — which means its without-index arm drops an index the
    schema is supposed to have. An earlier version of the script dropped it and never put it back,
    so a full `scripts/validation-run.sh` pass (migrate, then benchmark) ended with the mitigation
    silently missing and the negative control above quietly skipping.

    This asserts the round trip on the real database rather than trusting the code to be careful.
    """
    engine = create_async_engine(DATABASE_URL)
    try:
        async with AsyncSession(engine) as session:
            if not await _index_exists(session):
                pytest.skip(f"{INDEX_NAME} not present — migration 015 not applied")
            before = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes"
                    " WHERE tablename = 'inventory_lots' AND indexname = :n"
                ),
                {"n": INDEX_NAME},
            )

            captured = await bench_module._existing_index_ddl(session)
            assert captured == before, "capture must record the definition verbatim"

            # Stand in for the without-index arm, then tear down the way the sweep does.
            await bench_module._set_index(session, None)
            assert not await _index_exists(session), "the arm really does drop it"

            await bench_module._teardown(session, captured)

            after = await session.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes"
                    " WHERE tablename = 'inventory_lots' AND indexname = :n"
                ),
                {"n": INDEX_NAME},
            )
            assert after == before, "teardown must restore the index exactly as it was"
    finally:
        await engine.dispose()


async def test_availability_latency_budget_at_volume():
    """RSK-04 — the aggregation stays within budget at volume.

    The 50 ms budget is derived from the A8-6 sweep rather than picked by hand: measured p95 at
    200 000 lots is far below it, and the headroom absorbs a loaded CI runner. If this fails, that
    is the trigger for RSK-04's periodic-snapshot fallback, not a reason to loosen the number.

    Note this is *wall* time and therefore includes a client/server round trip per statement —
    `availability` issues three. On a containerised database that transport cost dominates the
    aggregation itself, which is why the index decision was made on the server-side execution time
    the benchmark captures from EXPLAIN, not on this figure.
    """
    async with seeded_volume() as seeded:
        session, product_id = seeded["session"], seeded["product_id"]

        timings_ms = []
        for _ in range(LATENCY_SAMPLES):
            start = time.perf_counter()
            await reservation_service.availability(
                db=session, product_id=product_id, state=LotStatus.IN_STORAGE
            )
            timings_ms.append((time.perf_counter() - start) * 1000)

        pct = percentiles(timings_ms, (50, 95))
        print(
            f"\navailability latency over {SEED_LOTS} lots + {RESERVATION_ROWS} reservations: "
            f"p50 {pct[50]:.1f}ms, p95 {pct[95]:.1f}ms (budget {LATENCY_BUDGET_MS:.0f}ms)"
        )

        assert pct[95] < LATENCY_BUDGET_MS, (
            f"p95 {pct[95]:.1f}ms exceeded {LATENCY_BUDGET_MS:.0f}ms budget"
        )
