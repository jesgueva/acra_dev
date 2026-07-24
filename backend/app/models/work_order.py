from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Integer, Numeric, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product = Column(String(200), nullable=False)
    quantity_required = Column(Numeric(12, 3), nullable=False)
    quantity_produced = Column(Numeric(12, 3), nullable=False, server_default="0")
    priority = Column(String(20), nullable=False, server_default="medium")
    display_sequence = Column(Integer, nullable=False, server_default="0")
    status = Column(String(30), nullable=False, server_default="created")
    target_date = Column(Date, nullable=False)
    production_line = Column(String(50), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity_required > 0", name="ck_work_orders_qty_required"),
        CheckConstraint("quantity_produced >= 0", name="ck_work_orders_qty_produced"),
        CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_work_orders_priority"),
        CheckConstraint(
            "status IN ('created', 'materials_allocated', 'in_production', 'completed', 'ready_for_shipment')",
            name="ck_work_orders_status",
        ),
    )


class WorkOrderMaterial(Base):
    __tablename__ = "work_order_materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    material_type = Column(String(200), nullable=False)
    quantity_required = Column(Numeric(12, 3), nullable=False)
    quantity_allocated = Column(Numeric(12, 3), nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("quantity_required > 0", name="ck_wom_qty_required"),
        CheckConstraint("quantity_allocated >= 0", name="ck_wom_qty_allocated"),
    )


class MaterialAllocation(Base):
    __tablename__ = "material_allocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_material_id = Column(Integer, ForeignKey("work_order_materials.id", ondelete="CASCADE"), nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventory_lots.id"), nullable=False)
    lot_batch_number = Column(String(100), nullable=False)
    quantity_allocated = Column(Numeric(12, 3), nullable=False)
    allocated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity_allocated > 0", name="ck_material_allocations_qty"),
    )
