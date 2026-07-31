"""ACRA MES — comparative concurrency study (A8-5).

ISS-06 records three divergent stock-drawdown implementations coexisting in this repo. This script
measures them against each other for **correctness first, throughput second**.

    unguarded            read-modify-write, no lock, no version predicate
                         — `inventory_service.adjust_quantity`, `shipment_service.create_shipment`
    optimistic           ADR-02: row lock + `UPDATE ... WHERE version = :expected` + ascending-id
                         lot locks — `production_worksheet_service.close_worksheet`, called for real
    serializable         `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` + `FOR UPDATE`, no version
                         guard — `allocation_service.allocate_materials`
    serializable-retry   the same, wrapped in a bounded retry on SQLSTATE 40001

**Why the arms share one workload.** The three shapes live on three different domain operations —
adjusting a lot, closing a worksheet, allocating work-order materials. Benchmarked as they sit,
the comparison would measure how much work each endpoint does rather than how each concurrency
control behaves. So the workload is fixed — *N concurrent closers drawing stock from one product* —
and only the control varies. `optimistic` is the production function called directly; the other two
are minimal faithful reductions of shapes that demonstrably exist in the tree, and `unguarded` is
the same shape TC-02 already carries as its negative control.

**Why the closers hold distinct worksheets.** N closers racing for the *same* worksheet is a
double-close test: the version guard means exactly one can win by construction, so arms 2 and 3
would post one success and N-1 instant conflicts and the throughput column would measure nothing.
Distinct worksheets over shared lots gives every closer real work while still contending on the
same rows — and it is where a lost update becomes visible as wrong on-hand.

Usage (needs a **scratch** database — this seeds and deletes):
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5441/acra_db \\
        PYTHONPATH=backend python scripts/validation/concurrency_bench.py [OUT_DIR] \\
        [--arms ...] [--levels 2,4,8,16,32] [--rounds 3]

Exit code is 0 for a completed sweep **even when an arm loses updates** — a lost update is the
finding this script exists to produce, not a failure to run it. Non-zero only if the sweep could
not be carried out.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.benchmark import BenchmarkRun, Outcome, RunMetadata
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import WorksheetCloseLine, WorksheetCloseRequest
from app.services.production_worksheet_service import close_worksheet

ARMS = ("unguarded", "optimistic", "serializable", "serializable-retry")
DEFAULT_LEVELS = (2, 4, 8, 16, 32)
# PostgreSQL's serialization-failure SQLSTATE. SERIALIZABLE aborts the losers with this.
SQLSTATE_SERIALIZATION_FAILURE = "40001"
MAX_RETRIES = 5

_USER = TokenUser(
    user_id=0,  # replaced per scenario with the real seeded id
    full_name="A8-5 Bench Runner",
    roles=["company_admin"],
    preferred_language="en",
    effective_privileges=["production.worksheet.close"],
)


# ---------------------------------------------------------------------------
# Scenario setup — lifted from tests/integration/test_worksheet_close_concurrency.py so the study
# and the TC-02 proof stay on one fixture shape.
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Ids of the rows one round owns, so teardown removes exactly those."""

    user_id: int
    product_id: int
    lot_ids: list[int] = field(default_factory=list)
    worksheet_ids: list[int] = field(default_factory=list)
    line_ids: list[int] = field(default_factory=list)

    def user(self) -> TokenUser:
        return _USER.model_copy(update={"user_id": self.user_id})


