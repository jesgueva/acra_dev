"""ACRA MES — aggregation benchmark at volume (A8-6).

RSK-04 asserts *"ledger on-hand/reserved/available aggregation is slow at data volume"*, mitigated
by *"index by `(item, state)`; keep a periodic-snapshot fallback in reserve if reads degrade."*
Neither half had ever been measured. This script measures both, then hands the decision a number.

Four read paths, each called **through the real service function** rather than through a hand-copied
query, so what is measured is what production runs:

    availability      reservation_service.availability:112 — composes two independent aggregates,
                      _on_hand:43 over inventory_lots and _reserved:59 over stock_reservations
    list-alerts       inventory_service.list_alerts:332 — SUM ... GROUP BY product_id, no WHERE
    list-inventory    inventory_service.list_inventory:70 — COUNT(*) + one LIMIT/OFFSET page
    export-csv        inventory_service.export_csv:418 — the same base query, unpaginated

Two arms — `without-index` and `with-index` — applied as real DDL inside one run, against one
substrate, with `ANALYZE` between. The only variable is the index.

Three methodology traps this script exists to avoid. Each produces a plausible-looking benchmark
that proves nothing, and the first two are why the naive version of this measurement is worthless:

1.  **The seed creates no reservations.** `grep -i reservation backend/scripts/seed_fake_data.py`
    returns nothing: `stock_reservations` is empty at every `--scale`. Benchmarking `availability`
    against seeded data alone compares a sequential scan over N lots against an index scan over an
    *empty table* — which is not the indexed/unindexed asymmetry the ticket is about, and would
    flatter the index enormously. So this script seeds its own reservations, in the same
    `(product_id, state)` distribution as the lots it measures against, with a realistic
    active/released mix.

2.  **Stale planner statistics.** PostgreSQL picks plans from `pg_statistic`, not from row counts.
    Immediately after a bulk insert, and again immediately after `CREATE INDEX`, those statistics
    are stale and autovacuum has not caught up. Measuring straight through yields a "before" and an
    "after" that may differ only because the planner re-analyzed. `ANALYZE` runs after every volume
    change and every DDL change, and the artifact records that it ran.

3.  **Measuring the wrong layer.** Over HTTP every sample also carries routing, RBAC's three
    queries, Pydantic validation and JSON encoding. At these volumes that overhead dominates the
    aggregation under study, and an index that halves the SQL moves the endpoint number by a few
    percent. Measurement is therefore at the **service layer**, against a real `AsyncSession`.
    `scripts/validation/api_latency_bench.py` remains the HTTP-level view.

**Why this generates its own lots instead of driving `seed_fake_data.py --scale N`.** The seed is
the *demo fixture* and costs ~3.3 s per scale unit, so reaching 100 000 lots through it takes over
an hour — a curve nobody will ever reproduce. Volume here is generated with `generate_series` in
seconds, at exact row counts, which is what makes the curve repeatable. The seeded demo data is
still present and still counted: it is the realistic ambient content of the table, reported as
`ambient_lots` in every artifact.

Every row this script creates is tagged `storage_location = 'A86-BENCH'` and torn down afterwards.

Usage (needs a **scratch** database — this writes tens of thousands of rows and creates/drops an
index; never point it at anything you care about):

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5445/acra_db \\
        PYTHONPATH=backend python scripts/validation/aggregation_bench.py [OUT_DIR] \\
        [--lot-steps 1000,10000,50000,200000] [--samples 100] [--index-variant covering]

Exit code 0 for a completed sweep **even when the index turns out not to help** — that is the
finding this script exists to produce, not a failure to run it. Non-zero only if the sweep could
not be carried out.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.benchmark import BenchmarkRun, RunMetadata
from app.models.inventory import LotStatus
from app.services import inventory_service, reservation_service

PATHS = ("availability", "list-alerts", "list-inventory", "export-csv")
ARMS = ("without-index", "with-index")
DEFAULT_LOT_STEPS = (1_000, 10_000, 50_000, 200_000)
DEFAULT_SAMPLES = 100
WARMUP = 5  # matches api_latency_bench.py, so the two tools' percentiles are comparable
#: Wall-clock ceiling per (path, volume, arm) cell — see `sample_budget`.
DEFAULT_CELL_BUDGET_S = 20.0
MIN_SAMPLES = 5

#: Tag on every row this script creates, so teardown removes exactly its own and nothing else.
BENCH_TAG = "A86-BENCH"

INDEX_NAME = "ix_inventory_lots_item_state"

#: The candidates from the plan's §5.1. They disagree about which path they help, which is the
#: point: `list_alerts` has no WHERE clause, so a plain (product_id, status) index does nothing for
#: it, while a covering index can serve its GROUP BY as an index-only scan.
INDEX_VARIANTS = {
    "plain": f"CREATE INDEX {INDEX_NAME} ON inventory_lots (product_id, status)",
    "covering": (
        f"CREATE INDEX {INDEX_NAME} ON inventory_lots (product_id, status)"
        " INCLUDE (quantity_on_hand)"
    ),
    "product-only": f"CREATE INDEX {INDEX_NAME} ON inventory_lots (product_id)",
}

# One active + one released reservation per this many bench lots. Released rows are seeded
# deliberately: `_reserved` filters `status = 'active'`, and an index that cannot discriminate
# would look correct against an all-active table.
LOTS_PER_RESERVATION = 4

_SCAN_PATTERNS = (
    ("index-only", re.compile(r"Index Only Scan", re.I)),
    ("index", re.compile(r"(Bitmap )?Index Scan", re.I)),
    ("seq", re.compile(r"Seq Scan", re.I)),
)

_EXECUTION_TIME = re.compile(r"^\s*Execution Time:\s*([0-9.]+)\s*ms", re.I | re.M)


# ---------------------------------------------------------------------------
# Pure helpers — no database, unit-tested in backend/tests/test_aggregation_bench.py
# ---------------------------------------------------------------------------


def scan_kind(explain_text: str, table: str) -> str:
    """Classify how `table` was reached in an EXPLAIN plan.

    Returns `index-only`, `index`, `seq`, or `none` when the table does not appear at all.

    Only lines naming the table count, because a plan for `availability` touches `products` and
    `inventory_lots` in the same output and a bare "is there a Seq Scan anywhere" check would
    report the wrong node. `Index Only` is tested before `Index`, and `Index` before `Seq`, since
    an index-only scan line contains neither of the weaker spellings but a bitmap plan mentions
    both an index node and a heap node.
    """
    relevant = [line for line in explain_text.splitlines() if table in line]
    if not relevant:
        return "none"
    blob = "\n".join(relevant)
    for label, pattern in _SCAN_PATTERNS:
        if pattern.search(blob):
            return label
    return "none"


def dominant_scan(
    plans: Sequence[str], timings: Sequence[float | None], table: str
) -> str:
    """One scan verdict for a path that issued several statements against `table`.

    A path is only as indexed as its worst statement: `list_inventory` runs an unfiltered
    `COUNT(*)` and a paginated fetch, and reporting "index-only" because the cheaper half used an
    index would hide the sequential scan that dominates the cost. So a `seq` anywhere wins the
    label. Failing that, the plan that actually cost the most time is the one reported, and
    untimed plans fall back to the first classification seen.
    """
    kinds = [scan_kind(p, table) for p in plans]
    present = [k for k in kinds if k != "none"]
    if not present:
        return "none"
    if "seq" in present:
        return "seq"
    timed = [(t, k) for t, k in zip(timings, kinds) if t is not None and k != "none"]
    if timed:
        return max(timed, key=lambda pair: pair[0])[1]
    return present[0]


def parse_execution_ms(explain_text: str) -> float | None:
    """The server-side `Execution Time` from an `EXPLAIN ANALYZE` plan, in ms.

    This is the number the index decision actually turns on. Service-layer wall time includes a
    client/server round trip per statement, and against a containerised PostgreSQL that transport
    cost is milliseconds while these aggregates are microseconds — so wall time can move in the
    *opposite* direction to the query it is supposed to be measuring, purely on scheduling noise.
    Reported alongside wall time, never instead of it: the round trip is real latency a caller
    pays, it just is not what an index can fix.

    Returns None when the plan carries no timing (an `EXPLAIN` without `ANALYZE`).
    """
    match = _EXECUTION_TIME.search(explain_text or "")
    return float(match.group(1)) if match else None


def plan_reservation_count(lot_count: int, lots_per_reservation: int = LOTS_PER_RESERVATION) -> int:
    """How many reservation rows to seed alongside `lot_count` lots (trap 1).

    Always at least one once there are any lots: a zero here is the empty-table comparison this
    whole function exists to prevent.
    """
    if lot_count <= 0:
        return 0
    return max(1, lot_count // max(1, lots_per_reservation))


def sample_budget(
    warmup_seconds: float, requested: int, budget_seconds: float, minimum: int = MIN_SAMPLES
) -> int:
    """How many samples to actually take, given how slow one warm-up call turned out to be.

    `export_csv` is unpaginated: at 200 000 lots one call materialises every row, so the requested
    100 samples would run for hours while the cheap paths finish in seconds. Rather than silently
    dropping the expensive path — or capping every path to the slowest one's budget — each cell
    takes as many samples as fit its time budget, never fewer than `minimum`.

    This is safe to report because `BenchmarkRun.stats` always publishes `n`: a percentile over 8
    samples is visibly a percentile over 8 samples, not a p99 dressed up as one.
    """
    if warmup_seconds <= 0:
        return requested
    affordable = int(budget_seconds / warmup_seconds)
    return max(minimum, min(requested, affordable))


def artifact_name(path: str, lots: int, arm: str) -> str:
    """Stable artifact basename. A change here silently orphans previously published evidence."""
    return f"aggregation-{path}-lots{lots}-{arm}"


def assemble_curve(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group measured cells into one ascending latency curve per `path/arm`.

    Raises ValueError on a missing or duplicated cell rather than silently emitting a short curve —
    a curve with a hole in it reads as a completed sweep and is the easiest way to publish a wrong
    conclusion.
    """
    paths = sorted({r["path"] for r in rows})
    arms = sorted({r["arm"] for r in rows})
    steps = sorted({r["lots"] for r in rows})

    curve: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        for arm in arms:
            cells = [r for r in rows if r["path"] == path and r["arm"] == arm]
            seen = sorted(c["lots"] for c in cells)
            if seen != steps:
                missing = [s for s in steps if s not in seen]
                dupes = [s for s in set(seen) if seen.count(s) > 1]
                raise ValueError(
                    f"incomplete curve for {path}/{arm}: missing={missing} duplicated={dupes}"
                )
            curve[f"{path}/{arm}"] = sorted(cells, key=lambda c: c["lots"])
    return curve


