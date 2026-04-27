from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import engine, Base
from routers import sessions, queries, approvals, security, evaluations, agents
from routers import chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="SQL Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agent configs"])
app.include_router(sessions.router,    prefix="/api/v1/sessions",    tags=["Sessions"])
app.include_router(queries.router,     prefix="/api/v1/queries",     tags=["Query logs"])
app.include_router(approvals.router,   prefix="/api/v1/approvals",   tags=["Human approvals"])
app.include_router(security.router,    prefix="/api/v1/security",    tags=["Security logs"])
app.include_router(evaluations.router, prefix="/api/v1/evaluations", tags=["Evaluations"])
app.include_router(chat.router, prefix="/api/v1/agent", tags=["Agent chat"])


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}