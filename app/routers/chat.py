"""
Chat Router — SQLab-in esas API giris noqteleri.
Butun AI biznes mentiqi services/ qatina kocurulub;
bu fayl yalniz HTTP orkestrasiyasini edir (incə qat memarlığı).
"""
import os
import re
import pathlib
import tempfile
import shutil
import time
import sqlalchemy as sa
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from ai.val import validate_sql

from services.llm_client import call_groq
from services.schema_service import get_db_name, load_semantic, filter_schema, get_schema
from services.sql_generator import build_chat_prompt, build_excel_prompt
from services.judge_service import judge_answer
from services.sql_executor import extract_sql, format_rows

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    agent_config_id: str
    db_url: Optional[str] = None
    source_type: Optional[str] = "postgresql"


class ChatResponse(BaseModel):
    session_id: str
    query_log_id: Optional[str]
    answer: str
    status: str


async def _log_query(db: AsyncSession, session_id: str, message: str) -> str:
    nl_input_safe = message[:400].replace("\'", "")
    result = await db.execute(sa.text(
        "INSERT INTO query_logs (session_id, nl_input, status) VALUES (:sid, :nl, :st) RETURNING id"
    ), {"sid": session_id, "nl": nl_input_safe, "st": "pending_approval"})
    await db.commit()
    return str(result.scalar())


@router.post("/upload-excel", summary="Excel/CSV fayl yukle")
async def upload_excel(file: UploadFile = File(...)):
    """Excel ve ya CSV fayli yukleyib sxemini qaytarir."""
    try:
        suffix = pathlib.Path(file.filename).suffix.lower()
        if suffix not in {".xlsx", ".xls", ".csv", ".tsv"}:
            return {"error": f"Desteklenmeyen format: {suffix}"}

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        shutil.copyfileobj(file.file, tmp)
        tmp.close()

        import sys
        sys.path.insert(0, "/app")
        from data_source.excel import get_excel_schema
        schema, ds = get_excel_schema(tmp.name)

        return {
            "file_path": tmp.name,
            "filename": file.filename,
            "schema": schema,
            "table_name": ds.table_name if ds else None,
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/chat-excel", summary="Excel fayl uzre sual ver")
async def chat_excel(
    file_path: str = Form(...),
    table_name: str = Form(...),
    message: str = Form(...),
    session_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Excel datasource-a sual verir."""
    import sys
    sys.path.insert(0, "/app")
    from data_source.excel import ExcelDataSource

    ds = ExcelDataSource(file_path)
    ds.load()
    schema_info = ds.get_schema()

    query_log_id = await _log_query(db, session_id, message)
    prompt = build_excel_prompt(schema_info, table_name, message)

    try:
        llm_answer = await call_groq(prompt, max_tokens=1000)

        real_result = ""
        sql = extract_sql(llm_answer)
        if sql:
            sql = re.sub(r"\bFROM\s+\w+", f"FROM {table_name}", sql, flags=re.IGNORECASE, count=1)
            try:
                rows = ds.execute(sql)
                real_result = format_rows(rows)
            except Exception as e:
                real_result = f"\n\n⚠ SQL xetasi: {e}"

        answer = llm_answer + real_result

        await db.execute(sa.text(
            "UPDATE query_logs SET status = :s, execution_time_ms = :ms WHERE id = :id"
        ), {"s": "SUCCESS", "ms": 0, "id": query_log_id})
        await db.commit()
        ds.close()

        return ChatResponse(session_id=session_id, query_log_id=query_log_id, answer=answer, status="success")

    except Exception as e:
        await db.execute(sa.text("UPDATE query_logs SET status = :s WHERE id = :id"), {"s": "error", "id": query_log_id})
        await db.commit()
        return ChatResponse(session_id=session_id, query_log_id=query_log_id, answer=f"Xeta: {e}", status="error")


@router.post("/chat", response_model=ChatResponse, summary="Agent-e sual ver")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    conn = None
    schema_info = ""
    semantic_info = ""

    if body.db_url:
        schema_info, conn = await get_schema(body.db_url)
        semantic_info = load_semantic(body.db_url)

    query_log_id = await _log_query(db, body.session_id, body.message)
    semantic_block = semantic_info if semantic_info else "(semantic layer yoxdur)"

    # RAG + acar-soz filtri hybrid (RAG elcatmaz olarsa fallback)
    try:
        import sys
        sys.path.insert(0, "/app")
        from ai.rag import embed_schema, filter_schema_rag
        db_name = get_db_name(body.db_url) if body.db_url else "unknown"
        embed_schema(db_name, schema_info)
        filtered_schema = filter_schema_rag(schema_info, db_name, body.message)
    except Exception:
        filtered_schema = filter_schema(schema_info, body.message)

    prompt = build_chat_prompt(filtered_schema, semantic_block, body.message)

    try:
        llm_answer = await call_groq(prompt, max_tokens=1500)

        real_result = ""
        exec_ms = 0
        if conn:
            sql = extract_sql(llm_answer)
            if sql:
                is_safe, err_msg = validate_sql(sql)
                if not is_safe:
                    await db.execute(sa.text("UPDATE query_logs SET status = :s WHERE id = :id"), {"s": "blocked", "id": query_log_id})
                    await db.commit()
                    await conn.close()
                    return ChatResponse(
                        session_id=body.session_id, query_log_id=query_log_id,
                        answer=llm_answer + f"\n\n🚫 Bloklandi: {err_msg}", status="blocked",
                    )
                try:
                    t0 = time.perf_counter()
                    result_rows = await conn.fetch(sql)
                    exec_ms = int((time.perf_counter() - t0) * 1000)
                    real_result = format_rows(result_rows)
                except Exception as e:
                    real_result = f"\n\n⚠ SQL icra xetasi: {e}"
            await conn.close()

        answer = llm_answer + real_result
        judge_score = await judge_answer(body.message, answer)

        await db.execute(sa.text(
            "UPDATE query_logs SET status = :s, execution_time_ms = :ms, llm_judge_score = :score WHERE id = :id"
        ), {"s": "SUCCESS", "ms": exec_ms, "score": judge_score, "id": query_log_id})

        if judge_score is not None:
            await db.execute(sa.text(
                "INSERT INTO evaluations (query_log_id, llm_judge_score, judge_model, notes) VALUES (:qid, :score, :model, :notes)"
            ), {"qid": query_log_id, "score": judge_score, "model": "llama-3.3-70b-versatile", "notes": body.message[:200]})

        await db.commit()
        return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=answer, status="success")

    except Exception as e:
        err = str(e)[:200]
        await db.execute(sa.text("UPDATE query_logs SET status = :s, error_message = :e WHERE id = :id"), {"s": "error", "e": err, "id": query_log_id})
        await db.commit()
        return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=f"Xeta: {e}", status="error")
