"""
Queries Router — SQL sorğu jurnalı + alət çağırışları

Endpoint-lər:
  POST   /api/v1/queries/                     yeni sorğu qeydi
  GET    /api/v1/queries/                     filtr + səhifə
  GET    /api/v1/queries/{id}                 bir sorğu (tool_calls ilə)
  PATCH  /api/v1/queries/{id}                 status / nəticə güncəllə
  GET    /api/v1/queries/search               NL mətnə görə axtarış

  POST   /api/v1/queries/{id}/tool-calls      alət çağırışı qeyd et
  GET    /api/v1/queries/{id}/tool-calls      sorğunun bütün alət çağırışları

  GET    /api/v1/queries/stats                sessiya / agent statistikası
"""

import uuid
import sqlalchemy as sa
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db
from models import QueryLog, ToolCall
from schemas.schemas import (
    QueryLogCreate, QueryLogUpdate, QueryLogResponse,
    ToolCallCreate, ToolCallResponse,
)

router = APIRouter()


# ════════════════════════════════════════════════════════════════
#  QUERY LOGS
# ════════════════════════════════════════════════════════════════

@router.post(
    "/",
    response_model=QueryLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni sorğu qeydi yarat",
)
async def create_query_log(
    body: QueryLogCreate,
    db: AsyncSession = Depends(get_db),
) -> QueryLogResponse:
    log = QueryLog(**body.model_dump())
    db.add(log)
    await db.flush()
    await db.refresh(log)
    return QueryLogResponse.model_validate(log)


@router.get(
    "/",
    response_model=list[QueryLogResponse],
    summary="Sorğu siyahısı (filtr + səhifə)",
)
async def list_query_logs(
    session_id: Optional[uuid.UUID] = Query(None),
    query_status: Optional[str]     = Query(None, alias="status",
                                            description="success | error | blocked | pending_approval"),
    page: int  = Query(1, ge=1),
    size: int  = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[QueryLogResponse]:
    q = select(QueryLog)
    if session_id:
        q = q.where(QueryLog.session_id == session_id)
    if query_status:
        q = q.where(QueryLog.status == query_status)
    q = q.order_by(QueryLog.executed_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    return [QueryLogResponse.model_validate(r) for r in result.scalars().all()]


@router.get(
    "/search",
    response_model=list[QueryLogResponse],
    summary="Təbii dil mətnə görə axtarış (pg_trgm)",
)
async def search_queries(
    q: str = Query(..., min_length=2, description="Axtarış mətni"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[QueryLogResponse]:
    """
    pg_trgm trigram oxşarlığına əsasən nl_input və sql_query arasında axtarış.
    Misal: /search?q=ən+çox+satılan
    """
    stmt = (
        select(QueryLog)
        .where(
            or_(
                QueryLog.nl_input.ilike(f"%{q}%"),
                QueryLog.sql_query.ilike(f"%{q}%"),
            )
        )
        .order_by(QueryLog.executed_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [QueryLogResponse.model_validate(r) for r in result.scalars().all()]


@router.get(
    "/stats",
    summary="Sorğu statistikası",
)
async def query_stats(
    session_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    where = f"WHERE session_id = '{session_id}'" if session_id else ""
    result = await db.execute(
        sa.text(f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'SUCCESS') as success,
                COUNT(*) FILTER (WHERE status = 'ERROR') as error,
                COUNT(*) FILTER (WHERE status = 'BLOCKED') as blocked,
                COUNT(*) FILTER (WHERE status = 'PENDING_APPROVAL') as pending,
                AVG(execution_time_ms) as avg_ms,
                AVG(rows_returned) as avg_rows
            FROM query_logs {where}
        """)
    )
    row = result.one()
    total = max(row.total or 0, 1)
    return {
        "total": row.total,
        "success": row.success,
        "error": row.error,
        "blocked": row.blocked,
        "pending_approval": row.pending,
        "success_rate_pct": round(100 * (row.success / total), 1),
        "avg_execution_ms": round(row.avg_ms or 0, 1),
        "avg_rows_returned": round(row.avg_rows or 0, 1),
    }


@router.get(
    "/{query_id}",
    response_model=QueryLogResponse,
    summary="Bir sorğu qeydi",
)
async def get_query_log(
    query_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> QueryLogResponse:
    log = await _get_query_or_404(db, query_id)
    return QueryLogResponse.model_validate(log)


@router.patch(
    "/{query_id}",
    response_model=QueryLogResponse,
    summary="Sorğu nəticəsini güncəllə (agent tərəfindən çağırılır)",
)
async def update_query_log(
    query_id: uuid.UUID,
    body: QueryLogUpdate,
    db: AsyncSession = Depends(get_db),
) -> QueryLogResponse:
    """
    Agent sorğunu icra etdikdən sonra bu endpoint-i çağırır:
      • sql_query — yaradılmış SQL
      • status    — success / error / blocked
      • execution_time_ms, rows_returned, error_message
    """
    log = await _get_query_or_404(db, query_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(log, field, value)
    await db.flush()
    await db.refresh(log)
    return QueryLogResponse.model_validate(log)


# ════════════════════════════════════════════════════════════════
#  TOOL CALLS
# ════════════════════════════════════════════════════════════════

@router.post(
    "/{query_id}/tool-calls",
    response_model=ToolCallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alət çağırışı qeyd et (ReAct addımı)",
)
async def log_tool_call(
    query_id: uuid.UUID,
    body: ToolCallCreate,
    db: AsyncSession = Depends(get_db),
) -> ToolCallResponse:
    """
    ReAct dövrünün hər addımı üçün:
      tool_name: 'sql_db_query' | 'sql_db_schema' | 'sql_db_query_checker'
    """
    await _get_query_or_404(db, query_id)
    call = ToolCall(query_log_id=query_id, **body.model_dump())
    db.add(call)
    await db.flush()
    await db.refresh(call)
    return ToolCallResponse.model_validate(call)


@router.get(
    "/{query_id}/tool-calls",
    response_model=list[ToolCallResponse],
    summary="Sorğunun alət çağırışları (ReAct izi)",
)
async def list_tool_calls(
    query_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ToolCallResponse]:
    await _get_query_or_404(db, query_id)
    result = await db.execute(
        select(ToolCall)
        .where(ToolCall.query_log_id == query_id)
        .order_by(ToolCall.called_at.asc())
    )
    return [ToolCallResponse.model_validate(t) for t in result.scalars().all()]


# ── Köməkçi funksiya ─────────────────────────────────────────

async def _get_query_or_404(db: AsyncSession, query_id: uuid.UUID) -> QueryLog:
    result = await db.execute(select(QueryLog).where(QueryLog.id == query_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail=f"Sorğu tapılmadı: {query_id}")
    return log
