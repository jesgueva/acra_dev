"""Production worksheet service — creation, read, and the concurrency-safe close (ACR-30).

``close_worksheet`` is the point of this module; everything else exists to give it something to
close. See its docstring for the protocol and why it is shaped that way.
"""

from collections import Counter, defaultdict
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

# Lots in any other status are not on the shelf and must not be drawn from.
_DRAWABLE_LOT_STATUS = "in_storage"


async def _load_products(db: AsyncSession, ids: set[int]) -> dict[int, Product]:
    if not ids:
        return {}
    res = await db.execute(select(Product).where(Product.id.in_(ids)))
    return {p.id: p for p in res.scalars().all()}


def _worksheet_response(
    ws: ProductionWorksheet,
    lines: list[ProductionWorksheetLine],
    products_by_id: dict[int, Product],
) -> WorksheetResponse:
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
                id=line.id,
                worksheet_id=line.worksheet_id,
                product_id=line.product_id,
                product_name=getattr(products_by_id.get(line.product_id), "name", None),
                planned_quantity=line.planned_quantity,
                actual_quantity=line.actual_quantity,
            )
            for line in lines
        ],
    )


async def _fetch_lines(
    db: AsyncSession, worksheet_id: int
) -> list[ProductionWorksheetLine]:
    res = await db.execute(
        select(ProductionWorksheetLine)
        .where(ProductionWorksheetLine.worksheet_id == worksheet_id)
        .order_by(ProductionWorksheetLine.id.asc())
    )
    return list(res.scalars().all())


async def create_worksheet(
    db: AsyncSession,
    body: WorksheetCreate,
    current_user: TokenUser,
) -> WorksheetResponse:
    """Create a draft worksheet with its material lines.

    ACR-29 replaces this with BoM explosion off a work order; here it is only the setup step that
    gives the close something to consume.
    """
    product_ids = {line.product_id for line in body.lines}
    products_by_id = await _load_products(db, product_ids)

    missing = sorted(product_ids - products_by_id.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown product_id(s): {missing}",
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
    await db.flush()  # assigns ws.id

    lines: list[ProductionWorksheetLine] = []
    for line in body.lines:
        row = ProductionWorksheetLine(
            worksheet_id=ws.id,
            product_id=line.product_id,
            planned_quantity=line.planned_quantity,
        )
        db.add(row)
        lines.append(row)
    await db.flush()  # assigns line ids

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="production_worksheet_created",
        entity_type="production_worksheet",
        entity_id=ws.id,
        details={"lines": len(lines), "work_order_id": body.work_order_id},
    )
    await db.commit()

    return _worksheet_response(ws, lines, products_by_id)


async def get_worksheet(db: AsyncSession, worksheet_id: int) -> WorksheetResponse:
    res = await db.execute(
        select(ProductionWorksheet).where(ProductionWorksheet.id == worksheet_id)
    )
    ws = res.scalar_one_or_none()
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Production worksheet not found"
        )

    lines = await _fetch_lines(db, worksheet_id)
    products_by_id = await _load_products(db, {line.product_id for line in lines})
    return _worksheet_response(ws, lines, products_by_id)


def _validate_close_lines(
    body: WorksheetCloseRequest, lines: list[ProductionWorksheetLine]
) -> dict[int, ProductionWorksheetLine]:
    """Every worksheet line must be accounted for exactly once.

    The duplicate check is not cosmetic: two entries for the same ``line_id`` would consume that
    line's stock twice inside a single, perfectly serialized close — a lost update that no amount
    of locking would catch, because there is no second transaction to serialize against.
    """
    lines_by_id = {line.id: line for line in lines}
    submitted = [cl.line_id for cl in body.lines]

    duplicates = sorted(lid for lid, n in Counter(submitted).items() if n > 1)
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Duplicate line_id(s) in close request: {duplicates}",
        )

    unknown = sorted(set(submitted) - lines_by_id.keys())
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"line_id(s) not on this worksheet: {unknown}",
        )

    missing = sorted(lines_by_id.keys() - set(submitted))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Close request is missing line_id(s): {missing}",
        )

    return lines_by_id


