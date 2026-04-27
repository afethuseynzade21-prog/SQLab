"""
ai/gen.py — LLM SQL Generation Engine
PostgreSQL, MySQL və Excel/CSV dəstəyi ilə.
"""

import os
import re
import time
import asyncpg
import httpx
import sqlalchemy as sa
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from ai.val import validate_sql

router = APIRouter()

# ── Kalıcı söhbət yaddaşı (PostgreSQL-də saxlanılır) ─────────
_MAX_HISTORY = 5
import json as _json

def get_history(session_id: str) -> list[dict]:
    try:
        p = pathlib.Path(f"/app/memory_{session_id}.json")
        if not p.exists():
            return []
        data = _json.loads(p.read_text())
        return data[-_MAX_HISTORY * 2:]
    except Exception:
        return []

def add_to_history(session_id: str, role: str, content_text: str) -> None:
    try:
        p = pathlib.Path(f"/app/memory_{session_id}.json")
        data = []
        if p.exists():
            data = _json.loads(p.read_text())
        data.append({"role": role, "content": content_text[:2000]})
        data = data[-_MAX_HISTORY * 2:]
        p.write_text(_json.dumps(data, ensure_ascii=False))
    except Exception as e:
        print(f"MEMORY WRITE ERROR: {e}")


class ChatRequest(BaseModel):
    session_id: str
    message: str
    agent_config_id: str
    db_url: Optional[str] = None
    source_type: Optional[str] = "postgresql"
    file_path: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    query_log_id: Optional[str]
    answer: str
    status: str
    source_type: Optional[str] = None


def get_db_name(db_url: str) -> str:
    return db_url.rstrip("/").split("/")[-1]


def load_semantic(db_url: str) -> str:
    try:
        import yaml
        db_name = get_db_name(db_url)
        path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        lines = ["\n=== SEMANTIK LAYER ==="]
        if "tables" in data:
            lines.append("\nCədvəl təsvirləri:")
            for tbl, info in data["tables"].items():
                lines.append(f"  {tbl} -> {info.get('label', '')}: {info.get('description', '')}")
        if "kpis" in data:
            lines.append("\nKPI Definitions:")
            for key, kpi in data["kpis"].items():
                lines.append(f"  {kpi['label']}: {kpi['description']}")
        return "\n".join(lines)
    except Exception:
        return ""


