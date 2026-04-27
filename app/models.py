"""
SQL Agent Sistemi — SQLAlchemy ORM Modelləri
Arxitektura: ReAct paradigması (Mülahizə + Hərəkət + Müşahidə)
Python 3.11+ | SQLAlchemy 2.0 | PostgreSQL
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, Float,
    ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ────────────────────────────────────────────────────────────
#  BASE CLASS
# ────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ────────────────────────────────────────────────────────────
#  ENUM TİPLƏR
# ────────────────────────────────────────────────────────────

class SessionStatus(str, enum.Enum):
    ACTIVE  = "ACTIVE"
    CLOSED  = "CLOSED"
    ERROR   = "ERROR"


class MessageRole(str, enum.Enum):
    USER      = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM    = "SYSTEM"
    TOOL      = "TOOL"

class QueryStatus(str, enum.Enum):
    SUCCESS          = "SUCCESS"
    ERROR            = "ERROR"
    BLOCKED          = "BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class SecurityEvent(str, enum.Enum):
    PROMPT_INJECTION    = "PROMPT_INJECTION"
    FORBIDDEN_OPERATION = "FORBIDDEN_OPERATION"
    RATE_LIMIT          = "RATE_LIMIT"
    BLOCKED_QUERY       = "BLOCKED_QUERY"


class ApprovalStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class AgentFramework(str, enum.Enum):
    LANGCHAIN = "LANGCHAIN"
    MASTRA    = "MASTRA"
    CUSTOM    = "CUSTOM"

# ────────────────────────────────────────────────────────────
#  1. AGENT_CONFIGS
# ────────────────────────────────────────────────────────────

class AgentConfig(Base):
    """
    Agent parametrləri: hansı LLM, framework, DB bağlantısı.
    Bir konfiqurasiya çoxlu sessiyalara xidmət edə bilər.
    """
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str]        = mapped_column(String(120), nullable=False)
    llm_model: Mapped[str]   = mapped_column(String(80), nullable=False)
    framework: Mapped[AgentFramework] = mapped_column(
        Enum(AgentFramework, name="agent_framework"),
        nullable=False, default=AgentFramework.LANGCHAIN,
    )
    db_connection_string: Mapped[str] = mapped_column(Text, nullable=False)
    max_iterations: Mapped[int]       = mapped_column(Integer, default=10)
    read_only: Mapped[bool]           = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # İlişkilər
    sessions: Mapped[list["Session"]] = relationship(back_populates="agent_config")

    def __repr__(self) -> str:
        return f"<AgentConfig name={self.name!r} llm={self.llm_model!r}>"


# ────────────────────────────────────────────────────────────
#  2. SESSIONS
# ────────────────────────────────────────────────────────────

class Session(Base):
    """
    İstifadəçi söhbət sessiyaları.
    Hər söhbət bir agentlə bir istifadəçi arasındakı tam dialoqdur.
    """
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_configs.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str]             = mapped_column(String(100), nullable=False)
    title: Mapped[Optional[str]]     = mapped_column(String(200))
    status: Mapped[SessionStatus]    = mapped_column(
        Enum(SessionStatus, name="session_status"), default=SessionStatus.ACTIVE
    )
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # İlişkilər
    agent_config: Mapped["AgentConfig"]          = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]]             = relationship(back_populates="session", cascade="all, delete-orphan")
    memory_summary: Mapped[Optional["MemorySummary"]] = relationship(back_populates="session", uselist=False)
    query_logs: Mapped[list["QueryLog"]]          = relationship(back_populates="session", cascade="all, delete-orphan")
    security_logs: Mapped[list["SecurityLog"]]    = relationship(back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sessions_user",   "user_id"),
        Index("idx_sessions_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} user={self.user_id!r} status={self.status}>"


# ────────────────────────────────────────────────────────────
#  3. MESSAGES
# ────────────────────────────────────────────────────────────

class Message(Base):
    """
    Sessiya daxilindəki mesajlar.
    Rol: user | assistant | system | tool
    """
    __tablename__ = "messages"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str]      = mapped_column(Text, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_: Mapped[Optional[dict]]  = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkilər
    session: Mapped["Session"]         = relationship(back_populates="messages")
    triggered_queries: Mapped[list["QueryLog"]] = relationship(back_populates="message")

    __table_args__ = (
        Index("idx_messages_session", "session_id"),
        Index("idx_messages_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message role={self.role} tokens={self.tokens_used}>"


# ────────────────────────────────────────────────────────────
#  4. MEMORY_SUMMARIES
# ────────────────────────────────────────────────────────────

class MemorySummary(Base):
    """
    ConversationSummaryBufferMemory saxlama cədvəli.
    Hər sessiyaya uyğun bir xülasə + son mesaj buferi.
    Yeni xülasə yarandıqda UPSERT istifadə edin.
    """
    __tablename__ = "memory_summaries"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    summary_text: Mapped[str]     = mapped_column(Text, nullable=False)
    recent_messages: Mapped[list] = mapped_column(JSONB, default=list)
    token_count: Mapped[int]      = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # İlişkilər
    session: Mapped["Session"] = relationship(back_populates="memory_summary")

    def __repr__(self) -> str:
        return f"<MemorySummary session={self.session_id} tokens={self.token_count}>"


# ────────────────────────────────────────────────────────────
#  5. QUERY_LOGS
# ────────────────────────────────────────────────────────────

class QueryLog(Base):
    """
    Agentin icra etdiyi bütün SQL sorğularının audit jurnalı.
    status=blocked → SecurityLog ilə əlaqəlidir.
    status=pending_approval → HumanApproval gözləyir.
    """
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    nl_input: Mapped[str]               = mapped_column(Text, nullable=False)
    sql_query: Mapped[Optional[str]]    = mapped_column(Text)
    status: Mapped[QueryStatus]         = mapped_column(
        Enum(QueryStatus, name="query_status"), default=QueryStatus.PENDING_APPROVAL
    )
    execution_time_ms: Mapped[Optional[int]]  = mapped_column(Integer)
    rows_returned: Mapped[Optional[int]]      = mapped_column(Integer)
    error_message: Mapped[Optional[str]]      = mapped_column(Text)
    executed_at: Mapped[datetime]             = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkilər
    session: Mapped["Session"]               = relationship(back_populates="query_logs")
    message: Mapped[Optional["Message"]]     = relationship(back_populates="triggered_queries")
    tool_calls: Mapped[list["ToolCall"]]     = relationship(back_populates="query_log", cascade="all, delete-orphan")
    human_approval: Mapped[Optional["HumanApproval"]]     = relationship(back_populates="query_log", uselist=False)
    evaluation_result: Mapped[Optional["EvaluationResult"]] = relationship(back_populates="query_log", uselist=False)

    __table_args__ = (
        Index("idx_query_logs_session",  "session_id"),
        Index("idx_query_logs_status",   "status"),
        Index("idx_query_logs_executed", "executed_at"),
    )

    def __repr__(self) -> str:
        preview = (self.nl_input or "")[:40]
        return f"<QueryLog status={self.status} nl={preview!r}>"


# ────────────────────────────────────────────────────────────
#  6. TOOL_CALLS
# ────────────────────────────────────────────────────────────

class ToolCall(Base):
    """
    ReAct iterasiyalarının hər addımı.
    tool_name nümunələri:
      - sql_db_query          → sorğunu icra et
      - sql_db_schema         → cədvəl strukturuna bax
      - sql_db_query_checker  → sintaksis yoxla
    """
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str]          = mapped_column(String(80), nullable=False)
    input_params: Mapped[dict]      = mapped_column(JSONB, default=dict)
    output: Mapped[Optional[str]]   = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    success: Mapped[bool]              = mapped_column(Boolean, default=False)
    called_at: Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkilər
    query_log: Mapped["QueryLog"] = relationship(back_populates="tool_calls")

    __table_args__ = (
        Index("idx_tool_calls_query",     "query_log_id"),
        Index("idx_tool_calls_tool_name", "tool_name"),
    )

    def __repr__(self) -> str:
        return f"<ToolCall tool={self.tool_name!r} success={self.success}>"


# ────────────────────────────────────────────────────────────
#  7. SECURITY_LOGS
# ────────────────────────────────────────────────────────────

class SecurityLog(Base):
    """
    Prompt injection, qadağan əməliyyat, risk balı.
    risk_score: 0.000 (təhlükəsiz) → 1.000 (yüksək risk)
    DeBERTa kimi modellər tərəfindən hesablanır.
    """
    __tablename__ = "security_logs"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[SecurityEvent] = mapped_column(
        Enum(SecurityEvent, name="security_event"), nullable=False
    )
    input_text: Mapped[str]                    = mapped_column(Text, nullable=False)
    detection_model: Mapped[Optional[str]]     = mapped_column(String(80))
    risk_score: Mapped[Optional[float]]        = mapped_column(Numeric(4, 3))
    action_taken: Mapped[Optional[str]]        = mapped_column(String(100))
    created_at: Mapped[datetime]               = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkilər
    session: Mapped["Session"] = relationship(back_populates="security_logs")

    __table_args__ = (
        Index("idx_security_logs_session",    "session_id"),
        Index("idx_security_logs_event_type", "event_type"),
        CheckConstraint("risk_score BETWEEN 0 AND 1", name="chk_risk_score_range"),
    )

    def __repr__(self) -> str:
        return f"<SecurityLog event={self.event_type} risk={self.risk_score}>"


# ────────────────────────────────────────────────────────────
#  8. HUMAN_APPROVALS
# ────────────────────────────────────────────────────────────

class HumanApproval(Base):
    """
    Human-in-the-loop: kritik sorğu icrasından əvvəl insan təsdiqi.
    Hər query_log-a uyğun ən çox bir approval olur.
    """
    __tablename__ = "human_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    approver_id: Mapped[Optional[str]]     = mapped_column(String(100))
    status: Mapped[ApprovalStatus]         = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), default=ApprovalStatus.PENDING
    )
    reason: Mapped[Optional[str]]          = mapped_column(Text)
    requested_at: Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # İlişkilər
    query_log: Mapped["QueryLog"] = relationship(back_populates="human_approval")

    __table_args__ = (
        Index("idx_human_approvals_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<HumanApproval status={self.status} approver={self.approver_id!r}>"


# ────────────────────────────────────────────────────────────
#  9. EVALUATION_RESULTS
# ────────────────────────────────────────────────────────────

class EvaluationResult(Base):
    """
    Sorğu keyfiyyətinin qiymətləndirilməsi üç metrika ilə:
    1. functional_correct    — sorğu xətasız işlədimi?
    2. semantic_similarity   — ideal sorğuya nə qədər yaxın?
    3. llm_judge_score       — LLM hakim balı (claude-opus-4-6, gpt-4o)
    """
    __tablename__ = "evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    functional_correct: Mapped[Optional[bool]]   = mapped_column(Boolean)
    semantic_similarity: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    llm_judge_score: Mapped[Optional[float]]     = mapped_column(Numeric(4, 3))
    ground_truth_query: Mapped[Optional[str]]    = mapped_column(Text)
    judge_model: Mapped[Optional[str]]           = mapped_column(String(80))
    notes: Mapped[Optional[str]]                 = mapped_column(Text)
    evaluated_at: Mapped[datetime]               = mapped_column(DateTime(timezone=True), server_default=func.now())

    # İlişkilər
    query_log: Mapped["QueryLog"] = relationship(back_populates="evaluation_result")

    __table_args__ = (
        CheckConstraint("semantic_similarity BETWEEN 0 AND 1", name="chk_semantic_range"),
        CheckConstraint("llm_judge_score BETWEEN 0 AND 1",     name="chk_judge_range"),
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationResult "
            f"correct={self.functional_correct} "
            f"semantic={self.semantic_similarity} "
            f"judge={self.llm_judge_score}>"
        )


# ────────────────────────────────────────────────────────────
#  YARDIMÇI: Baza yaratmaq üçün skript
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    İstifadə:
        DATABASE_URL=postgresql+psycopg2://user:pass@localhost/sql_agent_db
        python models.py
    """
    import os
    from sqlalchemy import create_engine

    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:password@localhost/sql_agent_db",
    )

    engine = create_engine(DATABASE_URL, echo=True)
    Base.metadata.create_all(engine)
    print("✅ Bütün cədvəllər uğurla yaradıldı.")