async def close_worksheet(
    db: AsyncSession,
    worksheet_id: int,
    body: WorksheetCloseRequest,
    current_user: TokenUser,
) -> WorksheetResponse:
    """Close the worksheet and consume actual quantities from stock. **RSK-01 / ADR-02.**

    The protocol, in this order — the order *is* the guarantee:

    1. **Read Committed** (PostgreSQL's default). Deliberately *not* the
       ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` that
       ``allocation_service.allocate_materials`` uses: under N-way parallelism SERIALIZABLE aborts
       losers with ``could not serialize access``, which reaches the operator as a 500 and needs a
       retry loop to be usable. Row locks give the loser a deterministic 409 instead.
    2. **Lock the parent row** (``SELECT ... FOR UPDATE``). Also fixes the lock order for step 4, so
       two closes can never deadlock against each other.
    3. **Optimistic version guard as one atomic UPDATE**, before any stock moves. Not a
       read-then-check: the ``WHERE version = :expected`` predicate is re-evaluated by PostgreSQL
       against the freshly committed row, so the winner of a race is chosen by the database. This
       step alone is sufficient against a double-close; step 2 makes the failure deterministic.
    4. **Lock the stock**, every candidate lot in ascending id order — one global order across all
       callers, so concurrent closes queue instead of deadlocking.
    5. Draw FIFO with integer arithmetic and append one ``consume`` transaction per lot touched.
       No compensating ``adjust`` rows: the Issue is written at ``actual_quantity``, so the
       planned/actual delta corrects something that was never wrong (client_domain_model §7.1).
    6. Audit, then a single commit.

    Insufficient stock rolls the whole thing back, including the step-3 status change, leaving the
    worksheet open and retryable.
    """
    # 2. Lock the parent row. Blocks a competing closer here rather than mid-decrement.
    res = await db.execute(
        select(ProductionWorksheet)
        .where(ProductionWorksheet.id == worksheet_id)
        .with_for_update()
    )
    ws = res.scalar_one_or_none()
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Production worksheet not found"
        )

    # Read under the row lock into plain locals. A rollback below expires every ORM instance, and
    # touching an expired attribute afterwards triggers synchronous IO — which raises
    # MissingGreenlet on an async session and turns a clean 409 into a 500.
    current_status, current_version = ws.status, ws.version

    lines = await _fetch_lines(db, worksheet_id)
    lines_by_id = _validate_close_lines(body, lines)

    # 3. The guard. rowcount 0 means another close already won, or it was closed earlier.
    now = datetime.now(timezone.utc)
    guard = await db.execute(
        update(ProductionWorksheet)
        .where(
            ProductionWorksheet.id == worksheet_id,
            ProductionWorksheet.version == body.expected_version,
            ProductionWorksheet.status != "closed",
        )
        .values(
            status="closed",
            version=ProductionWorksheet.version + 1,
            closed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if guard.rowcount != 1:
        # current_status/current_version were read under the row lock, so they are accurate.
        detail = (
            "Worksheet is already closed."
            if current_status == "closed"
            else (
                "Worksheet was modified by another operation "
                f"(expected version {body.expected_version}, current {current_version})."
            )
        )
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # 4. Lock the stock — ascending lot id, one global order for every caller.
    product_ids = {
        lines_by_id[cl.line_id].product_id for cl in body.lines if cl.actual_quantity > 0
    }
    lots_by_product: dict[int, list[InventoryLot]] = defaultdict(list)
    if product_ids:
        lots_res = await db.execute(
            select(InventoryLot)
            .where(
                InventoryLot.product_id.in_(product_ids),
                InventoryLot.status == _DRAWABLE_LOT_STATUS,
                InventoryLot.quantity_on_hand > 0,
            )
            .order_by(InventoryLot.id.asc())
            .with_for_update()
        )
        for lot in lots_res.scalars().all():
            lots_by_product[lot.product_id].append(lot)

    # 5. Draw FIFO. Integer arithmetic throughout — quantities are ×100 ints, and
    #    allocation_service's float() casts on this same column are a wart worth not copying.
    consumed_by_product: dict[int, int] = defaultdict(int)
    for close_line in body.lines:
        line = lines_by_id[close_line.line_id]
        line.actual_quantity = close_line.actual_quantity

        remaining = close_line.actual_quantity
        if remaining == 0:
            continue

        candidate_lots = lots_by_product[line.product_id]
        # Re-summed per line, so two lines drawing on the same product see each other's decrements.
        available = sum(lot.quantity_on_hand for lot in candidate_lots)
        if available < remaining:
            # Build the message before rolling back — rollback expires line.product_id.
            detail = (
                f"Insufficient stock for product {line.product_id}. "
                f"Required: {remaining}, available: {available}."
            )
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

        for lot in candidate_lots:
            if remaining <= 0:
                break
            taken = min(remaining, lot.quantity_on_hand)
            lot.quantity_on_hand -= taken
            db.add(
                InventoryTransaction(
                    lot_id=lot.id,
                    transaction_type="consume",
                    quantity=-taken,  # negative = out
                    reference_type="production_worksheet",
                    reference_id=worksheet_id,
                    reason=f"Production worksheet {worksheet_id} close",
                    created_by=current_user.user_id,
                )
            )
            remaining -= taken

        consumed_by_product[line.product_id] += close_line.actual_quantity

    # 6. Audit, then one commit for the whole close.
    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="production_worksheet_closed",
        entity_type="production_worksheet",
        entity_id=worksheet_id,
        details={"consumed_by_product": dict(consumed_by_product)},
    )

    # Read the response data inside the same transaction: doing it after the commit would open a
    # second transaction purely to render a reply, and it must happen before ws is touched below
    # (a query autoflushes, and a dirty ws would emit a stray UPDATE).
    products_by_id = await _load_products(db, {line.product_id for line in lines})

    await db.commit()

    # ws still holds its pre-guard values (the UPDATE ran with synchronize_session=False), so the
    # three fields the guard changed are restated here rather than re-read.
    ws.status = "closed"
    ws.version = body.expected_version + 1
    ws.closed_at = now

    return _worksheet_response(ws, lines, products_by_id)
