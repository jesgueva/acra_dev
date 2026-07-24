"""Stock reservations — reserve / release, and the available-stock query.

``available = on_hand − reserved`` per ``(item, state)``. A reservation earmarks stock for an open
production worksheet: it lowers ``available`` while leaving ``on_hand`` untouched. Stock only
leaves the warehouse when the worksheet closes (ACR-31), which is where the movement is written —
so nothing here mutates ``inventory_lots`` or writes an ``inventory_transactions`` row.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.inventory import InventoryLot, LotStatus
from app.models.product import Product
from app.models.reservation import ReservationStatus, StockReservation
from app.schemas.reservation import (
    AvailabilityResponse,
    ReservationCreate,
    ReservationListResponse,
    ReservationResponse,
)


# ── Internals ─────────────────────────────────────────────────────────────────


async def _get_product_or_404(db: AsyncSession, product_id: int) -> Product:
    product = (
        await db.execute(select(Product).where(Product.id == product_id))
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    return product


async def _on_hand(db: AsyncSession, product_id: int, state: LotStatus) -> int:
    """On-hand for ``(item, state)``, summed over the lots in that state.

    TODO(Phase 2): delegate to ``stock_movement_service.on_hand()`` once the append-only
    StockMovement ledger table lands. This function is the only place the lot-centric
    aggregation leaks into the reservation layer — swapping it swaps the whole ledger.
    """
    res = await db.execute(
        select(func.coalesce(func.sum(InventoryLot.quantity_on_hand), 0)).where(
            InventoryLot.product_id == product_id,
            InventoryLot.status == state.value,
        )
    )
    return res.scalar() or 0


async def _reserved(db: AsyncSession, product_id: int, state: LotStatus) -> int:
    """Sum of ACTIVE reservations against ``(item, state)``."""
    res = await db.execute(
        select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
            StockReservation.product_id == product_id,
            StockReservation.state == state.value,
            StockReservation.status == ReservationStatus.ACTIVE.value,
        )
    )
    return res.scalar() or 0


async def _lock_lots(db: AsyncSession, product_id: int, state: LotStatus) -> None:
    """Row-lock the lots backing ``(item, state)`` so concurrent reserves serialize.

    A reserve can only succeed when at least one lot exists, so locking the lot rows is enough to
    stop two callers from both reading the same ``available`` and oversubscribing it.
    """
    await db.execute(
        select(InventoryLot.id)
        .where(
            InventoryLot.product_id == product_id,
            InventoryLot.status == state.value,
        )
        .with_for_update()
    )


def _response(reservation: StockReservation, product_name: Optional[str]) -> ReservationResponse:
    return ReservationResponse(
        id=reservation.id,
        product_id=reservation.product_id,
        product_name=product_name,
        state=reservation.state,
        quantity=reservation.quantity,
        production_worksheet_line_id=reservation.production_worksheet_line_id,
        status=reservation.status,
        created_by=reservation.created_by,
        created_at=reservation.created_at,
        released_at=reservation.released_at,
    )


async def _load_product_names(db: AsyncSession, product_ids: set[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    res = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    return {p.id: p.name for p in res.scalars().all()}


# ── Public API ────────────────────────────────────────────────────────────────


async def availability(
    db: AsyncSession,
    product_id: int,
    state: LotStatus = LotStatus.IN_STORAGE,
) -> AvailabilityResponse:
    """``on_hand`` / ``reserved`` / ``available`` for one ``(item, state)`` pair."""
    product = await _get_product_or_404(db, product_id)
    on_hand = await _on_hand(db, product_id, state)
    reserved = await _reserved(db, product_id, state)

    return AvailabilityResponse(
        product_id=product_id,
        product_name=product.name,
        state=state,
        on_hand=on_hand,
        reserved=reserved,
        available=on_hand - reserved,
    )


async def reserve(
    db: AsyncSession,
    data: ReservationCreate,
    user_id: int,
) -> ReservationResponse:
    """Reserve stock against ``(item, state)``. Never touches on-hand."""
    product = await _get_product_or_404(db, data.product_id)

    await _lock_lots(db, data.product_id, data.state)
    on_hand = await _on_hand(db, data.product_id, data.state)
    reserved = await _reserved(db, data.product_id, data.state)
    available = on_hand - reserved

    if data.quantity > available:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Insufficient available stock for product {data.product_id} "
                f"in state '{data.state.value}': "
                f"requested {data.quantity / 100:.2f}, available {available / 100:.2f}"
            ),
        )

    reservation = StockReservation(
        product_id=data.product_id,
        state=data.state.value,
        quantity=data.quantity,
        production_worksheet_line_id=data.production_worksheet_line_id,
        status=ReservationStatus.ACTIVE.value,
        created_by=user_id,
    )
    db.add(reservation)
    await db.flush()  # assigns PK + created_at before we build the response

    await write_audit(
        db=db,
        user_id=user_id,
        action="reservation.created",
        entity_type="stock_reservation",
        entity_id=reservation.id,
        details={
            "product_id": data.product_id,
            "state": data.state.value,
            "quantity": data.quantity,
            "available_before": available,
        },
    )
    await db.commit()

    return _response(reservation, product.name)


async def release(
    db: AsyncSession,
    reservation_id: int,
    user_id: int,
) -> ReservationResponse:
    """Release an active reservation, returning its quantity to ``available``."""
    reservation = (
        await db.execute(
            select(StockReservation).where(StockReservation.id == reservation_id)
        )
    ).scalar_one_or_none()

    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation {reservation_id} not found",
        )

    if reservation.status != ReservationStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Reservation {reservation_id} is already released",
        )

    reservation.status = ReservationStatus.RELEASED.value
    reservation.released_at = datetime.now(timezone.utc)

    await write_audit(
        db=db,
        user_id=user_id,
        action="reservation.released",
        entity_type="stock_reservation",
        entity_id=reservation.id,
        details={
            "product_id": reservation.product_id,
            "state": reservation.state,
            "quantity": reservation.quantity,
        },
    )
    await db.commit()

    product_names = await _load_product_names(db, {reservation.product_id})
    return _response(reservation, product_names.get(reservation.product_id))


async def list_reservations(
    db: AsyncSession,
    product_id: Optional[int] = None,
    state: Optional[LotStatus] = None,
    status_filter: Optional[ReservationStatus] = None,
    page: int = 1,
    page_size: int = 50,
) -> ReservationListResponse:
    """Paginated reservation list, newest first."""
    base = select(StockReservation)
    if product_id is not None:
        base = base.where(StockReservation.product_id == product_id)
    if state is not None:
        base = base.where(StockReservation.state == state.value)
    if status_filter is not None:
        base = base.where(StockReservation.status == status_filter.value)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            base.order_by(StockReservation.created_at.desc()).offset(offset).limit(page_size)
        )
    ).scalars().all()

    product_names = await _load_product_names(db, {r.product_id for r in rows})

    return ReservationListResponse(
        total=total,
        page=page,
        page_size=page_size,
        results=[_response(r, product_names.get(r.product_id)) for r in rows],
    )
