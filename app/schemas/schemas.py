"""
Pydantic v2 sxemləri — request/response validasiyası

Hər entity üçün üç sxem:
  • Base     — ortaq sahələr
  • Create   → POST body
  • Response ← GET/POST/PATCH cavabı
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Ortaq konfiqurasiya ───────────────────────────────────────

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ════════════════════════════════════════════════════════════════
#  AGENT CONFIGS
# ════════════════════════════════════════════════════════════════

class AgentConfigCreate(_Base):
    name: str                        = Field(..., max_length=120, example="Prod Agent v1")
    llm_model: str                   = Field(..., max_length=80,  example="claude-sonnet-4-5")
    framework: str                   = Field("langchain",          example="langchain")
    db_connection_string: str        = Field(..., example="postgresql://...")
    max_iterations: int              = Field(10, ge=1, le=50)
    read_only: bool                  = Field(True)
    description: Optional[str]       = None


class AgentConfigResponse(_Base):
    id: uuid.UUID
    name: str
    llm_model: str
    framework: str
    max_iterations: int
    read_only: bool
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    # db_connection_string response-a daxil deyil (təhlükəsizlik)


# ════════════════════════════════════════════════════════════════
#  SESSIONS
# ════════════════════════════════════════════════════════════════

class SessionCreate(_Base):
    agent_config_id: uuid.UUID
    user_id: str             = Field(..., max_length=100, example="user_001")
    title: Optional[str]     = Field(None, max_length=200, example="Satış analizi")
    metadata: Optional[dict] = None


class SessionUpdate(_Base):
    title: Optional[str]  = None
    status: Optional[str] = None


class SessionResponse(_Base):
    id: uuid.UUID
    agent_config_id: uuid.UUID
    user_id: str
    title: Optional[str]
    status: str
    metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime


class SessionListResponse(_Base):
    items: list[SessionResponse]
    total: int
    page: int
    size: int


# ════════════════════════════════════════════════════════════════
#  MESSAGES
# ════════════════════════════════════════════════════════════════

class MessageCreate(_Base):
    role: str        = Field(..., example="user")
    content: str     = Field(..., example="Ən çox satılan 5 məhsulu göstər")
    tokens_used: Optional[int] = None
    metadata: Optional[dict]   = None


class MessageResponse(_Base):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    tokens_used: Optional[int]
    created_at: datetime


# ════════════════════════════════════════════════════════════════
#  QUERY LOGS
# ════════════════════════════════════════════════════════════════

class QueryLogCreate(_Base):
    session_id: uuid.UUID
    message_id: Optional[uuid.UUID] = None
    nl_input: str                   = Field(..., example="Ən çox satılan 5 məhsulu göstər")
    sql_query: Optional[str]        = None
    status: str                     = Field("pending_approval")


class QueryLogUpdate(_Base):
    sql_query: Optional[str]        = None
    status: Optional[str]           = None
    execution_time_ms: Optional[int] = None
    rows_returned: Optional[int]    = None
    error_message: Optional[str]    = None


class QueryLogResponse(_Base):
    id: uuid.UUID
    session_id: uuid.UUID
    message_id: Optional[uuid.UUID]
    nl_input: str
    sql_query: Optional[str]
    status: str
    execution_time_ms: Optional[int]
    rows_returned: Optional[int]
    error_message: Optional[str]
    executed_at: datetime


# ════════════════════════════════════════════════════════════════
#  TOOL CALLS
# ════════════════════════════════════════════════════════════════

class ToolCallCreate(_Base):
    tool_name: str             = Field(..., example="sql_db_query")
    input_params: dict         = Field(default_factory=dict)
    output: Optional[str]      = None
    duration_ms: Optional[int] = None
    success: bool              = False


class ToolCallResponse(_Base):
    id: uuid.UUID
    query_log_id: uuid.UUID
    tool_name: str
    input_params: dict
    output: Optional[str]
    duration_ms: Optional[int]
    success: bool
    called_at: datetime


# ════════════════════════════════════════════════════════════════
#  SECURITY LOGS
# ════════════════════════════════════════════════════════════════

class SecurityLogCreate(_Base):
    session_id: uuid.UUID
    event_type: str              = Field(..., example="prompt_injection")
    input_text: str
    detection_model: Optional[str] = Field(None, example="deberta-v3")
    risk_score: Optional[float]    = Field(None, ge=0.0, le=1.0)
    action_taken: Optional[str]    = Field(None, example="blocked")


class SecurityLogResponse(_Base):
    id: uuid.UUID
    session_id: uuid.UUID
    event_type: str
    input_text: str
    detection_model: Optional[str]
    risk_score: Optional[float]
    action_taken: Optional[str]
    created_at: datetime


# ════════════════════════════════════════════════════════════════
#  HUMAN APPROVALS
# ════════════════════════════════════════════════════════════════

class ApprovalCreate(_Base):
    query_log_id: uuid.UUID
    approver_id: Optional[str] = None


class ApprovalDecision(_Base):
    """Admin-in qərar verməsi üçün."""
    approver_id: str
    status: str   = Field(..., example="approved")  # approved | rejected
    reason: Optional[str] = None


class ApprovalResponse(_Base):
    id: uuid.UUID
    query_log_id: uuid.UUID
    approver_id: Optional[str]
    status: str
    reason: Optional[str]
    requested_at: datetime
    resolved_at: Optional[datetime]


# ════════════════════════════════════════════════════════════════
#  EVALUATION RESULTS
# ════════════════════════════════════════════════════════════════

class EvaluationCreate(_Base):
    query_log_id: uuid.UUID
    functional_correct: Optional[bool]    = None
    semantic_similarity: Optional[float]  = Field(None, ge=0.0, le=1.0)
    llm_judge_score: Optional[float]      = Field(None, ge=0.0, le=1.0)
    ground_truth_query: Optional[str]     = None
    judge_model: Optional[str]            = Field(None, example="claude-opus-4-6")
    notes: Optional[str]                  = None


class EvaluationResponse(_Base):
    id: uuid.UUID
    query_log_id: uuid.UUID
    functional_correct: Optional[bool]
    semantic_similarity: Optional[float]
    llm_judge_score: Optional[float]
    ground_truth_query: Optional[str]
    judge_model: Optional[str]
    notes: Optional[str]
    evaluated_at: datetime


# ════════════════════════════════════════════════════════════════
#  MEMORY SUMMARIES
# ════════════════════════════════════════════════════════════════

class MemorySummaryUpsert(_Base):
    summary_text: str
    recent_messages: list[Any] = Field(default_factory=list)
    token_count: int = 0


class MemorySummaryResponse(_Base):
    id: uuid.UUID
    session_id: uuid.UUID
    summary_text: str
    recent_messages: list[Any]
    token_count: int
    updated_at: datetime


# ════════════════════════════════════════════════════════════════
#  ÜMUMI
# ════════════════════════════════════════════════════════════════

class ErrorResponse(_Base):
    detail: str


class SuccessResponse(_Base):
    message: str
