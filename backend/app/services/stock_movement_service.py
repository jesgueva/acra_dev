"""Phase 2 — stock-movement ledger service (skeleton).

Defines the service interface the ledger will expose; behavior lands in Sprint II. Keeping the
signatures here lets dependent surfaces (receiving, production close, shipment) be wired against a
stable contract before the implementation exists.
"""

from app.models.stock_movement import MovementType, StockState

_NOT_YET = "StockMovement ledger is not implemented until Sprint II (Phase 2)."


async def record_movement(
    *,
    item_id: int,
    state: StockState,
    movement_type: MovementType,
    quantity: int,
) -> None:
    """Append a signed movement to the ledger.

    Not yet implemented — see ``docs/architecture.md`` (Phase 2 direction).
    """
    raise NotImplementedError(_NOT_YET)


async def on_hand(*, item_id: int, state: StockState) -> int:
    """Return on-hand for ``(item, state)`` as the sum of signed movement quantities.

    Not yet implemented — see ``docs/architecture.md`` (Phase 2 direction).
    """
    raise NotImplementedError(_NOT_YET)
