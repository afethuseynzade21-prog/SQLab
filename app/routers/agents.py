"""
Agent Configs Router — agent parametrləri idarəsi
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import AgentConfig
from schemas.schemas import AgentConfigCreate, AgentConfigResponse

router = APIRouter()


@router.post("/", response_model=AgentConfigResponse, status_code=201,
             summary="Yeni agent konfiqurasiyası")
async def create_agent(
    body: AgentConfigCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentConfigResponse:
    agent = AgentConfig(**body.model_dump())
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return AgentConfigResponse.model_validate(agent)


@router.get("/", response_model=list[AgentConfigResponse],
            summary="Bütün agent konfiqurasiyaları")
async def list_agents(db: AsyncSession = Depends(get_db)) -> list[AgentConfigResponse]:
    result = await db.execute(
        select(AgentConfig).order_by(AgentConfig.created_at.desc())
    )
    return [AgentConfigResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/{agent_id}", response_model=AgentConfigResponse,
            summary="Bir agent konfiqurasiyası")
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AgentConfigResponse:
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent tapılmadı")
    return AgentConfigResponse.model_validate(agent)
