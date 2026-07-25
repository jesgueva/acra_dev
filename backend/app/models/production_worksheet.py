"""Production worksheet — the minimal shape the ACR-30 close spike needs.

A worksheet holds the material lines a production run consumes. Closing it is the operation
RSK-01 is about: two operators (or one double-click) must not be able to decrement the same stock
twice.

``ProductionWorksheet.version`` is the optimistic guard. The close does not read-then-check it; it
issues a single ``UPDATE ... WHERE id = :id AND version = :expected AND status <> 'closed'`` and
treats ``rowcount != 1`` as "someone else got there first". See
``app.services.production_worksheet_service.close_worksheet``.

Scope note: lines key on ``product_id`` only — no ``state`` column. Stock is drawn from
``inventory_lots``, so this spike does not depend on the ``StockState`` vocabulary (ACR-26) or on
reservations (ACR-27). ACR-29 extends these tables; it does not have to undo them.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base

# Statuses a worksheet can hold. ACR-29 adds 'reserved' when reservations land.
WORKSHEET_STATUSES = ("draft", "in_progress", "closed")


class ProductionWorksheet(Base):
    __tablename__ = "production_worksheets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    production_line = Column(String(100), nullable=True)
    scheduled_date = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, server_default="draft")
    version = Column(Integer, nullable=False, server_default="0")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'in_progress', 'closed')",
            name="ck_production_worksheets_status",
        ),
        CheckConstraint("version >= 0", name="ck_production_worksheets_version"),
    )


class ProductionWorksheetLine(Base):
    __tablename__ = "production_worksheet_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worksheet_id = Column(
        Integer, ForeignKey("production_worksheets.id", ondelete="CASCADE"), nullable=False
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    planned_quantity = Column(Integer, nullable=False)  # ×100
    actual_quantity = Column(Integer, nullable=True)  # ×100, set at close

    __table_args__ = (
        CheckConstraint("planned_quantity > 0", name="ck_pw_lines_planned_qty"),
        CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0", name="ck_pw_lines_actual_qty"
        ),
        Index("ix_pw_lines_worksheet", "worksheet_id"),
    )
