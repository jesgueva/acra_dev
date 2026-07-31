"""A8-1 — the seed's planning layer, exercised without a database.

`seed_fake_data` splits "decide what rows should exist" from "write them". Everything here tests
the pure half, which is what makes the scale-1 fixture cheap to pin.

**Why the golden snapshot matters:** all 83 Playwright e2e tests log in as seeded users and read
seeded rows, and `tests/test_shipping_privileges.py` reads seeded privileges. If `--scale 1` output
drifts by one field, that suite breaks in a way that is expensive to diagnose from the e2e failure.
`test_scale_one_matches_golden_snapshot` fails first, in milliseconds, and says exactly what moved.
"""
import hashlib
from dataclasses import astuple
from datetime import date, timedelta

import pytest

from scripts.seed_fake_data import (
    BASE_MATERIALS,
    DELIVERIES_PER_SCALE,
    WORK_ORDER_SEEDS,
    WORK_ORDERS_PER_SCALE,
    build_parser,
    material_balance,
    plan_deliveries,
    plan_materials,
    plan_work_orders,
    resolve_volumes,
)

# A fixed date, so the snapshot does not move with the clock.
FIXED_TODAY = date(2026, 7, 30)

# The scale-1 fixture as it stood before the scale knob existed (master @ 7649a6e). Regenerate
# ONLY when the demo fixture is intentionally changed — and expect to re-record the e2e suite.
GOLDEN_PLAN_SHA256 = "2951e6303541348051db52d266dce2f7dc6ac5e265321b1d943685dfad0b4b49"

SCALE_1_DELIVERIES = 24
SCALE_1_DELIVERY_ITEMS = 72
SCALE_1_WORK_ORDERS = 8