async def generate_semantic(db_url: str, schema_text: str, api_key: str) -> None:
    db_name = get_db_name(db_url)
    path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
    if path.exists():
        return
    prompt = f"""Bu verilənlər bazası sxemi üçün YAML formatında semantic layer yarat.
{schema_text}
YALNIZ YAML yaz."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000},
                timeout=30.0,
            )
            data = resp.json()
            if "choices" in data:
                yaml_text = re.sub(r"```yaml\s*|```\s*", "", data["choices"][0]["message"]["content"])
                with open(path, "w", encoding="utf-8") as f:
                    f.write(yaml_text.strip())
    except Exception as e:
        print(f"SEMANTIC GENERATE XETASI: {e}")


async def get_postgresql_schema(db_url: str):
    try:
        conn = await asyncpg.connect(db_url)
        col_rows = await conn.fetch("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        schema: dict[str, list[str]] = {}
        for r in col_rows:
            t = r["table_name"]
            if t not in schema:
                schema[t] = []
            schema[t].append(f"{r['column_name']} ({r['data_type']})")

        schema_text = "=== PostgreSQL VERİLƏNLƏR BAZASI SXEMİ ===\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"
            try:
                sample = await conn.fetch(f"SELECT * FROM {tbl} LIMIT 2")
                if sample:
                    col_names = list(sample[0].keys())
                    schema_text += f"  -- Nümunə ({tbl}):\n"
                    for row in sample:
                        vals = " | ".join(str(v)[:30] if v is not None else "NULL" for v in row.values())
                        schema_text += f"  -- {vals}\n"
            except Exception:
                pass
        return schema_text, conn
    except Exception as e:
        return f"PostgreSQL bağlantı xətası: {e}", None


async def call_llm(prompt: str, api_key: str, history: list[dict] | None = None) -> str:
    messages = []
    if history:
        messages.extend(history[:-1])
    messages.append({"role": "user", "content": prompt})
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 1500},
            timeout=30.0,
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        return "API xetasi: " + str(data.get("error", data))


def format_rows(rows: list[dict], total: int) -> str:
    if not rows:
        return "\n\n📊 Nəticə: boş"
    cols = list(rows[0].keys())
    header = " | ".join(cols)
    sep = "-" * len(header)
    rows_text = "\n".join([" | ".join(str(v) for v in r.values()) for r in rows[:20]])
    result = f"\n\n📊 Real nəticə ({total} sətir):\n{header}\n{sep}\n{rows_text}"
    if total > 20:
        result += f"\n... +{total - 20} sətir"
    return result


@router.post("/chat", response_model=ChatResponse, summary="Agent-ə sual ver")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    api_key = os.environ.get("GROQ_API_KEY", "")
    source_type = (body.source_type or "postgresql").lower()

    nl_input_safe = body.message[:400]
    ql_result = await db.execute(
        sa.text("INSERT INTO query_logs (session_id, nl_input, status) VALUES (:session_id, :nl_input, :status) RETURNING id"),
        {"session_id": body.session_id, "nl_input": nl_input_safe, "status": "pending_approval"},
    )
    await db.commit()
    query_log_id = str(ql_result.scalar())

    try:
        schema_info = ""
        real_result = ""
        exec_ms = 0
        llm_answer = ""

        if source_type == "postgresql":
            conn = None
            try:
                if body.db_url:
                    schema_info, conn = await get_postgresql_schema(body.db_url)
                    db_name = get_db_name(body.db_url)
                    sem_path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
                    if not sem_path.exists():
                        await generate_semantic(body.db_url, schema_info, api_key)
                    semantic_info = load_semantic(body.db_url)
                else:
                    semantic_info = ""

                prompt = f"""Sen SQL agentisen. PostgreSQL sxeminə əsaslanaraq cavabla.
{schema_info}
{semantic_info if semantic_info else ''}
VACİB: Yalnız sxemdəki REAL sütun adlarını istifadə et. SQL-i ```sql ``` içinə yaz. Azərbaycan dilində cavabla.
Sual: {body.message}"""

                history = get_history(body.session_id)
            add_to_history(body.session_id, "user", body.message)
            llm_answer = await call_llm(prompt, api_key, history)
            add_to_history(body.session_id, "assistant", llm_answer)

                if conn:
                    sql_match = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
                    if sql_match:
                        sql = sql_match.group(1).strip()
                        is_safe, err_msg = validate_sql(sql)
                        if not is_safe:
                            real_result = f"\n\n🚫 SQL bloklandı: {err_msg}"
                            await db.execute(sa.text("UPDATE query_logs SET status = :s WHERE id = :id"), {"s": "blocked", "id": query_log_id})
                            await db.commit()
                            return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=llm_answer + real_result, status="blocked", source_type=source_type)
                        try:
                            t0 = time.perf_counter()
                            result_rows = await conn.fetch(sql)
                            exec_ms = int((time.perf_counter() - t0) * 1000)
                            real_result = format_rows([dict(r) for r in result_rows], len(result_rows))
                        except Exception as e:
                            real_result = f"\n\n⚠ SQL icra xətası: {e}"
            finally:
                if conn:
                    await conn.close()

        elif source_type == "mysql":
            from data_source.mysql import get_mysql_schema, execute_mysql_sql, close_mysql
            mysql_conn = None
            try:
                if not body.db_url:
                    raise ValueError("MySQL üçün db_url tələb olunur")
                schema_info, mysql_conn = await get_mysql_schema(body.db_url)
                prompt = f"""Sen SQL agentisen. MySQL sxeminə əsaslanaraq cavabla.
{schema_info}
VACİB: MySQL sintaksisi istifadə et. SQL-i ```sql ``` içinə yaz. Azərbaycan dilində cavabla.
Sual: {body.message}"""
                history = get_history(body.session_id)
            add_to_history(body.session_id, "user", body.message)
            llm_answer = await call_llm(prompt, api_key, history)
            add_to_history(body.session_id, "assistant", llm_answer)
                if mysql_conn:
                    sql_match = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
                    if sql_match:
                        rows, exec_ms, err = await execute_mysql_sql(mysql_conn, sql_match.group(1).strip())
                        real_result = f"\n\n⚠ MySQL xətası: {err}" if err else format_rows(rows, len(rows))
            finally:
                if mysql_conn:
                    await close_mysql(mysql_conn)

        elif source_type == "excel":
            from data_source.excel import get_excel_schema, execute_excel_sql
            if not body.file_path:
                raise ValueError("Excel ucun file_path teleb olunur")
            schema_info, excel_ds = get_excel_schema(body.file_path)
            bts = chr(96) * 3
            prompt = ("Sen SQL agentisen. Bu Excel/CSV faylina esaslanaraq cavabla.\n"
                      + schema_info + "\n"
                      + "VACIB: SQLite sintaksisi istifade et. "
                      + "SQL-i " + bts + "sql " + bts + " icine yaz. "
                      + "Azerbaycan dilinde cavabla.\n"
                      + "Sual: " + body.message)
            history = get_history(body.session_id)
            add_to_history(body.session_id, "user", body.message)
            llm_answer = await call_llm(prompt, api_key, history)
            add_to_history(body.session_id, "assistant", llm_answer)
            if excel_ds:
                import re
                pat = bts + r"sql\s*(.*?)\s*" + bts
                found = re.search(pat, llm_answer, re.DOTALL)
                if found:
                    sql_text = found.group(1).strip()
                    result_rows, exec_err = execute_excel_sql(excel_ds, sql_text)
                    if exec_err:
                        real_result = "\n\nExcel SQL xetasi: " + exec_err
                    else:
                        real_result = format_rows(result_rows, len(result_rows))
                excel_ds.close()
        else:
            raise ValueError(f"Naməlum source_type: {source_type}. Dəstəklənənlər: postgresql, mysql, excel")

        answer = llm_answer + real_result
        await db.execute(sa.text("UPDATE query_logs SET status = :s, execution_time_ms = :ms WHERE id = :id"), {"s": "success", "ms": exec_ms, "id": query_log_id})
        await db.commit()
        return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=answer, status="success", source_type=source_type)

    except Exception as e:
        err = str(e)[:200]
        await db.execute(sa.text("UPDATE query_logs SET status = :s, error_message = :err WHERE id = :id"), {"s": "error", "err": err, "id": query_log_id})
        await db.commit()
        return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=f"Xəta: {e}", status="error", source_type=source_type)
