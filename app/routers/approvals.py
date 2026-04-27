"""
Human Approvals Router — insan təsdiqi idarəsi

Endpoint-lər:
  POST   /api/v1/approvals/           yeni təsdiq sorğusu
  GET    /api/v1/approvals/pending    gözləyən sorğular (admin paneli)
  GET    /api/v1/approvals/{id}       bir sorğu
  PATCH  /api/v1/approvals/{id}/decide  qərar ver (approve / reject)
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from core.database import get_db
from models import HumanApproval
from schemas.schemas import (
    ApprovalCreate, ApprovalDecision, ApprovalResponse,
)

router = APIRouter()


@router.post(
    "/",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni insan təsdiqi sorğusu yarat",
)
async def create_approval(
    body: ApprovalCreate,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """
    Agent kritik sorğu icra etməzdən əvvəl bunu çağırır.
    Status: 'pending' — admin qərar verənə qədər agent gözləyir.
    """
    # Eyni query_log üçün ikinci approval yaratmağa icazə vermə
    existing = await db.execute(
        select(HumanApproval).where(HumanApproval.query_log_id == body.query_log_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Bu sorğu üçün artıq təsdiq sorğusu mövcuddur",
        )
    approval = HumanApproval(**body.model_dump())
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return ApprovalResponse.model_validate(approval)


@router.get(
    "/pending",
    response_model=list[ApprovalResponse],
    summary="Gözləyən təsdiq sorğuları (admin paneli)",
)
async def list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalResponse]:
    """Ən köhnə pending sorğu əvvəl görsənir."""
    result = await db.execute(
        select(HumanApproval)
        .where(HumanApproval.status == "pending")
        .order_by(HumanApproval.requested_at.asc())
        .limit(limit)
    )
    return [ApprovalResponse.model_validate(a) for a in result.scalars().all()]


@router.get(
    "/{approval_id}",
    response_model=ApprovalResponse,
    summary="Bir təsdiq sorğusu",
)
async def get_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    approval = await _get_or_404(db, approval_id)
    return ApprovalResponse.model_validate(approval)


@router.patch(
    "/{approval_id}/decide",
    response_model=ApprovalResponse,
    summary="Qərar ver: approve / reject",
)
async def decide_approval(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """
    Admin bu endpoint-i çağırır.
    status: 'approved' → agent sorğunu icra edir
    status: 'rejected' → agent query_log-u blocked kimi qeyd edir
    """
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="status: 'approved' və ya 'rejected' olmalıdır")

    approval = await _get_or_404(db, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Bu sorğu artıq həll edilib")

    approval.status = body.status
    approval.approver_id = body.approver_id
    approval.reason = body.reason
    approval.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(approval)
    return ApprovalResponse.model_validate(approval)


async def _get_or_404(db: AsyncSession, approval_id: uuid.UUID) -> HumanApproval:
    result = await db.execute(
        select(HumanApproval).where(HumanApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail=f"Təsdiq tapılmadı: {approval_id}")
    return approval
