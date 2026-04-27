"""
Security Logs Router
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import SecurityLog
from schemas.schemas import SecurityLogCreate, SecurityLogResponse

router = APIRouter()


@router.post("/", response_model=SecurityLogResponse, status_code=201,
             summary="Təhlükəsizlik hadisəsi qeyd et")
async def log_security_event(
    body: SecurityLogCreate,
    db: AsyncSession = Depends(get_db),
) -> SecurityLogResponse:
    """
    DeBERTa filter və ya digər mexanizm tərəfindən çağırılır.
    event_type: prompt_injection | forbidden_operation | rate_limit | blocked_query
    """
    event = SecurityLog(**body.model_dump())
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return SecurityLogResponse.model_validate(event)


@router.get("/", response_model=list[SecurityLogResponse],
            summary="Təhlükəsizlik hadisələri (filtr)")
async def list_security_logs(
    session_id: Optional[uuid.UUID] = Query(None),
    event_type: Optional[str]       = Query(None),
    min_risk:   Optional[float]     = Query(None, ge=0.0, le=1.0,
                                            description="Minimum risk balı"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[SecurityLogResponse]:
    q = select(SecurityLog)
    if session_id:
        q = q.where(SecurityLog.session_id == session_id)
    if event_type:
        q = q.where(SecurityLog.event_type == event_type)
    if min_risk is not None:
        q = q.where(SecurityLog.risk_score >= min_risk)
    q = q.order_by(SecurityLog.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    return [SecurityLogResponse.model_validate(r) for r in result.scalars().all()]
