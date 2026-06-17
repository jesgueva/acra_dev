"""Covers the Phase 2 StockMovement ledger skeleton (model vocab, service stubs, 501 router).

These tests pin the skeleton's shape and assert the placeholders behave as documented, so the
baseline stays green and the coverage gate holds while the real ledger is built in Sprint II.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.stock_movement import MovementType, StockState
from app.services import stock_movement_service


def test_stock_state_vocabulary():
    assert StockState.IN_STORAGE.value == "in_storage"
    assert {s.value for s in StockState} == {
        "in_storage",
        "in_production",
        "shipped",
        "consumed",
    }


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
            state=StockState.IN_STORAGE,
            movement_type=MovementType.RECEIPT,
            quantity=1,
        )


@pytest.mark.asyncio
async def test_on_hand_not_implemented():
    with pytest.raises(NotImplementedError):
        await stock_movement_service.on_hand(item_id=1, state=StockState.IN_STORAGE)


@pytest.mark.asyncio
async def test_stock_movements_endpoint_returns_501():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/stock-movements")
    assert response.status_code == 501
    assert "Sprint II" in response.json()["detail"]
