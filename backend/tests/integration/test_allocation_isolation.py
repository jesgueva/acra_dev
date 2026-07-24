"""
Integration test — material allocation against a real Postgres transaction (ACR-21).

`allocate_materials` opens with `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`. Postgres only
accepts that as the *first* statement of a transaction, and in a real request the
`require_privilege` dependency has already run three lookups on the same session — so the SET
raised `ActiveSQLTransactionError` and every allocation returned 500.

`tests/test_allocation.py` cannot catch this: it stubs the session and no-ops the SET entirely
(see its `_noop` handler). Only a live connection reproduces it, which is what this does.
"""
import os
from contextlib import asynccontextmanager
from datetime import date

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.audit import AuditLog
from app.models.contact import Contact  # noqa: F401 — registers products.contact_id's FK target
from app.models.inventory import InventoryLot, LotStatus
from app.models.product import Product
from app.models.user import User
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from app.services import allocation_service

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
)

MATERIAL_NAME = "ACR-21 Allocation Fixture"
LOT_QTY = 1000          # ×100 → 10.00 units
REQUIRED = 4.0


@asynccontextmanager
async def seeded_work_order():
    """A `created` work order needing one material, with stock to satisfy it."""
    engine = create_async_engine(DATABASE_URL)
    session = AsyncSession(engine, expire_on_commit=False)
    product_id = wo_id = None
    try:
        user_id = (
            await session.execute(select(User.id).order_by(User.id).limit(1))
        ).scalar()

        product = Product(name=MATERIAL_NAME, category="raw")
        session.add(product)
        await session.flush()
        product_id = product.id

        session.add(
            InventoryLot(
                product_id=product_id,
                lot_number="ACR21-ALLOC-0001",
                status=LotStatus.IN_STORAGE.value,
                quantity_on_hand=LOT_QTY,
                storage_location="RACK-21",
            )
        )

        wo = WorkOrder(
            product=MATERIAL_NAME,
            status="created",
            priority="medium",
            display_sequence=0,
            quantity_required=REQUIRED,
            quantity_produced=0,
            target_date=date(2026, 12, 31),
            created_by=user_id,
        )
        session.add(wo)
        await session.flush()
        wo_id = wo.id

        session.add(
            WorkOrderMaterial(
                work_order_id=wo_id,
                material_type=MATERIAL_NAME,
                quantity_required=REQUIRED,
                quantity_allocated=0,
            )
        )
        await session.commit()

        yield session, wo_id, product_id, user_id
    finally:
        await session.rollback()
        if wo_id is not None:
            mat_ids = (
                await session.execute(
                    select(WorkOrderMaterial.id).where(
                        WorkOrderMaterial.work_order_id == wo_id
                    )
                )
            ).scalars().all()
            if mat_ids:
                await session.execute(
                    delete(MaterialAllocation).where(
                        MaterialAllocation.work_order_material_id.in_(mat_ids)
                    )
                )
            await session.execute(
                delete(WorkOrderMaterial).where(
                    WorkOrderMaterial.work_order_id == wo_id
                )
            )
            await session.execute(
                delete(AuditLog).where(
                    AuditLog.entity_type == "work_order", AuditLog.entity_id == wo_id
                )
            )
            await session.execute(delete(WorkOrder).where(WorkOrder.id == wo_id))
        if product_id is not None:
            await session.execute(
                delete(InventoryLot).where(InventoryLot.product_id == product_id)
            )
            await session.execute(delete(Product).where(Product.id == product_id))
        await session.commit()
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_allocation_succeeds_on_a_session_that_already_ran_queries():
    """The regression: reads before allocation must not make the isolation-level SET fail."""
    async with seeded_work_order() as (session, wo_id, product_id, user_id):
        # Stand in for `require_privilege`, which issues exactly three lookups (user, roles,
        # privileges) on this session before any service code runs — that is what opens the
        # transaction and used to poison the SET.
        await session.execute(select(User).where(User.id == user_id))
        await session.execute(select(User.id))
        await session.execute(select(User.username))

        response = await allocation_service.allocate_materials(
            db=session, wo_id=wo_id, user_id=user_id
        )
        await session.commit()

        assert response.status == "materials_allocated"

        # Stock moved and an allocation row was written. The *amount* is deliberately not asserted
        # here: `WorkOrderMaterial.quantity_required` is in display units while
        # `InventoryLot.quantity_on_hand` is stored ×100, and `allocate_materials` subtracts one
        # from the other directly — so a 4-unit requirement removes 4 hundredths, not 4 units.
        # That unit mismatch is a real defect, but reconciling the two scales is a domain decision
        # spanning the work-order and inventory contracts, so it is reported rather than changed
        # here. Pinning the current number would only cement the bug.
        remaining = (
            await session.execute(
                select(InventoryLot.quantity_on_hand).where(
                    InventoryLot.product_id == product_id
                )
            )
        ).scalar()
        assert remaining < LOT_QTY, "allocation must consume stock"

        allocations = (
            await session.execute(
                select(MaterialAllocation).join(
                    WorkOrderMaterial,
                    MaterialAllocation.work_order_material_id == WorkOrderMaterial.id,
                ).where(WorkOrderMaterial.work_order_id == wo_id)
            )
        ).scalars().all()
        assert len(allocations) == 1
        assert LOT_QTY - remaining == pytest.approx(
            float(allocations[0].quantity_allocated)
        ), "the ledger and the allocation record must agree with each other"
