from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.audit import PaginatedAuditLogs
from app.schemas.auth import TokenUser
from app.services import audit_service

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit"])


@router.get("", response_model=PaginatedAuditLogs)
async def list_audit_logs(
    user_id: int | None = Query(None),
    action: str | None = Query(None),
    entity_type: str | None = Query(None),
    entity_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    current_user: TokenUser = Depends(require_privilege("audit.view")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedAuditLogs:
    return await audit_service.list_audit_logs(
        db=db,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
