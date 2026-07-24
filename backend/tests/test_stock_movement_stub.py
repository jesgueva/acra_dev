"""Covers the Phase 2 StockMovement ledger skeleton (model vocab, service stubs, 501 router).

These tests pin the skeleton's shape and assert the placeholders behave as documented, so the
baseline stays green and the coverage gate holds while the real ledger is built in Sprint II.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.inventory import InventoryLot, LotStatus
from app.models.stock_movement import MovementType, StockState
from app.services import stock_movement_service


def test_stock_state_vocabulary():
    """State is the material axis (RM → WIP → FG), never a lifecycle axis."""
    assert StockState.RAW_MATERIAL.value == "raw_material"
    assert {s.value for s in StockState} == {
        "raw_material",
        "work_in_progress",
        "finished_good",
    }


def test_stock_state_excludes_lifecycle_values():
    """Guards ACR-26: lifecycle belongs to MovementType + reservations, not to state.

    ``shipped`` / ``consumed`` as states would break ``on_hand = Σ signed qty`` — an ISSUE of -100
    at state=SHIPPED gives on_hand(item, SHIPPED) == -100. ``auxiliary`` is a category on the item
    (D-Q4), not a state.
    """
    values = {s.value for s in StockState}
    for forbidden in ("in_storage", "in_production", "shipped", "consumed", "auxiliary"):
        assert forbidden not in values


def test_lot_status_is_the_lifecycle_axis():
    """The two axes stay disjoint — that separation is the whole point of ACR-26."""
    assert {s.value for s in LotStatus} == {
        "in_storage",
        "in_production",
        "shipped",
        "consumed",
    }
    assert {s.value for s in LotStatus}.isdisjoint({s.value for s in StockState})


def test_lot_status_check_constraint_matches_migration_007():
    """``InventoryLot`` derives its constraint from ``LotStatus``, so the enum can't drift from the
    model. It *can* still drift from the database: adding a member here rewrites the model's
    constraint while migration 007 keeps the original four. Pin the SQL so that needs a migration.
    """
    constraint = next(
        c
        for c in InventoryLot.__table__.constraints
        if getattr(c, "name", "") == "ck_inventory_lots_status"
    )
    assert str(constraint.sqltext) == (
        "status IN ('in_storage', 'in_production', 'shipped', 'consumed')"
    )
    assert InventoryLot.__table__.c.status.server_default.arg == LotStatus.IN_STORAGE.value


def test_movement_type_vocabulary():
    assert MovementType.RECEIPT.value == "receipt"
    assert {m.value for m in MovementType} == {
        "receipt",
        "reserve",
        "consume",
        "issue",
        "adjust",
        "transfer",
    }


@pytest.mark.asyncio
async def test_record_movement_not_implemented():
    with pytest.raises(NotImplementedError):
        await stock_movement_service.record_movement(
            item_id=1,
            state=StockState.RAW_MATERIAL,
            movement_type=MovementType.RECEIPT,
            quantity=1,
        )


@pytest.mark.asyncio
async def test_on_hand_not_implemented():
    with pytest.raises(NotImplementedError):
        await stock_movement_service.on_hand(item_id=1, state=StockState.RAW_MATERIAL)


@pytest.mark.asyncio
async def test_stock_movements_endpoint_returns_501():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/stock-movements")
    assert response.status_code == 501
    assert "Sprint II" in response.json()["detail"]