def speedup_rows(curve: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """`without-index` vs `with-index` per (path, volume), as a ratio of p95s.

    A ratio > 1 means the index helped. Reported per path because the paths genuinely disagree —
    forcing one verdict across all four would hide that.
    """
    out: list[dict[str, Any]] = []
    for key, cells in sorted(curve.items()):
        path, arm = key.rsplit("/", 1)
        if arm != "without-index":
            continue
        indexed = curve.get(f"{path}/with-index")
        if not indexed:
            continue
        for base, withidx in zip(cells, indexed):
            sql_without = base.get("sql_execution_ms")
            sql_with = withidx.get("sql_execution_ms")
            out.append(
                {
                    "path": path,
                    "lots": base["lots"],
                    "p95_without_ms": base["p95_ms"],
                    "p95_with_ms": withidx["p95_ms"],
                    "speedup": round(base["p95_ms"] / withidx["p95_ms"], 2)
                    if withidx["p95_ms"]
                    else None,
                    "sql_without_ms": sql_without,
                    "sql_with_ms": sql_with,
                    # The decision column. Wall-clock speedup is diluted by a per-statement round
                    # trip that no index can remove; this ratio is the aggregation alone.
                    "sql_speedup": round(sql_without / sql_with, 2)
                    if sql_without is not None and sql_with
                    else None,
                    "scan_without": base["scan"],
                    "scan_with": withidx["scan"],
                }
            )
    return out


def comparison_lines(rows: Sequence[dict[str, Any]]) -> list[str]:
    """The human-readable comparison table for the `.txt` artifact."""
    header = (
        f"  {'path':<15} {'lots':>8} {'sql no-idx':>11} {'sql idx':>10} {'sql x':>7} "
        f"{'p95 wall':>9} {'wall x':>7}  {'scan (no-idx -> idx)'}"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for r in rows:
        def _ms(value: float | None) -> str:
            return f"{value:.3f}" if value is not None else "n/a"

        def _x(value: float | None) -> str:
            return f"{value:.2f}x" if value is not None else "n/a"

        lines.append(
            f"  {r['path']:<15} {r['lots']:>8} {_ms(r['sql_without_ms']):>11} "
            f"{_ms(r['sql_with_ms']):>10} {_x(r['sql_speedup']):>7} "
            f"{r['p95_with_ms']:>8.2f}m {_x(r['speedup']):>7}  "
            f"{r['scan_without']} -> {r['scan_with']}"
        )
    return lines


# ---------------------------------------------------------------------------
# SQL capture — EXPLAIN the statement the service really ran
# ---------------------------------------------------------------------------


@dataclass
class Captured:
    statement: str
    parameters: tuple[Any, ...]


class SQLCapture:
    """Records every statement a service function executes, with its bound parameters.

    Mirroring each service's SQL by hand into this script would be the obvious approach and is a
    drift trap: the copy stays convincing long after the service has changed, and the published
    plan then describes a query that no longer runs. Hooking the engine means the EXPLAIN below is
    of the exact statement the service issued, with the exact parameters, by construction.
    """

    def __init__(self, engine) -> None:
        self._sync_engine = engine.sync_engine
        self.statements: list[Captured] = []
        self._active = False

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if self._active:
            self.statements.append(Captured(statement, tuple(parameters or ())))

    def __enter__(self) -> SQLCapture:
        self.statements = []
        self._active = True
        event.listen(self._sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc: object) -> None:
        self._active = False
        event.remove(self._sync_engine, "before_cursor_execute", self._on_execute)

    def touching(self, table: str) -> list[Captured]:
        """Captured statements that reference `table`, ignoring the transaction bookkeeping."""
        return [c for c in self.statements if table in c.statement]


async def _explain(db: AsyncSession, captured: Captured) -> str:
    """`EXPLAIN (ANALYZE, BUFFERS)` one captured statement, through the raw asyncpg connection.

    The raw connection is used because the captured statement already carries asyncpg's positional
    `$1` placeholders and its parameters as a tuple; handing that back to SQLAlchemy would mean
    re-parsing text it already compiled.
    """
    conn = await db.connection()
    raw = await conn.get_raw_connection()
    driver = raw.driver_connection
    sql = f"EXPLAIN (ANALYZE, BUFFERS) {captured.statement}"
    rows = await driver.fetch(sql, *captured.parameters)
    return "\n".join(r[0] for r in rows)


# ---------------------------------------------------------------------------
# Substrate — volume, reservations, statistics, DDL
# ---------------------------------------------------------------------------


async def _scalar(db: AsyncSession, sql: str, **params: Any) -> Any:
    return await db.scalar(text(sql), params)


async def _bench_product_ids(db: AsyncSession, count: int) -> list[int]:
    """Products the bench lots spread across, created once and reused."""
    ids: list[int] = []
    for i in range(count):
        name = f"{BENCH_TAG} Material {i:03d}"
        pid = await _scalar(db, "SELECT id FROM products WHERE name = :n", n=name)
        if pid is None:
            pid = await _scalar(
                db,
                "INSERT INTO products (name, category) VALUES (:n, 'raw') RETURNING id",
                n=name,
            )
        ids.append(pid)
    return ids


async def _bench_user_id(db: AsyncSession) -> int:
    username = f"{BENCH_TAG.lower()}_runner"
    uid = await _scalar(db, "SELECT id FROM users WHERE username = :u", u=username)
    if uid is None:
        uid = await _scalar(
            db,
            "INSERT INTO users (username, password_hash, full_name, preferred_language, status)"
            " VALUES (:u, 'x', 'A8-6 Bench Runner', 'en', 'active') RETURNING id",
            u=username,
        )
    return uid


async def _grow_to(
    db: AsyncSession, product_ids: Sequence[int], user_id: int, target_lots: int
) -> tuple[int, int]:
    """Grow the bench's own lots (and matching reservations) to `target_lots`.

    Monotonic: each step tops up rather than rebuilding, so the sweep visits ascending volumes on
    one substrate and the steps stay comparable. Returns `(lots, reservations)` actually present.
    """
    current = await _scalar(
        db, "SELECT count(*) FROM inventory_lots WHERE storage_location = :t", t=BENCH_TAG
    )
    to_add = target_lots - (current or 0)
    if to_add > 0:
        # One statement per step. A per-row INSERT at 200 000 rows would dominate the runtime of
        # the benchmark itself and tell us nothing about the read path.
        await db.execute(
            text(
                "INSERT INTO inventory_lots"
                " (product_id, lot_number, storage_location, status, quantity_on_hand)"
                # CAST(...) rather than `:pids::int[]`: SQLAlchemy's text() reads `:` as the start
                # of a bind parameter, so the PostgreSQL `::` cast operator has to be spelled out.
                " SELECT (CAST(:pids AS int[]))[1 + (g % :np)],"
                "        :tag || '-' || g,"
                "        :tag,"
                # A tenth of the lots sit in another state so the status predicate has something
                # to discriminate; an all-in_storage table makes the composite index look pointless.
                "        CASE WHEN g % 10 = 0 THEN 'in_production' ELSE 'in_storage' END,"
                "        500"
                # Explicit casts: asyncpg sends parameters untyped, and generate_series is
                # overloaded, so PostgreSQL cannot pick a candidate without them.
                " FROM generate_series(CAST(:lo AS bigint), CAST(:hi AS bigint)) g"
            ),
            {
                "pids": list(product_ids),
                "np": len(product_ids),
                "tag": BENCH_TAG,
                "lo": (current or 0) + 1,
                "hi": target_lots,
            },
        )

    # Trap 1 — reservations in the same (product, state) distribution, half of them released.
    want_reservations = plan_reservation_count(target_lots)
    have = await _scalar(
        db,
        "SELECT count(*) FROM stock_reservations WHERE production_worksheet_line_id = :m",
        m=-86,
    )
    if want_reservations > (have or 0):
        await db.execute(
            text(
                "INSERT INTO stock_reservations"
                " (product_id, state, quantity, production_worksheet_line_id, status, created_by)"
                " SELECT (CAST(:pids AS int[]))[1 + (g % :np)],"
                "        'in_storage',"
                "        10,"
                "        -86,"
                "        CASE WHEN g % 2 = 0 THEN 'active' ELSE 'released' END,"
                "        :uid"
                # Explicit casts: asyncpg sends parameters untyped, and generate_series is
                # overloaded, so PostgreSQL cannot pick a candidate without them.
                " FROM generate_series(CAST(:lo AS bigint), CAST(:hi AS bigint)) g"
            ),
            {
                "pids": list(product_ids),
                "np": len(product_ids),
                "uid": user_id,
                "lo": (have or 0) + 1,
                "hi": want_reservations,
            },
        )
    await db.commit()

    lots = await _scalar(
        db, "SELECT count(*) FROM inventory_lots WHERE storage_location = :t", t=BENCH_TAG
    )
    reservations = await _scalar(
        db, "SELECT count(*) FROM stock_reservations WHERE production_worksheet_line_id = :m", m=-86
    )
    return lots or 0, reservations or 0


async def _analyze(db: AsyncSession) -> None:
    """Trap 2 — refresh planner statistics. Must follow every volume change and every DDL change."""
    await db.execute(text("ANALYZE inventory_lots, stock_reservations"))
    await db.commit()


async def _existing_index_ddl(db: AsyncSession) -> str | None:
    """The `CREATE INDEX` statement for `INDEX_NAME` as it exists right now, or None.

    Captured before the sweep touches anything so teardown can put the database back exactly as it
    was found. Reading the definition out of `pg_indexes` rather than assuming it means the restore
    is correct whatever created it — migration 015, a hand-rolled variant, or a future revision that
    changes the column list.
    """
    return await db.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'inventory_lots' AND indexname = :n"),
        {"n": INDEX_NAME},
    )


async def _set_index(db: AsyncSession, ddl: str | None) -> None:
    await db.execute(text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
    if ddl:
        await db.execute(text(ddl))
    await db.commit()


async def _teardown(db: AsyncSession, original_index_ddl: str | None) -> None:
    """Remove every row this script created and restore the index to how it was found.

    The restore is load-bearing. `INDEX_NAME` is deliberately the *same* name migration 015 uses —
    the point of the with-index arm is to measure the real index, not a lookalike — which means the
    without-index arm drops an index the schema is supposed to have. Ending the run without putting
    it back would leave a normally-migrated database silently missing RSK-04's mitigation, and
    `scripts/validation-run.sh` runs migrations and then this script, so that would be the routine
    outcome rather than an edge case.
    """
    await db.execute(
        text("DELETE FROM stock_reservations WHERE production_worksheet_line_id = :m"), {"m": -86}
    )
    await db.execute(
        text("DELETE FROM inventory_lots WHERE storage_location = :t"), {"t": BENCH_TAG}
    )
    await db.execute(text("DELETE FROM products WHERE name LIKE :p"), {"p": f"{BENCH_TAG} Material%"})
    await db.execute(text("DELETE FROM users WHERE username = :u"), {"u": f"{BENCH_TAG.lower()}_runner"})
    await _set_index(db, original_index_ddl)
    await db.commit()


# ---------------------------------------------------------------------------
# The four measured paths
# ---------------------------------------------------------------------------


async def _call(path: str, db: AsyncSession, product_id: int) -> None:
    """Invoke one read path through its real service function."""
    if path == "availability":
        await reservation_service.availability(db, product_id, LotStatus.IN_STORAGE)
    elif path == "list-alerts":
        await inventory_service.list_alerts(db)
    elif path == "list-inventory":
        await inventory_service.list_inventory(db, page=1, page_size=50)
    elif path == "export-csv":
        await inventory_service.export_csv(db)
    else:  # pragma: no cover — guarded by argparse choices
        raise ValueError(f"unknown path {path}")


async def _measure(
    sessionmaker_: async_sessionmaker[AsyncSession],
    engine,
    path: str,
    product_id: int,
    lots: int,
    arm: str,
    samples: int,
    cell_budget_s: float,
) -> tuple[BenchmarkRun, str, str, float | None]:
    """Time one (path, volume, arm) cell and capture the EXPLAIN plan for its lot aggregate."""
    async with sessionmaker_() as db:
        warm_start = time.perf_counter()
        for _ in range(WARMUP):
            await _call(path, db, product_id)
        per_call = (time.perf_counter() - warm_start) / WARMUP

        planned = sample_budget(per_call, samples, cell_budget_s)
        run = BenchmarkRun(
            artifact_name(path, lots, arm),
            path=path,
            arm=arm,
            bench_lots=lots,
            samples=planned,
            samples_requested=samples,
            cell_budget_s=cell_budget_s,
            warmup=WARMUP,
            layer="service",
        )

        for _ in range(planned):
            with run.time():
                await _call(path, db, product_id)

        # Plans for **every** statement the service issued against inventory_lots, not just the
        # first. `list_inventory` issues two — the COUNT(*) and the LIMIT/OFFSET page — and taking
        # only [0] published the COUNT's plan while the docstring claimed the page was measured.
        with SQLCapture(engine) as capture:
            await _call(path, db, product_id)

        plans: list[str] = []
        for statement in capture.touching("inventory_lots"):
            plans.append(await _explain(db, statement))

    plan = "\n\n".join(
        f"-- statement {i + 1} of {len(plans)}\n{p}" for i, p in enumerate(plans)
    )
    # Server-side cost of the whole path against this table, so a two-statement path is not
    # reported as though it only ran its cheaper half.
    timings = [parse_execution_ms(p) for p in plans]
    measured = [t for t in timings if t is not None]
    exec_ms = round(sum(measured), 3) if measured else None
    scan = dominant_scan(plans, timings, "inventory_lots")

    return run, plan, scan, exec_ms


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


async def _sweep(args: argparse.Namespace) -> int:
    engine = create_async_engine(args.dsn, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(engine, expire_on_commit=False)
    out_dir = Path(args.out_dir)
    rows: list[dict[str, Any]] = []
    plans: dict[str, str] = {}
    written: list[Path] = []
    ambient_lots = 0

    original_index_ddl: str | None = None

    try:
        async with sessionmaker_() as db:
            ambient_lots = await _scalar(
                db,
                "SELECT count(*) FROM inventory_lots WHERE storage_location IS DISTINCT FROM :t",
                t=BENCH_TAG,
            )
            # Captured before anything is touched, so teardown can restore exactly what was here.
            original_index_ddl = await _existing_index_ddl(db)
            product_ids = await _bench_product_ids(db, args.products)
            user_id = await _bench_user_id(db)
            await db.commit()

        print(f"== ambient lots already in table: {ambient_lots} ==", flush=True)
        print(
            f"== {INDEX_NAME}: {'present, will be restored' if original_index_ddl else 'absent'} ==",
            flush=True,
        )

        for lots_target in args.lot_steps:
            async with sessionmaker_() as db:
                lots, reservations = await _grow_to(db, product_ids, user_id, lots_target)
                await _analyze(db)
            print(
                f"\n== volume: {lots} bench lots (+{ambient_lots} ambient), "
                f"{reservations} reservations ==",
                flush=True,
            )

            for arm in args.arms:
                ddl = INDEX_VARIANTS[args.index_variant] if arm == "with-index" else None
                async with sessionmaker_() as db:
                    await _set_index(db, ddl)
                    await _analyze(db)  # trap 2 — again, after the DDL

                for path in args.paths:
                    run, plan, scan, exec_ms = await _measure(
                        sessionmaker_,
                        engine,
                        path,
                        product_ids[0],
                        lots,
                        arm,
                        args.samples,
                        args.cell_budget_s,
                    )
                    stats = run.stats
                    rows.append(
                        {
                            "path": path,
                            "arm": arm,
                            "lots": lots,
                            "ambient_lots": ambient_lots,
                            "reservations": reservations,
                            "analyzed": True,
                            "scan": scan,
                            "n": stats["n"],
                            "p50_ms": stats["p50_ms"],
                            "p95_ms": stats["p95_ms"],
                            "p99_ms": stats["p99_ms"],
                            "sql_execution_ms": exec_ms,
                        }
                    )
                    key = f"{path}-{lots}-{arm}"
                    plans[key] = plan
                    written += list(run.write(out_dir))
                    sql = f"{exec_ms:.3f}ms" if exec_ms is not None else "n/a"
                    print(
                        f"   {arm:<14} {path:<15} n={stats['n']:>3} p50={stats['p50_ms']:>8.2f}ms "
                        f"p95={stats['p95_ms']:>8.2f}ms  sql={sql:>10}  scan={scan}",
                        flush=True,
                    )
    finally:
        # Nested, so a teardown failure cannot skip disposal and strand the connection pool.
        try:
            if not args.keep:
                async with sessionmaker_() as db:
                    await _teardown(db, original_index_ddl)
        finally:
            await engine.dispose()

    curve = assemble_curve(rows)
    speedups = speedup_rows(curve)

    meta = RunMetadata.capture(
        paths=",".join(args.paths),
        arms=",".join(args.arms),
        lot_steps=",".join(str(x) for x in args.lot_steps),
        samples=args.samples,
        index_variant=args.index_variant,
        index_ddl=INDEX_VARIANTS[args.index_variant],
        ambient_lots=ambient_lots,
        analyzed_after_every_change=True,
        measurement_layer="service",
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = meta.header_lines(
        "benchmark: aggregation-at-volume",
        f"{len(rows)} cells across {len(args.lot_steps)} volumes",
    )
    lines += ["", "Comparison (p95, service layer)"] + comparison_lines(speedups)
    txt_path = out_dir / "aggregation-bench-summary.txt"
    txt_path.write_text("\n".join(lines) + "\n")

    json_path = out_dir / "aggregation-bench-summary.json"
    json_path.write_text(
        json.dumps(
            {
                "name": "aggregation-bench-summary",
                "metadata": asdict(meta),
                "rows": rows,
                "curve": curve,
                "speedups": speedups,
            },
            indent=2,
        )
        + "\n"
    )

    plans_path = out_dir / "aggregation-explain-plans.txt"
    plan_lines = meta.header_lines("EXPLAIN (ANALYZE, BUFFERS) plans", f"{len(plans)} plans")
    for key, plan in plans.items():
        plan_lines += ["", f"### {key}", plan]
    plans_path.write_text("\n".join(plan_lines) + "\n")

    written += [json_path, txt_path, plans_path]

    print("\n".join(["", "== Comparison =="] + comparison_lines(speedups)))
    print(f"\n== Artifacts ({len(written)}) ==")
    for path in written:
        print(f"  {path}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACRA MES aggregation benchmark at volume (A8-6)")
    parser.add_argument("out_dir", nargs="?", default="validation-evidence")
    parser.add_argument(
        "--lot-steps",
        default=",".join(str(x) for x in DEFAULT_LOT_STEPS),
        help="ascending bench-lot counts to measure at",
    )
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument(
        "--cell-budget-s",
        type=float,
        default=DEFAULT_CELL_BUDGET_S,
        help="wall-clock ceiling per cell; slow paths take fewer samples (n is reported)",
    )
    parser.add_argument("--paths", default=",".join(PATHS))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument(
        "--index-variant",
        default="covering",
        choices=sorted(INDEX_VARIANTS),
        help="which candidate index the with-index arm creates",
    )
    parser.add_argument("--products", type=int, default=20, help="products the bench lots spread over")
    parser.add_argument("--keep", action="store_true", help="skip teardown (for manual inspection)")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args(argv)

    args.paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    unknown = [p for p in args.paths if p not in PATHS]
    if unknown:
        parser.error(f"unknown path(s): {unknown}; choose from {list(PATHS)}")

    args.arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown_arms = [a for a in args.arms if a not in ARMS]
    if unknown_arms:
        parser.error(f"unknown arm(s): {unknown_arms}; choose from {list(ARMS)}")

    args.lot_steps = [int(x) for x in args.lot_steps.split(",") if x.strip()]
    if not args.lot_steps:
        parser.error("--lot-steps needs at least one volume")
    if args.lot_steps != sorted(args.lot_steps):
        # The substrate grows monotonically between steps; a descending list would silently
        # measure the larger volume twice.
        parser.error("--lot-steps must be ascending")
    if args.samples < 1:
        parser.error("--samples must be >= 1")
    if args.cell_budget_s <= 0:
        parser.error("--cell-budget-s must be > 0")
    if args.products < 1:
        parser.error("--products must be >= 1")
    if not args.dsn:
        parser.error("no database: pass --dsn or export DATABASE_URL")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(
        f"== A8-6 aggregation benchmark ==\n"
        f"   paths={args.paths}\n   volumes={args.lot_steps}\n"
        f"   index={args.index_variant}: {INDEX_VARIANTS[args.index_variant]}"
    )
    return asyncio.run(_sweep(args))


if __name__ == "__main__":
    sys.exit(main())