def _fingerprint(specs) -> str:
    """Stable serialization of a delivery plan — every field of every line."""
    blob = "\n".join(
        "|".join(
            str(v) for v in (s.index, s.bol_reference, s.supplier, s.carrier, s.delivery_date)
        )
        + "||"
        + ";".join(",".join(str(x) for x in astuple(i)) for i in s.items)
        for s in specs
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# The scale-1 contract
# ---------------------------------------------------------------------------

def test_scale_one_matches_golden_snapshot():
    """Every field of all 24 deliveries and 72 lines is unchanged from the pre-knob script."""
    specs = plan_deliveries(SCALE_1_DELIVERIES, FIXED_TODAY)
    assert _fingerprint(specs) == GOLDEN_PLAN_SHA256, (
        "The scale-1 demo fixture changed. This breaks the 83 Playwright e2e tests, which read "
        "these exact rows. If the change is intentional, re-record the snapshot AND the e2e suite."
    )


def test_scale_one_volumes():
    specs = plan_deliveries(SCALE_1_DELIVERIES, FIXED_TODAY)
    assert len(specs) == SCALE_1_DELIVERIES
    assert sum(len(s.items) for s in specs) == SCALE_1_DELIVERY_ITEMS


def test_scale_one_first_delivery_fields():
    """Spot-check in readable form, so a snapshot failure has something to compare against."""
    first = plan_deliveries(SCALE_1_DELIVERIES, FIXED_TODAY)[0]
    assert first.index == 1
    assert first.bol_reference == "DEMO-BOL-2026-001"
    assert first.supplier == "Northwind Materials"
    assert first.carrier == "DHL Freight"
    assert first.delivery_date == date(2026, 7, 28)
    assert [i.material_type for i in first.items] == [
        "Steel Rod",
        "Aluminum Sheet",
        "Plastic Resin",
    ]
    assert [i.storage_location for i in first.items] == ["RACK-A1", "RACK-B2", "BULK-01"]
    assert [i.quantity_x100 for i in first.items] == [75_000, 120_000, 175_000]


def test_plan_work_orders_scale_one_is_the_base_seeds():
    assert plan_work_orders(SCALE_1_WORK_ORDERS) == list(WORK_ORDER_SEEDS)


def test_work_orders_per_scale_tracks_the_seed_list():
    assert WORK_ORDERS_PER_SCALE == len(WORK_ORDER_SEEDS)


# ---------------------------------------------------------------------------
# Scaling properties
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scale", [2, 10, 50])
def test_higher_scale_is_a_superset_of_scale_one(scale):
    """Index 1..24 must generate identical rows at every scale — re-seeding is additive."""
    base = plan_deliveries(SCALE_1_DELIVERIES, FIXED_TODAY)
    scaled = plan_deliveries(SCALE_1_DELIVERIES * scale, FIXED_TODAY)
    assert scaled[:SCALE_1_DELIVERIES] == base


@pytest.mark.parametrize("scale", [1, 2, 10, 50])
def test_volume_scales_linearly(scale):
    specs = plan_deliveries(DELIVERIES_PER_SCALE * scale, FIXED_TODAY)
    assert len(specs) == SCALE_1_DELIVERIES * scale
    assert sum(len(s.items) for s in specs) == SCALE_1_DELIVERY_ITEMS * scale
    assert len(plan_work_orders(WORK_ORDERS_PER_SCALE * scale)) == SCALE_1_WORK_ORDERS * scale


def test_bol_references_stay_unique_past_999():
    """`{index:03d}` pads to a *minimum* of 3, so index 1000 renders as "1000", not a collision."""
    specs = plan_deliveries(1200, FIXED_TODAY)
    refs = [s.bol_reference for s in specs]
    assert len(set(refs)) == len(refs)
    assert refs[999] == "DEMO-BOL-2026-1000"


def test_lot_numbers_stay_unique_at_scale():
    specs = plan_deliveries(DELIVERIES_PER_SCALE * 20, FIXED_TODAY)
    lot_numbers = [
        f"{item.lot_prefix}-{s.bol_reference}-{item.line_number}"
        for s in specs
        for item in s.items
    ]
    assert len(set(lot_numbers)) == len(lot_numbers)


def test_work_order_replicas_get_distinct_products():
    """Without the suffix, `create_demo_work_orders`' product-match skip drops every replica."""
    orders = plan_work_orders(WORK_ORDERS_PER_SCALE * 50)
    products = [o.product for o in orders]
    assert len(set(products)) == len(products)


def test_work_order_replica_naming():
    orders = plan_work_orders(WORK_ORDERS_PER_SCALE * 3)
    base_name = WORK_ORDER_SEEDS[0].product
    assert orders[0].product == base_name  # replica 0 keeps the bare name
    assert orders[WORK_ORDERS_PER_SCALE].product == f"{base_name} #2"
    assert orders[WORK_ORDERS_PER_SCALE * 2].product == f"{base_name} #3"


def test_replicas_keep_the_base_material_requirements():
    orders = plan_work_orders(WORK_ORDERS_PER_SCALE * 2)
    replica = orders[WORK_ORDERS_PER_SCALE]
    assert replica.materials == WORK_ORDER_SEEDS[0].materials
    assert replica.status == WORK_ORDER_SEEDS[0].status


def test_quantities_are_integers_not_floats():
    """The ×100 convention has to survive scaling — a float here becomes drift in the ledger."""
    for spec in plan_deliveries(DELIVERIES_PER_SCALE * 10, FIXED_TODAY):
        for item in spec.items:
            assert isinstance(item.quantity_x100, int)
            assert item.quantity_x100 == item.pallets * item.units_per_pallet * 100


# ---------------------------------------------------------------------------
# Date window
# ---------------------------------------------------------------------------

def test_delivery_dates_are_bounded_at_high_scale():
    """Unwrapped, index*2 days reaches ~13 years back at scale 100."""
    specs = plan_deliveries(DELIVERIES_PER_SCALE * 100, FIXED_TODAY)
    oldest = min(s.delivery_date for s in specs)
    assert (FIXED_TODAY - oldest).days <= 730


def test_date_wrapping_leaves_the_demo_fixture_untouched():
    for spec in plan_deliveries(SCALE_1_DELIVERIES, FIXED_TODAY):
        assert spec.delivery_date == FIXED_TODAY - timedelta(days=spec.index * 2)


# ---------------------------------------------------------------------------
# Material catalogue
# ---------------------------------------------------------------------------

def test_default_catalogue_is_the_named_materials():
    assert plan_materials(len(BASE_MATERIALS)) == list(BASE_MATERIALS)


def test_extended_catalogue_keeps_the_named_materials_first():
    materials = plan_materials(60)
    assert materials[: len(BASE_MATERIALS)] == list(BASE_MATERIALS)
    assert len(materials) == 60


def test_generated_materials_have_unique_names_and_prefixes():
    materials = plan_materials(200)
    assert len({m.material_type for m in materials}) == 200
    assert len({m.lot_prefix for m in materials}) == 200


def test_extended_catalogue_reaches_every_material_at_volume():
    """A8-6 needs lots spread across products, not piled onto the first few."""
    materials = plan_materials(60)
    specs = plan_deliveries(DELIVERIES_PER_SCALE * 20, FIXED_TODAY, materials)
    used = {item.material_type for s in specs for item in s.items}
    assert used == {m.material_type for m in materials}


# ---------------------------------------------------------------------------
# Supply vs demand — the trap that aborts a seed mid-run
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scale", [1, 2, 10, 50, 200])
def test_default_scaling_stays_feasible(scale):
    """Supply and demand are both multiplied by N, so headroom must not decay with scale."""
    deliveries = plan_deliveries(DELIVERIES_PER_SCALE * scale, FIXED_TODAY)
    work_orders = plan_work_orders(WORK_ORDERS_PER_SCALE * scale)
    for material_type, (supply, demand) in material_balance(deliveries, work_orders).items():
        assert supply >= demand, f"{material_type} short at scale {scale}"


def test_material_balance_predicts_the_starved_case():
    """The configuration that makes `allocate_inventory` abort is visible from the plan alone."""
    materials = plan_materials(60)
    deliveries = plan_deliveries(24, FIXED_TODAY, materials)
    work_orders = plan_work_orders(200)
    balance = material_balance(deliveries, work_orders)
    assert any(supply < demand for supply, demand in balance.values())


def test_created_work_orders_contribute_no_demand():
    """Status "created" is seeded unallocated, so it must not count against supply."""
    created_only = [o for o in plan_work_orders(WORK_ORDERS_PER_SCALE) if o.status == "created"]
    assert created_only, "fixture should still contain unallocated work orders"
    balance = material_balance([], created_only)
    assert all(demand == 0 for _supply, demand in balance.values())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_scale_resolves_both_axes():
    args = build_parser().parse_args(["--scale", "10"])
    deliveries, work_orders, materials = resolve_volumes(args)
    assert deliveries == DELIVERIES_PER_SCALE * 10
    assert work_orders == WORK_ORDERS_PER_SCALE * 10
    assert materials == len(BASE_MATERIALS)


def test_explicit_axes_override_scale():
    args = build_parser().parse_args(["--scale", "10", "--deliveries", "7", "--work-orders", "0"])
    deliveries, work_orders, _materials = resolve_volumes(args)
    assert deliveries == 7
    assert work_orders == 0


def test_defaults_are_the_demo_fixture():
    args = build_parser().parse_args([])
    assert resolve_volumes(args) == (
        DELIVERIES_PER_SCALE,
        WORK_ORDERS_PER_SCALE,
        len(BASE_MATERIALS),
    )


@pytest.mark.parametrize("argv", [["--scale", "0"], ["--scale", "-1"], ["--materials", "0"]])
def test_parser_rejects_non_positive_volumes(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


@pytest.mark.parametrize("argv", [["--deliveries", "-1"], ["--work-orders", "-5"]])
def test_parser_rejects_negative_absolute_counts(argv):
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_zero_is_allowed_for_absolute_axes():
    """`--work-orders 0` is the documented way to build a lots-only corpus for A8-6."""
    args = build_parser().parse_args(["--work-orders", "0", "--deliveries", "0"])
    assert resolve_volumes(args)[:2] == (0, 0)
