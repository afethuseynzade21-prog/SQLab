"""
Sessions Router — söhbət sessiyaları idarəsi

Endpoint-lər:
  POST   /api/v1/sessions/                    yeni sessiya
  GET    /api/v1/sessions/                    sessiya siyahısı (filtr + səhifə)
  GET    /api/v1/sessions/{id}                bir sessiya
  PATCH  /api/v1/sessions/{id}                statusu/başlığı dəyişdirmə
  DELETE /api/v1/sessions/{id}                sessiyanı bağla (soft close)

  POST   /api/v1/sessions/{id}/messages       mesaj əlavə et
  GET    /api/v1/sessions/{id}/messages       sessiya mesajları

  GET    /api/v1/sessions/{id}/memory         yaddaş xülasəsi
  PUT    /api/v1/sessions/{id}/memory         yaddaşı güncəllə (upsert)
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import Session, Message, MemorySummary
from schemas.schemas import (
    SessionCreate, SessionUpdate, SessionResponse, SessionListResponse,
    MessageCreate, MessageResponse,
    MemorySummaryUpsert, MemorySummaryResponse,
)

router = APIRouter()


# ════════════════════════════════════════════════════════════════
#  SESSIONS CRUD
# ════════════════════════════════════════════════════════════════

@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni sessiya yarat",
)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    session = Session(**body.model_dump())
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return SessionResponse.model_validate(session)


@router.get(
    "/",
    response_model=SessionListResponse,
    summary="Sessiya siyahısı",
)
async def list_sessions(
    user_id: Optional[str] = Query(None, description="İstifadəçiyə görə filtr"),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    q = select(Session)
    if user_id:
        q = q.where(Session.user_id == user_id)
    if status_filter:
        q = q.where(Session.status == status_filter)

    total_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_res.scalar_one()

    q = q.order_by(Session.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    items = [SessionResponse.model_validate(s) for s in result.scalars().all()]

    return SessionListResponse(items=items, total=total, page=page, size=size)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Bir sessiya",
)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    session = await _get_or_404(db, session_id)
    return SessionResponse.model_validate(session)


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Sessiyanı güncəllə (başlıq / status)",
)
async def update_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    session = await _get_or_404(db, session_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(session, field, value)
    await db.flush()
    await db.refresh(session)
    return SessionResponse.model_validate(session)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sessiyanı bağla (soft delete)",
)
async def close_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Sessiyanı silmir — statusunu 'closed' edir.
    Audit jurnalı qorunur.
    """
    session = await _get_or_404(db, session_id)
    session.status = "closed"
    await db.flush()


# ════════════════════════════════════════════════════════════════
#  MESSAGES
# ════════════════════════════════════════════════════════════════

@router.post(
    "/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Sessiyaya mesaj əlavə et",
)
async def add_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await _get_or_404(db, session_id)
    msg = Message(session_id=session_id, **body.model_dump())
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    return MessageResponse.model_validate(msg)


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
    summary="Sessiya mesajları (xronoloji)",
)
async def list_messages(
    session_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    await _get_or_404(db, session_id)
    q = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(q)
    return [MessageResponse.model_validate(m) for m in result.scalars().all()]


# ════════════════════════════════════════════════════════════════
#  MEMORY SUMMARIES
# ════════════════════════════════════════════════════════════════

@router.get(
    "/{session_id}/memory",
    response_model=MemorySummaryResponse,
    summary="Sessiyanın yaddaş xülasəsi",
)
async def get_memory(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemorySummaryResponse:
    await _get_or_404(db, session_id)
    result = await db.execute(
        select(MemorySummary).where(MemorySummary.session_id == session_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Bu sessiya üçün yaddaş tapılmadı")
    return MemorySummaryResponse.model_validate(memory)


@router.put(
    "/{session_id}/memory",
    response_model=MemorySummaryResponse,
    summary="Yaddaşı güncəllə (upsert)",
)
async def upsert_memory(
    session_id: uuid.UUID,
    body: MemorySummaryUpsert,
    db: AsyncSession = Depends(get_db),
) -> MemorySummaryResponse:
    """
    Yaddaş mövcuddursa güncəllər, yoxdursa yeni yaradır.
    ConversationSummaryBufferMemory hər döngüdən sonra bunu çağırır.
    """
    await _get_or_404(db, session_id)
    result = await db.execute(
        select(MemorySummary).where(MemorySummary.session_id == session_id)
    )
    memory = result.scalar_one_or_none()

    if memory:
        memory.summary_text = body.summary_text
        memory.recent_messages = body.recent_messages
        memory.token_count = body.token_count
    else:
        memory = MemorySummary(session_id=session_id, **body.model_dump())
        db.add(memory)

    await db.flush()
    await db.refresh(memory)
    return MemorySummaryResponse.model_validate(memory)


# ── Köməkçi funksiya ─────────────────────────────────────────

async def _get_or_404(db: AsyncSession, session_id: uuid.UUID) -> Session:
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessiya tapılmadı: {session_id}")
    return session
