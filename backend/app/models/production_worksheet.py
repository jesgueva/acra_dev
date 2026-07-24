"""Production worksheet — the minimal close surface the ACR-30 concurrency spike protects.

Only the columns the concurrency-safe close protocol needs. ACR-29 (create-from-WO + reserve)
extends these additively; it does not have to undo anything here.

``ProductionWorksheet.version`` is the optimistic guard. It is never incremented in Python —
the close issues one conditional UPDATE and reads ``rowcount`` (see
``services/production_worksheet_service.close_worksheet``), so two concurrent closers cannot both
believe they won.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


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
        Integer,
        ForeignKey("production_worksheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    planned_quantity = Column(Integer, nullable=False)   # ×100
    actual_quantity = Column(Integer, nullable=True)     # ×100, set at close

    __table_args__ = (
        CheckConstraint("planned_quantity > 0", name="ck_pwl_planned_qty"),
        CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_pwl_actual_qty",
        ),
    )
