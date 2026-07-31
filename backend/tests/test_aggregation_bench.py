"""A8-6 — the aggregation benchmark's pure layer, exercised without a database.

`aggregation_bench` splits "decide what to measure and how to read the result" from "talk to
PostgreSQL". Everything here tests the pure half, which is the half that can silently publish a
wrong conclusion: a plan classifier that reads a bitmap plan as a sequential scan, or a curve
assembler that quietly emits three points where four were measured, produces evidence that looks
complete and is not.

The DB-backed half is covered by `tests/integration/test_aggregation_at_volume.py`.
"""
import importlib.util
import sys
from pathlib import Path

import pytest


def _load_bench_module():
    """Import the runner from the repo-root `scripts/` tree, which is not on the backend path.

    tests/<this file> -> tests -> backend -> repo root.
    """
    path = Path(__file__).resolve().parents[2] / "scripts" / "validation" / "aggregation_bench.py"
    spec = importlib.util.spec_from_file_location("acra_aggregation_bench", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = _load_bench_module()


# ── scan_kind — how the plan is read ──────────────────────────────────────────

SEQ_PLAN = """\
Aggregate (actual time=0.023..0.024 rows=1 loops=1)
  Buffers: shared hit=2
  ->  Seq Scan on inventory_lots (actual time=0.009..0.019 rows=12 loops=1)
        Filter: ((product_id = 1) AND ((status)::text = 'in_storage'::text))
"""

INDEX_PLAN = """\
Aggregate (actual time=0.031..0.032 rows=1 loops=1)
  ->  Index Scan using ix_inventory_lots_item_state on inventory_lots (actual rows=12 loops=1)
        Index Cond: ((product_id = 1) AND ((status)::text = 'in_storage'::text))
"""

INDEX_ONLY_PLAN = """\
Aggregate (actual time=0.018..0.019 rows=1 loops=1)
  ->  Index Only Scan using ix_inventory_lots_item_state on inventory_lots (actual rows=12 loops=1)
        Heap Fetches: 0
"""

BITMAP_PLAN = """\
Aggregate (actual time=1.2..1.2 rows=1 loops=1)
  ->  Bitmap Heap Scan on inventory_lots (actual rows=900 loops=1)
        Recheck Cond: (product_id = 1)
        ->  Bitmap Index Scan on ix_inventory_lots_item_state (actual rows=900 loops=1)
"""


@pytest.mark.parametrize(
    "plan,expected",
    [
        (SEQ_PLAN, "seq"),
        (INDEX_PLAN, "index"),
        (INDEX_ONLY_PLAN, "index-only"),
        (BITMAP_PLAN, "index"),
    ],
)
def test_scan_kind_classifies_each_plan_shape(plan, expected):
    assert bench.scan_kind(plan, "inventory_lots") == expected


def test_bitmap_plan_is_not_read_as_sequential():
    """A bitmap plan names a heap scan and an index scan in the same node.

    Read carelessly ("does the word Scan appear near the table") this classifies as sequential,
    which would report the index as unused at exactly the volumes where the planner starts
    choosing it — turning a working index into a false negative in the writeup.
    """
    assert bench.scan_kind(BITMAP_PLAN, "inventory_lots") != "seq"


def test_scan_kind_ignores_other_tables():
    """`availability` also touches `products`; the classifier must not read that node.

    Without the per-table filter this returns "index" for inventory_lots because the products
    lookup below it uses the primary key — a plan that says the opposite of the truth.
    """
    mixed = """\
Aggregate
  ->  Seq Scan on inventory_lots (actual rows=74 loops=1)
        Filter: (product_id = 1)
  ->  Index Scan using products_pkey on products (actual rows=1 loops=1)
"""
    assert bench.scan_kind(mixed, "inventory_lots") == "seq"
    assert bench.scan_kind(mixed, "products") == "index"


def test_scan_kind_reports_none_for_absent_table():
    assert bench.scan_kind(SEQ_PLAN, "stock_reservations") == "none"
    assert bench.scan_kind("", "inventory_lots") == "none"


# ── parse_execution_ms — isolating the query from the round trip ──────────────

TIMED_PLAN = """\
Aggregate (actual time=0.023..0.024 rows=1 loops=1)
  ->  Seq Scan on inventory_lots (actual time=0.009..0.019 rows=12 loops=1)
Planning Time: 0.107 ms
Execution Time: 0.052 ms
"""


def test_parse_execution_ms_reads_the_server_side_time():
    assert bench.parse_execution_ms(TIMED_PLAN) == 0.052


def test_parse_execution_ms_does_not_return_planning_time():
    """`Planning Time` precedes `Execution Time` and is the larger number here.

    A loose pattern picks up whichever it meets first, which would report planning cost as query
    cost — and planning is exactly what does *not* change with data volume.
    """
    assert bench.parse_execution_ms(TIMED_PLAN) != 0.107


def test_parse_execution_ms_is_none_without_analyze():
    """`EXPLAIN` without `ANALYZE` carries estimates and no timing at all."""
    assert bench.parse_execution_ms(SEQ_PLAN) is None
    assert bench.parse_execution_ms("") is None
    assert bench.parse_execution_ms(None) is None


# ── plan_reservation_count — trap 1 ───────────────────────────────────────────


def test_reservation_count_is_proportional_to_lots():
    assert bench.plan_reservation_count(1_000, lots_per_reservation=4) == 250
    assert bench.plan_reservation_count(200_000, lots_per_reservation=4) == 50_000


def test_reservation_count_is_never_zero_when_lots_exist():
    """Trap 1 — the whole point.

    A zero here means `_reserved` aggregates an empty table while `_on_hand` scans N rows, so the
    "indexed vs unindexed" comparison the ticket is about is really a comparison against nothing.
    """
    assert bench.plan_reservation_count(1) >= 1
    assert bench.plan_reservation_count(3, lots_per_reservation=1000) >= 1


def test_reservation_count_is_zero_only_with_no_lots():
    assert bench.plan_reservation_count(0) == 0
    assert bench.plan_reservation_count(-5) == 0


# ── assemble_curve — a hole must not read as a completed sweep ────────────────


def _cell(path, arm, lots, p95=1.0, sql=None):
    return {
        "path": path,
        "arm": arm,
        "lots": lots,
        "p50_ms": p95 / 2,
        "p95_ms": p95,
        "scan": "seq",
        "sql_execution_ms": sql,
    }


def test_assemble_curve_groups_and_sorts_by_volume():
    rows = [
        _cell("availability", "with-index", 10),
        _cell("availability", "without-index", 100),
        _cell("availability", "without-index", 10),
        _cell("availability", "with-index", 100),
    ]
    curve = bench.assemble_curve(rows)

    assert sorted(curve) == ["availability/with-index", "availability/without-index"]
    assert [c["lots"] for c in curve["availability/without-index"]] == [10, 100]


def test_assemble_curve_rejects_a_missing_cell():
    """A short curve is the easiest way to publish a wrong conclusion — fail loudly instead."""
    rows = [
        _cell("availability", "without-index", 10),
        _cell("availability", "without-index", 100),
        _cell("availability", "with-index", 10),
        # the 100-lot with-index cell never ran
    ]
    with pytest.raises(ValueError, match="incomplete curve"):
        bench.assemble_curve(rows)


def test_assemble_curve_rejects_a_duplicated_cell():
    rows = [
        _cell("availability", "without-index", 10),
        _cell("availability", "without-index", 10),
        _cell("availability", "with-index", 10),
    ]
    with pytest.raises(ValueError, match="incomplete curve"):
        bench.assemble_curve(rows)


# ── speedup_rows — the comparison the decision is made on ─────────────────────


def test_speedup_is_reported_per_path():
    """The four paths genuinely disagree about whether the index helps.

    `list_alerts` has no WHERE clause, so a (product_id, status) index does nothing for it while
    `availability` may benefit greatly. Collapsing them to a single verdict hides that, so the
    comparison is emitted per path.
    """
    rows = [
        _cell("availability", "without-index", 100, p95=40.0),
        _cell("availability", "with-index", 100, p95=4.0),
        _cell("list-alerts", "without-index", 100, p95=20.0),
        _cell("list-alerts", "with-index", 100, p95=20.0),
    ]
    curve = bench.assemble_curve(rows)
    speeds = {r["path"]: r["speedup"] for r in bench.speedup_rows(curve)}

    assert speeds["availability"] == 10.0
    assert speeds["list-alerts"] == 1.0


def test_speedup_survives_a_zero_measurement():
    """A sub-microsecond p95 rounds to 0.0 ms; dividing by it must not crash the sweep."""
    rows = [
        _cell("availability", "without-index", 100, p95=1.0),
        _cell("availability", "with-index", 100, p95=0.0),
    ]
    curve = bench.assemble_curve(rows)
    assert bench.speedup_rows(curve)[0]["speedup"] is None


def test_comparison_lines_render_every_row():
    rows = [
        _cell("availability", "without-index", 100, p95=40.0),
        _cell("availability", "with-index", 100, p95=4.0),
    ]
    lines = bench.comparison_lines(bench.speedup_rows(bench.assemble_curve(rows)))
    body = [line for line in lines if "availability" in line]
    assert len(body) == 1
    assert "10.00x" in body[0]


def test_sql_speedup_is_computed_from_server_side_time():
    """The decision column: the aggregation alone, with the round trip taken out.

    Here wall time gets *worse* (1.0 -> 1.2) while the query itself gets 20x faster — the exact
    shape this benchmark measured for real on a containerised database, and the reason reporting
    wall time alone would have rejected an index that plainly works.
    """
    rows = [
        _cell("availability", "without-index", 100, p95=1.0, sql=4.0),
        _cell("availability", "with-index", 100, p95=1.2, sql=0.2),
    ]
    row = bench.speedup_rows(bench.assemble_curve(rows))[0]

    assert row["sql_speedup"] == 20.0
    assert row["speedup"] < 1  # wall time says the opposite
    assert "20.00x" in bench.comparison_lines([row])[2]


def test_sql_speedup_is_none_when_timing_is_missing():
    rows = [
        _cell("availability", "without-index", 100, p95=1.0, sql=None),
        _cell("availability", "with-index", 100, p95=1.0, sql=None),
    ]
    row = bench.speedup_rows(bench.assemble_curve(rows))[0]
    assert row["sql_speedup"] is None
    # The table must still render rather than crashing on the missing cell.
    assert "n/a" in bench.comparison_lines([row])[2]


# ── sample_budget — the expensive path must not run for hours ─────────────────


def test_sample_budget_takes_everything_requested_when_calls_are_cheap():
    assert bench.sample_budget(0.001, requested=100, budget_seconds=20.0) == 100


def test_sample_budget_cuts_samples_for_an_expensive_cell():
    """`export_csv` is unpaginated: one call at 200k lots costs seconds, and 100 of them would
    run for hours while the cheap paths finish in seconds."""
    assert bench.sample_budget(2.0, requested=100, budget_seconds=20.0) == 10


def test_sample_budget_never_goes_below_the_floor():
    """Even a pathologically slow call yields enough samples to state a range."""
    assert bench.sample_budget(600.0, requested=100, budget_seconds=20.0) == bench.MIN_SAMPLES


def test_sample_budget_handles_an_unmeasurably_fast_warmup():
    """A zero warm-up duration must not divide by zero."""
    assert bench.sample_budget(0.0, requested=42, budget_seconds=20.0) == 42


# ── artifact_name — a rename orphans published evidence ───────────────────────


def test_artifact_name_is_stable():
    assert (
        bench.artifact_name("availability", 50_000, "with-index")
        == "aggregation-availability-lots50000-with-index"
    )


def test_artifact_names_are_unique_per_cell():
    names = {
        bench.artifact_name(p, lots, arm)
        for p in bench.PATHS
        for lots in (1_000, 200_000)
        for arm in bench.ARMS
    }
    assert len(names) == len(bench.PATHS) * 2 * len(bench.ARMS)


# ── argument parsing ──────────────────────────────────────────────────────────


def test_parser_requires_ascending_volumes():
    """The substrate grows monotonically between steps, so a descending list would measure the
    larger volume twice and label one of them small."""
    with pytest.raises(SystemExit):
        bench._parse_args(["--lot-steps", "1000,100", "--dsn", "postgresql://x/y"])


def test_parser_rejects_unknown_path_and_arm():
    with pytest.raises(SystemExit):
        bench._parse_args(["--paths", "not-a-path", "--dsn", "postgresql://x/y"])
    with pytest.raises(SystemExit):
        bench._parse_args(["--arms", "with-magic", "--dsn", "postgresql://x/y"])


def test_parser_requires_a_dsn():
    with pytest.raises(SystemExit):
        bench._parse_args(["--dsn", ""])


def test_parser_defaults_are_the_documented_sweep():
    args = bench._parse_args(["--dsn", "postgresql://x/y"])
    assert args.lot_steps == list(bench.DEFAULT_LOT_STEPS)
    assert args.samples == bench.DEFAULT_SAMPLES
    assert args.paths == list(bench.PATHS)
    assert args.arms == list(bench.ARMS)
    assert args.index_variant in bench.INDEX_VARIANTS


def test_every_index_variant_is_valid_ddl_shape():
    """Each candidate must name the one index the sweep drops between arms."""
    for ddl in bench.INDEX_VARIANTS.values():
        assert ddl.startswith(f"CREATE INDEX {bench.INDEX_NAME} ON inventory_lots")
