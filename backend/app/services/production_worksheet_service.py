"""Production-worksheet service — home of the concurrency-safe close protocol (ACR-30).

The close is the reason this module exists. See `close_worksheet` for the protocol and
`docs/architecture.md` (ADR-02) for why it is ordered the way it is.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.models.production_worksheet import ProductionWorksheet, ProductionWorksheetLine
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import (
    WorksheetCloseRequest,
    WorksheetCreate,
    WorksheetLineResponse,
    WorksheetResponse,
)

REFERENCE_TYPE = "production_worksheet"


async def _load_product_names(db: AsyncSession, product_ids: set[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    res = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    return {p.id: p.name for p in res.scalars().all()}


async def _ws_response(db: AsyncSession, ws: ProductionWorksheet) -> WorksheetResponse:
    lines_res = await db.execute(
        select(ProductionWorksheetLine)
        .where(ProductionWorksheetLine.worksheet_id == ws.id)
        .order_by(ProductionWorksheetLine.id.asc())
    )
    lines = list(lines_res.scalars().all())
    names = await _load_product_names(db, {ln.product_id for ln in lines})

    return WorksheetResponse(
        id=ws.id,
        work_order_id=ws.work_order_id,
        production_line=ws.production_line,
        scheduled_date=ws.scheduled_date,
        status=ws.status,
        version=ws.version,
        created_by=ws.created_by,
        created_at=ws.created_at,
        closed_at=ws.closed_at,
        lines=[
            WorksheetLineResponse(
                id=ln.id,
                worksheet_id=ln.worksheet_id,
                product_id=ln.product_id,
                product_name=names.get(ln.product_id),
                planned_quantity=ln.planned_quantity,
                actual_quantity=ln.actual_quantity,
            )
            for ln in lines
        ],
    )


async def _get_worksheet_or_404(
    db: AsyncSession, worksheet_id: int, *, lock: bool = False
) -> ProductionWorksheet:
    """Load a worksheet, 404 if absent. ``lock=True`` takes the row lock the close needs."""
    q = select(ProductionWorksheet).where(ProductionWorksheet.id == worksheet_id)
    if lock:
        q = q.with_for_update()
    ws = (await db.execute(q)).scalar_one_or_none()
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Production worksheet not found"
        )
    return ws


def _draw_fifo(
    db: AsyncSession,
    lots: list[InventoryLot],
    quantity: int,
    worksheet_id: int,
    user_id: int,
) -> None:
    """Draw ``quantity`` from ``lots`` oldest-first, one `consume` movement per lot touched.

    Pure arithmetic plus `db.add` (sync) — the caller owns locking, validation and the commit.
    ``lots`` is mutated in place so two lines drawing on the same product see each other's draw.
    """
    remaining = quantity
    for lot in lots:
        if remaining <= 0:
            break
        taken = min(remaining, lot.quantity_on_hand)
        lot.quantity_on_hand -= taken
        if lot.quantity_on_hand == 0:
            lot.status = "consumed"
        db.add(
            InventoryTransaction(
                lot_id=lot.id,
                transaction_type="consume",
                quantity=-taken,
                reference_type=REFERENCE_TYPE,
                reference_id=worksheet_id,
                reason=f"Production worksheet {worksheet_id} close",
                created_by=user_id,
            )
        )
        remaining -= taken


async def _rollback_and_409(db: AsyncSession, detail: str) -> None:
    """Roll back the close, then refuse it with 409.

    ``detail`` is taken as an already-built string on purpose: rollback expires every instance
    in the session, so any attribute the message needs must be read **before** this is called.
    Making that a parameter is what keeps the rule structural rather than a comment the next
    conflict path can forget.
    """
    await db.rollback()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def create_worksheet(
    db: AsyncSession,
    body: WorksheetCreate,
    current_user: TokenUser,
) -> WorksheetResponse:
    """Create a draft worksheet with its material lines. Stock is untouched until close."""
    # Resolve the products up front: without this an unknown product_id reaches the FK
    # constraint and surfaces as a 500 rather than something the operator can act on.
    requested = {line.product_id for line in body.lines}
    known = set((await _load_product_names(db, requested)).keys())
    missing = sorted(requested - known)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown product_id(s): {', '.join(str(p) for p in missing)}.",
        )

    ws = ProductionWorksheet(
        work_order_id=body.work_order_id,
        production_line=body.production_line,
        scheduled_date=body.scheduled_date,
        status="draft",
        version=0,
        created_by=current_user.user_id,
    )
    db.add(ws)
    await db.flush()

    for line in body.lines:
        db.add(
            ProductionWorksheetLine(
                worksheet_id=ws.id,
                product_id=line.product_id,
                planned_quantity=line.planned_quantity,
            )
        )

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="production_worksheet_created",
        entity_type=REFERENCE_TYPE,
        entity_id=ws.id,
        details={"lines": len(body.lines), "work_order_id": body.work_order_id},
    )
    await db.commit()

    return await _ws_response(db, ws)


async def get_worksheet(db: AsyncSession, worksheet_id: int) -> WorksheetResponse:
    ws = await _get_worksheet_or_404(db, worksheet_id)
    return await _ws_response(db, ws)


async def close_worksheet(
    db: AsyncSession,
    worksheet_id: int,
    body: WorksheetCloseRequest,
    current_user: TokenUser,
) -> WorksheetResponse:
    """Close a worksheet and consume stock at `actual_quantity` per line.

    The protocol — the order **is** the deliverable (ADR-02):

    1. Read Committed (Postgres default). Deliberately *not* SERIALIZABLE: under N-way
       parallelism that raises `could not serialize access`, which surfaces as a 500 rather
       than the 409 the operator can act on.
    2. Lock the parent worksheet row `FOR UPDATE`. This also fixes the lock order for step 4,
       so two closes can never deadlock against each other.
    3. Claim the worksheet with **one conditional UPDATE** on `version`. `rowcount != 1` → 409.
       The winner of a concurrent race is decided here, atomically, by the database — never by
       a read-then-check.
    4. Lock the candidate lots in a deterministic order (`id ASC`) across every caller.
    5. Check availability, then draw FIFO with integer arithmetic, writing one `consume`
       transaction per lot touched.

    Exactly one `consume` InventoryTransaction is written per lot drawn from — and **no
    adjustment row for `actual − planned`**. That delta is a reporting figure computed from the
    line, never a movement: the consume is already at `actual_quantity`, so an adjustment would
    correct something that was never wrong and silently drift inventory
    (`client_domain_model.md` §7.1, binding on this ticket by name).
    """
    # 2 — lock the parent row; also fixes lock ordering for step 4.
    ws = await _get_worksheet_or_404(db, worksheet_id, lock=True)

    lines_res = await db.execute(
        select(ProductionWorksheetLine)
        .where(ProductionWorksheetLine.worksheet_id == worksheet_id)
        .order_by(ProductionWorksheetLine.id.asc())
    )
    lines_by_id = {ln.id: ln for ln in lines_res.scalars().all()}

    submitted: dict[int, int] = {}
    for close_line in body.lines:
        if close_line.line_id not in lines_by_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Line {close_line.line_id} does not belong to this worksheet.",
            )
        if close_line.line_id in submitted:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Line {close_line.line_id} appears more than once.",
            )
        submitted[close_line.line_id] = close_line.actual_quantity

    now = datetime.now(timezone.utc)

    # 3 — the optimistic guard, before a single unit of stock is touched.
    claim = await db.execute(
        update(ProductionWorksheet)
        .where(
            ProductionWorksheet.id == worksheet_id,
            ProductionWorksheet.version == body.expected_version,
            ProductionWorksheet.status != "closed",
        )
        .values(status="closed", version=ProductionWorksheet.version + 1, closed_at=now)
    )
    if claim.rowcount != 1:
        # Build the message while `ws` is still live — see `_rollback_and_409`.
        detail = (
            "Worksheet is already closed."
            if ws.status == "closed"
            else (
                "Worksheet was modified by another operation "
                f"(expected version {body.expected_version})."
            )
        )
        await _rollback_and_409(db, detail)

    # 4 — lock the stock in a deterministic order across every caller.
    product_ids = {lines_by_id[line_id].product_id for line_id in submitted}
    lots_res = await db.execute(
        select(InventoryLot)
        .where(
            InventoryLot.product_id.in_(product_ids),
            InventoryLot.status == "in_storage",
            InventoryLot.quantity_on_hand > 0,
        )
        .order_by(InventoryLot.id.asc())
        .with_for_update()
    )
    lots_by_product: dict[int, list[InventoryLot]] = {}
    for lot in lots_res.scalars().all():
        lots_by_product.setdefault(lot.product_id, []).append(lot)

    # 5 — availability check, then FIFO draw with integer arithmetic.
    for line_id, actual in submitted.items():
        line = lines_by_id[line_id]
        line.actual_quantity = actual
        if actual == 0:
            continue

        product_id = line.product_id
        lots = lots_by_product.get(product_id, [])
        available = sum(lot.quantity_on_hand for lot in lots)
        if available < actual:
            # This path is only reachable when a close loses a real race for the stock.
            await _rollback_and_409(
                db,
                f"Insufficient stock for product {product_id}. "
                f"Required: {actual}, available: {available}.",
            )

        _draw_fifo(db, lots, actual, worksheet_id, current_user.user_id)

    # Mirror the claim onto the instance *inside* the transaction. The claim in step 3 was a Core
    # UPDATE, so this keeps the response consistent with what was committed without mutating
    # persistent state after the commit.
    ws.status = "closed"
    ws.version = body.expected_version + 1
    ws.closed_at = now

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="production_worksheet_closed",
        entity_type=REFERENCE_TYPE,
        entity_id=worksheet_id,
        details={"lines": {str(k): v for k, v in submitted.items()}},
    )
    await db.commit()

    return await _ws_response(db, ws)