async def _seed(sessionmaker_, *, stock: int, worksheets: int, planned: int) -> Scenario:
    """One product, one abundant lot, and `worksheets` single-line worksheets over it."""
    async with sessionmaker_() as db:
        tag = uuid.uuid4().hex[:12]
        user_id = await db.scalar(
            text(
                "INSERT INTO users (username, password_hash, full_name, preferred_language, status)"
                " VALUES (:u, 'x', 'A8-5 Bench Runner', 'en', 'active') RETURNING id"
            ),
            {"u": f"a85_{tag}"},
        )
        product_id = await db.scalar(
            text("INSERT INTO products (name, category) VALUES (:n, 'raw') RETURNING id"),
            {"n": f"A8-5 Material {tag}"},
        )
        scenario = Scenario(user_id=user_id, product_id=product_id)

        lot_id = await db.scalar(
            text(
                "INSERT INTO inventory_lots"
                " (product_id, lot_number, storage_location, status, quantity_on_hand)"
                " VALUES (:p, :ln, 'A8-5', 'in_storage', :q) RETURNING id"
            ),
            {"p": product_id, "ln": f"A85-{tag}", "q": stock},
        )
        scenario.lot_ids.append(lot_id)

        for _ in range(worksheets):
            ws_id = await db.scalar(
                text(
                    "INSERT INTO production_worksheets"
                    " (production_line, scheduled_date, status, version, created_by)"
                    " VALUES ('A8-5', '2026-07-31', 'draft', 0, :u) RETURNING id"
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
        for sql, params in (
            ("DELETE FROM inventory_transactions WHERE lot_id = ANY(:ids)", {"ids": scenario.lot_ids}),
            (
                "DELETE FROM audit_logs WHERE entity_type = 'production_worksheet'"
                " AND entity_id = ANY(:ids)",
                {"ids": scenario.worksheet_ids},
            ),
            (
                "DELETE FROM production_worksheet_lines WHERE worksheet_id = ANY(:ids)",
                {"ids": scenario.worksheet_ids},
            ),
            ("DELETE FROM production_worksheets WHERE id = ANY(:ids)", {"ids": scenario.worksheet_ids}),
            ("DELETE FROM inventory_lots WHERE id = ANY(:ids)", {"ids": scenario.lot_ids}),
            ("DELETE FROM products WHERE id = :id", {"id": scenario.product_id}),
            ("DELETE FROM users WHERE id = :id", {"id": scenario.user_id}),
        ):
            await db.execute(text(sql), params)
        await db.commit()


async def _on_hand(sessionmaker_, scenario: Scenario) -> int:
    async with sessionmaker_() as db:
        return await db.scalar(
            text("SELECT COALESCE(SUM(quantity_on_hand), 0) FROM inventory_lots WHERE id = ANY(:ids)"),
            {"ids": scenario.lot_ids},
        )


# ---------------------------------------------------------------------------
# The three arms. Each returns the Outcome of one attempt.
# ---------------------------------------------------------------------------


async def _close_unguarded(db: AsyncSession, scenario: Scenario, index: int, draw: int) -> Outcome:
    """Arm 1 — read-modify-write with no lock and no version predicate.

    The shape of `inventory_service.adjust_quantity:111-148`: read the row, compute the new total
    in Python, write the total back. Two closers that read before either writes both compute from
    the same starting value, and the second write erases the first.
    """
    lot_id = scenario.lot_ids[0]
    quantity = await db.scalar(
        text("SELECT quantity_on_hand FROM inventory_lots WHERE id = :id"), {"id": lot_id}
    )
    if quantity < draw:
        return Outcome.CONFLICT
    await db.execute(
        text("UPDATE inventory_lots SET quantity_on_hand = :q WHERE id = :id"),
        {"q": quantity - draw, "id": lot_id},
    )
    await db.execute(
        text(
            "UPDATE production_worksheets SET status = 'closed', version = version + 1"
            " WHERE id = :id"
        ),
        {"id": scenario.worksheet_ids[index]},
    )
    await db.commit()
    return Outcome.OK


async def _close_optimistic(db: AsyncSession, scenario: Scenario, index: int, draw: int) -> Outcome:
    """Arm 2 — the real `close_worksheet`. Not a reproduction: the shipping code path."""
    request = WorksheetCloseRequest(
        expected_version=0,
        lines=[WorksheetCloseLine(line_id=scenario.line_ids[index], actual_quantity=draw)],
    )
    try:
        await close_worksheet(db, scenario.worksheet_ids[index], request, scenario.user())
        return Outcome.OK
    except HTTPException as exc:
        return Outcome.CONFLICT if exc.status_code == 409 else Outcome.ERROR


async def _close_serializable(
    db: AsyncSession, scenario: Scenario, index: int, draw: int
) -> Outcome:
    """Arm 3 — SERIALIZABLE, the approach ADR-02 rejected.

    The opening `rollback()` mirrors `allocation_service:29`: PostgreSQL only accepts
    `SET TRANSACTION ISOLATION LEVEL` as the first statement of a transaction, and in a real request
    `require_privilege` has already opened one. Without it the SET raises
    `ActiveSQLTransactionError` and every attempt is a 500 — the defect
    `tests/integration/test_allocation_isolation.py` exists to document.
    """
    await db.rollback()
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    try:
        quantity = await db.scalar(
            text("SELECT quantity_on_hand FROM inventory_lots WHERE id = :id FOR UPDATE"),
            {"id": scenario.lot_ids[0]},
        )
        if quantity < draw:
            await db.rollback()
            return Outcome.CONFLICT
        await db.execute(
            text("UPDATE inventory_lots SET quantity_on_hand = :q WHERE id = :id"),
            {"q": quantity - draw, "id": scenario.lot_ids[0]},
        )
        await db.execute(
            text(
                "UPDATE production_worksheets SET status = 'closed', version = version + 1"
                " WHERE id = :id"
            ),
            {"id": scenario.worksheet_ids[index]},
        )
        await db.commit()
        return Outcome.OK
    except DBAPIError as exc:
        await db.rollback()
        if getattr(getattr(exc.orig, "sqlstate", None), "__str__", str)() == (
            SQLSTATE_SERIALIZATION_FAILURE
        ) or SQLSTATE_SERIALIZATION_FAILURE in str(exc.orig):
            return Outcome.SERIALIZATION_FAILURE
        return Outcome.ERROR


@dataclass
class AttemptResult:
    outcome: Outcome
    seconds: float
    retries: int = 0


async def _run_attempt(
    sessionmaker_, arm: str, scenario: Scenario, index: int, draw: int, barrier
) -> AttemptResult:
    """One closer, on its own session and therefore its own connection.

    Sharing a session across closers would serialize them through a single connection and quietly
    delete the race — the same trap `test_worksheet_close_concurrency.py:10-11` warns about.
    """
    await barrier.wait()  # release every closer at the same instant
    retries = 0
    start = time.perf_counter()
    async with sessionmaker_() as db:
        try:
            if arm == "unguarded":
                outcome = await _close_unguarded(db, scenario, index, draw)
            elif arm == "optimistic":
                outcome = await _close_optimistic(db, scenario, index, draw)
            elif arm == "serializable":
                outcome = await _close_serializable(db, scenario, index, draw)
            elif arm == "serializable-retry":
                # ADR-02 rejected SERIALIZABLE because it "needs a retry loop to be usable at all".
                # This arm is that retry loop, so the claim can be measured rather than asserted.
                for attempt in range(MAX_RETRIES):
                    outcome = await _close_serializable(db, scenario, index, draw)
                    if outcome is not Outcome.SERIALIZATION_FAILURE:
                        break
                    retries = attempt + 1
            else:  # pragma: no cover — argparse constrains the choices
                raise ValueError(f"unknown arm {arm!r}")
        except Exception:
            await db.rollback()
            outcome = Outcome.ERROR
    return AttemptResult(outcome, time.perf_counter() - start, retries)


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def _apply_correctness_oracle(
    results: list[AttemptResult], *, final_on_hand: int, stock: int, draw: int
) -> int:
    """Relabel successes whose work vanished, returning how many updates were lost.

    Every attempt that reported OK believes it consumed `draw`. If the books moved by less than the
    successes claim, the difference is other closers' committed work being erased — a lost update.
    Those samples are relabelled so the arm's own report shows it: an arm that reports 100% success
    while the stock is wrong is exactly the failure this study is here to surface.
    """
    successes = sum(1 for r in results if r.outcome is Outcome.OK)
    expected_on_hand = stock - successes * draw
    lost_total = (final_on_hand - expected_on_hand) // draw if draw else 0
    if lost_total <= 0:
        return 0

    remaining = lost_total
    for result in results:
        if remaining == 0:
            break
        if result.outcome is Outcome.OK:
            result.outcome = Outcome.LOST_UPDATE
            remaining -= 1
    return lost_total


async def _run_level(sessionmaker_, arm: str, level: int, args) -> tuple[BenchmarkRun, dict]:
    """One (arm, level) cell: `rounds` rounds of `level` concurrent closers."""
    run = BenchmarkRun(
        f"concurrency-{arm}-{level:02d}",
        arm=arm,
        concurrency=level,
        rounds=args.rounds,
        stock=args.stock,
        draw=args.draw,
    )
    totals = {"lost_updates": 0, "retries": 0, "rounds": 0, "wall_seconds": 0.0}

    for _ in range(args.rounds):
        scenario = await _seed(
            sessionmaker_, stock=args.stock, worksheets=level, planned=args.draw
        )
        try:
            barrier = asyncio.Barrier(level)
            wall_start = time.perf_counter()
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        _run_attempt(sessionmaker_, arm, scenario, i, args.draw, barrier)
                        for i in range(level)
                    ]
                ),
                timeout=args.timeout,
            )
            wall = time.perf_counter() - wall_start
            final = await _on_hand(sessionmaker_, scenario)
            lost = _apply_correctness_oracle(
                results, final_on_hand=final, stock=args.stock, draw=args.draw
            )

            for result in results:
                run.record(result.seconds, result.outcome)
            totals["lost_updates"] += lost
            totals["retries"] += sum(r.retries for r in results)
            totals["rounds"] += 1
            totals["wall_seconds"] += wall
        finally:
            await _teardown(sessionmaker_, scenario)

    return run, totals


