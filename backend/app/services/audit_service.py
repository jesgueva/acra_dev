from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.schemas.audit import AuditLogResponse, PaginatedAuditLogs


async def list_audit_logs(
    db: AsyncSession,
    user_id: int | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedAuditLogs:
    q = select(AuditLog)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if action is not None:
        q = q.where(AuditLog.action == action)
    if entity_type is not None:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    if date_from is not None:
        q = q.where(AuditLog.timestamp >= date_from)
    if date_to is not None:
        q = q.where(AuditLog.timestamp <= date_to)

    count_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_res.scalar() or 0

    offset = (page - 1) * page_size
    rows_res = await db.execute(q.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size))
    rows = rows_res.scalars().all()

    return PaginatedAuditLogs(
        total=total,
        page=page,
        page_size=page_size,
        results=[AuditLogResponse.model_validate(r) for r in rows],
    )
