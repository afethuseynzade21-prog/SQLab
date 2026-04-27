"""
Evaluations Router — sorğu keyfiyyəti qiymətləndirməsi
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import EvaluationResult
from schemas.schemas import EvaluationCreate, EvaluationResponse

router = APIRouter()


@router.post("/", response_model=EvaluationResponse, status_code=201,
             summary="Sorğu qiymətləndir")
async def create_evaluation(
    body: EvaluationCreate,
    db: AsyncSession = Depends(get_db),
) -> EvaluationResponse:
    """
    LLM-as-judge pipeline tərəfindən çağırılır.
    Hər query_log üçün yalnız bir evaluation ola bilər.
    """
    existing = await db.execute(
        select(EvaluationResult).where(EvaluationResult.query_log_id == body.query_log_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu sorğu artıq qiymətləndirilib")
    ev = EvaluationResult(**body.model_dump())
    db.add(ev)
    await db.flush()
    await db.refresh(ev)
    return EvaluationResponse.model_validate(ev)


@router.get("/", response_model=list[EvaluationResponse],
            summary="Qiymətləndirmə nəticələri (filtr)")
async def list_evaluations(
    functional_correct: Optional[bool]  = Query(None),
    min_judge_score:    Optional[float] = Query(None, ge=0.0, le=1.0),
    judge_model:        Optional[str]   = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationResponse]:
    q = select(EvaluationResult)
    if functional_correct is not None:
        q = q.where(EvaluationResult.functional_correct == functional_correct)
    if min_judge_score is not None:
        q = q.where(EvaluationResult.llm_judge_score >= min_judge_score)
    if judge_model:
        q = q.where(EvaluationResult.judge_model == judge_model)
    q = q.order_by(EvaluationResult.evaluated_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    return [EvaluationResponse.model_validate(r) for r in result.scalars().all()]


@router.get("/{eval_id}", response_model=EvaluationResponse,
            summary="Bir qiymətləndirmə")
async def get_evaluation(
    eval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EvaluationResponse:
    result = await db.execute(
        select(EvaluationResult).where(EvaluationResult.id == eval_id)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Qiymətləndirmə tapılmadı")
    return EvaluationResponse.model_validate(ev)