def _comparison_lines(rows: list[dict]) -> list[str]:
    """Correctness column first — the fastest arm here is the one that takes no locks."""
    header = (
        f"  {'arm':<20} {'conc':>5} {'lost':>6} {'success':>8} {'retry':>7} "
        f"{'p50ms':>8} {'p95ms':>8} {'goodput':>9} {'attempts':>9}"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for row in rows:
        lines.append(
            f"  {row['arm']:<20} {row['concurrency']:>5} {row['lost_updates']:>6} "
            f"{row['success_rate']:>7.0%} {row['retry_rate']:>6.0%} "
            f"{row['p50_ms']:>8.1f} {row['p95_ms']:>8.1f} "
            f"{row['goodput_ops_s']:>9.1f} {row['throughput_ops_s']:>9.1f}"
        )
    lines += [
        "",
        "  lost     = committed work erased by another closer (correctness; lower is better)",
        "  goodput  = successful closes/second — the honest throughput column",
        "  attempts = all closes/second including aborts, which are nearly free",
    ]
    return lines


async def _sweep(args) -> int:
    engine = create_async_engine(
        args.dsn, pool_size=max(args.levels) + 4, max_overflow=8, pool_pre_ping=True
    )
    sessionmaker_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    out_dir = Path(args.out_dir)
    rows: list[dict] = []
    written: list[Path] = []

    try:
        for arm in args.arms:
            for level in args.levels:
                print(f"== {arm} @ {level} closers ==", flush=True)
                run, totals = await _run_level(sessionmaker_, arm, level, args)
                stats = run.stats
                wall = totals["wall_seconds"]
                attempts = stats["n"]
                successes = sum(1 for o in run.outcomes if o is Outcome.OK)
                row = {
                    "arm": arm,
                    "concurrency": level,
                    "lost_updates": totals["lost_updates"],
                    "retries": totals["retries"],
                    "success_rate": stats.get("success_rate", 1.0),
                    "retry_rate": stats.get("retry_rate", 0.0),
                    "p50_ms": stats["p50_ms"],
                    "p95_ms": stats["p95_ms"],
                    "throughput_ops_s": round(attempts / wall, 2) if wall else 0.0,
                    # Attempts/second flatters an arm that fails fast: bare SERIALIZABLE posts the
                    # best throughput in this study while completing 3% of the work, because an
                    # abort is nearly free. Goodput counts only attempts that actually did the job,
                    # and is the column the writeup should quote.
                    "goodput_ops_s": round(successes / wall, 2) if wall else 0.0,
                }
                rows.append(row)
                print(
                    f"   lost={row['lost_updates']}  success={row['success_rate']:.0%}  "
                    f"retry={row['retry_rate']:.0%}  p50={row['p50_ms']:.1f}ms  "
                    f"{row['goodput_ops_s']:.1f} goodput/s ({row['throughput_ops_s']:.1f} attempts/s)",
                    flush=True,
                )
                written += list(run.write(out_dir))
    finally:
        await engine.dispose()

    # The comparison artifact. Written through RunMetadata so it carries the same provenance header
    # as every per-cell artifact and as scripts/validation-run.sh's own captures.
    meta = RunMetadata.capture(
        arms=",".join(args.arms),
        levels=",".join(str(x) for x in args.levels),
        rounds=args.rounds,
        stock=args.stock,
        draw=args.draw,
    )
    total_lost = sum(r["lost_updates"] for r in rows)
    lines = meta.header_lines(
        "benchmark: concurrency-ablation",
        f"{len(rows)} cells, {total_lost} lost updates",
    )
    lines += ["", "Comparison (correctness first)"] + _comparison_lines(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / "concurrency-ablation.txt"
    txt_path.write_text("\n".join(lines) + "\n")

    json_path = out_dir / "concurrency-ablation.json"
    json_path.write_text(
        json.dumps(
            {"name": "concurrency-ablation", "metadata": asdict(meta), "rows": rows},
            indent=2,
        )
        + "\n"
    )
    written += [json_path, txt_path]

    print("\n".join(["", "== Comparison =="] + _comparison_lines(rows)))
    print(f"\n== Artifacts ({len(written)}) ==")
    for path in written:
        print(f"  {path}")
    return 0


def _parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="ACRA MES comparative concurrency study (A8-5)")
    parser.add_argument("out_dir", nargs="?", default="validation-evidence")
    parser.add_argument("--arms", default=",".join(ARMS), help=f"comma-separated: {', '.join(ARMS)}")
    parser.add_argument("--levels", default=",".join(str(x) for x in DEFAULT_LEVELS))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--stock", type=int, default=1_000_000)
    parser.add_argument("--draw", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args(argv)

    args.arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in args.arms if a not in ARMS]
    if unknown:
        parser.error(f"unknown arm(s): {unknown}; choose from {list(ARMS)}")
    args.levels = [int(x) for x in args.levels.split(",") if x.strip()]
    if not args.dsn:
        parser.error("no database: pass --dsn or export DATABASE_URL")
    # Abundant stock is not a nicety: if the lot can run dry, "insufficient stock" stands in for the
    # guard and a broken arm looks correct. Same reason TC-02 has ABUNDANT_STOCK.
    if args.stock < max(args.levels) * args.draw * args.rounds:
        parser.error("--stock must exceed levels x draw x rounds so no arm can be saved by scarcity")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(f"== A8-5 comparative concurrency study ==\n   arms={args.arms} levels={args.levels}")
    return asyncio.run(_sweep(args))


if __name__ == "__main__":
    sys.exit(main())
