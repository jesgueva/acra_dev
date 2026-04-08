from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    preferred_language = Column(String(10), nullable=False, server_default="en")
    status = Column(String(20), nullable=False, server_default="active")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
    )


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    assigned_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier = Column(String(200), nullable=False)
    carrier = Column(String(200), nullable=False)
    delivery_date = Column(Date, nullable=False)
    bol_reference = Column(String(100), nullable=False, unique=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_type = Column(String(200), nullable=False)
    category = Column(String(20), nullable=False)
    quantity_on_hand = Column(Numeric(12, 3), nullable=False, server_default="0")
    lot_batch_number = Column(String(100), nullable=False)
    storage_location = Column(String(100), nullable=False)
    source_delivery_item_id = Column(
        Integer,
        ForeignKey("delivery_items.id", use_alter=True, name="fk_inventory_items_source_delivery"),
        nullable=True,
    )
    last_updated = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("category IN ('raw', 'finished')", name="ck_inventory_items_category"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_items_qty"),
    )


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False)
    material_type = Column(String(200), nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    lot_batch_number = Column(String(100), nullable=False)
    storage_location = Column(String(100), nullable=False)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_delivery_items_quantity"),
    )


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
    inventory_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False)
    lot_batch_number = Column(String(100), nullable=False)
    quantity_allocated = Column(Numeric(12, 3), nullable=False)
    allocated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("quantity_allocated > 0", name="ck_material_allocations_qty"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(JSON, nullable=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class LowStockAlert(Base):
    __tablename__ = "low_stock_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_type = Column(String(200), nullable=False, unique=True)
    threshold = Column(Numeric(12, 3), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("threshold >= 0", name="ck_low_stock_alerts_threshold"),
    )
