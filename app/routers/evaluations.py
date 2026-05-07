import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db

router = APIRouter()

class EvaluationResponse(BaseModel):
    id: str
    query_log_id: Optional[str]
    llm_judge_score: Optional[int]
    judge_model: Optional[str]
    notes: Optional[str]
    evaluated_at: Optional[str]

@router.get("", summary="Qiymetlendirmeler siyahisi")
async def list_evaluations(
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text(
        "SELECT id::text, query_log_id::text, llm_judge_score, judge_model, notes, evaluated_at::text "
        "FROM evaluations ORDER BY evaluated_at DESC LIMIT :size"
    ), {"size": size})
    rows = result.fetchall()
    return [
        {
            "id": r[0], "query_log_id": r[1], "llm_judge_score": r[2],
            "judge_model": r[3], "notes": r[4], "evaluated_at": r[5]
        }
        for r in rows
    ]

@router.get("/stats", summary="Qiymetlendirme statistikasi")
async def eval_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT COUNT(*), ROUND(AVG(llm_judge_score)::numeric, 2), MIN(llm_judge_score), MAX(llm_judge_score) FROM evaluations"
    ))
    r = result.fetchone()
    return {"total": r[0], "avg_score": float(r[1]) if r[1] else 0, "min": r[2], "max": r[3]}
