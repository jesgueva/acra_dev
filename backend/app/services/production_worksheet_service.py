"""Production worksheet service — creation, read, and the concurrency-safe close (ACR-30).

``close_worksheet`` is the point of this module; everything else exists to give it something to
close. See its docstring for the protocol and why it is shaped that way.
"""

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
                product_name=(
                    products_by_id[line.product_id].name
                    if line.product_id in products_by_id
                    else None
                ),
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
