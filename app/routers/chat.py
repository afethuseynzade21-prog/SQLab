import os
import re
import asyncpg
import sqlalchemy as sa
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
import httpx
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db

# ── Query Validation Engine ────────────────────────────────
import sqlglot
from sqlglot import exp

BLOCKED_STATEMENT_TYPES = (
    exp.Drop, exp.Delete, exp.Insert, exp.Update,
    exp.Create, exp.TruncateTable, exp.Alter,
    exp.Command, exp.Transaction,
)

BLOCKED_KEYWORDS = [
    "pg_read_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export",
    "information_schema.user_privileges",
]

def validate_sql(sql: str) -> tuple:
    sql = sql.strip()
    if not sql:
        return False, "Bos SQL sorgusu"
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Coxlu SQL sorgusu icaze verilmir (SQL injection riski)"
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        return False, f"SQL parse xetasi: {e}"
    if not isinstance(parsed, exp.Select):
        stmt_type = type(parsed).__name__
        return False, f"'{stmt_type}' emeliyyatina icaze verilmir. Yalniz SELECT icazelidir."
    for blocked in BLOCKED_STATEMENT_TYPES:
        if parsed.find(blocked):
            return False, f"Tehlikeli emeliyyat askar edildi: {blocked.__name__}"
    sql_lower = sql.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in sql_lower:
            return False, f"Bloklanan funksiya: '{kw}'"
    for node in parsed.walk():
        if isinstance(node, BLOCKED_STATEMENT_TYPES):
            return False, "Subquery-de tehlikeli emeliyyat askar edildi"
    return True, ""

# ──────────────────────────────────────────────────────────

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    agent_config_id: str
    db_url: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    query_log_id: Optional[str]
    answer: str
    status: str


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
            lines.append("\nCedvel tesvirleri:")
            for tbl, info in data["tables"].items():
                lines.append(f"  {tbl} -> {info.get('label','')}: {info.get('description','')}")
                if "metrics" in info:
                    for m in info["metrics"]:
                        lines.append(f"    - {m}")
        if "metrics" in data:
            lines.append("\nBiznes metrikleri:")
            for key, m in data["metrics"].items():
                lines.append(f"  {m['label']}: {m['formula']}")
        if "kpis" in data:
            lines.append("\nKPI Definitions:")
            for key, kpi in data["kpis"].items():
                lines.append(f"  {kpi['label']}: {kpi['description']}")
                lines.append(f"    Formula: {kpi['formula']}")
        if "common_joins" in data:
            lines.append("\nUmumi birleshmeler:")
            for j in data["common_joins"]:
                lines.append(f"  {j['description']}: {j['join']}")
        if "common_questions" in data:
            lines.append("\nTez-tez suallar:")
            for q in data["common_questions"]:
                lines.append(f"  '{q['q']}' -> {q['hint']}")
        return "\n".join(lines)
    except Exception:
        return ""


async def generate_semantic(db_url: str, schema_text: str, api_key: str):
    db_name = get_db_name(db_url)
    path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
    if path.exists():
        return
    prompt = f"""Bu verilənlər bazası sxemi üçün YAML formatında semantic layer yarat.

{schema_text}

Aşağıdakı YAML strukturunu istifadə et:

version: "1.0"
database: "{db_name}"

tables:
  CEDVEL_ADI:
    label: "Azərbaycan dilində ad"
    description: "Cədvəlin nə saxladığı"
    metrics:
      - "sutun_adi → nə deməkdir"

metrics:
  metrik_adi:
    label: "Azərbaycan dilində ad"
    formula: "SQL ifadəsi"

kpis:
  kpi_adi:
    label: "Azərbaycan dilində KPI adı"
    formula: "SELECT ifadəsi"
    description: "KPI nə ölçür"

common_joins:
  - description: "Birləşmə izahı"
    join: "cedvel1 → cedvel2 (açar_sutun)"

common_questions:
  - q: "Tez-tez soruşulan sual"
    hint: "SQL ipucu"

VACIB:
- Hər baza üçün 5-8 real KPI müəyyən et
- KPI formula-ları həmin bazanın REAL sütun adlarına əsaslanmalıdır
- YALNIZ YAML yaz, başqa heç nə yazma."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
                timeout=30.0,
            )
            data = resp.json()
            if "choices" in data:
                yaml_text = data["choices"][0]["message"]["content"]
                yaml_text = re.sub(r"```yaml\s*", "", yaml_text)
                yaml_text = re.sub(r"```\s*", "", yaml_text)
                yaml_text = yaml_text.strip()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(yaml_text)
    except Exception as e:
        print(f"SEMANTIC GENERATE XETASI: {e}")


async def get_schema(db_url: str):
    try:
        conn = await asyncpg.connect(db_url)
        col_rows = await conn.fetch("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        schema = {}
        for r in col_rows:
            t = r['table_name']
            if t not in schema:
                schema[t] = []
            schema[t].append(f"{r['column_name']} ({r['data_type']})")
        schema_text = "=== VERILƏNLƏR BAZASI SXEMİ ===\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"
        return schema_text, conn
    except Exception as e:
        return f"Baza qosulma xetasi: {e}", None


@router.post("/chat", response_model=ChatResponse, summary="Agent-e sual ver")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    api_key = os.environ.get("GROQ_API_KEY", "")

    conn = None
    schema_info = ""
    semantic_info = ""

    if body.db_url:
        schema_info, conn = await get_schema(body.db_url)
        db_name = get_db_name(body.db_url)
        sem_path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
        if not sem_path.exists():
            await generate_semantic(body.db_url, schema_info, api_key)
        semantic_info = load_semantic(body.db_url)

    ql_result = await db.execute(sa.text(
        f"INSERT INTO query_logs (session_id, nl_input, status) VALUES ('{body.session_id}', '{body.message[:400]}', 'PENDING_APPROVAL') RETURNING id"
    ))
    await db.commit()
    query_log_id = str(ql_result.scalar())

    semantic_block = semantic_info if semantic_info else "(semantic layer yoxdur)"

    prompt = f"""Sen SQL agentisen. Asagidaki sxem ve semantik layere esaslanaraq istifadecinin sualini cavabla.

{schema_info}

{semantic_block}

VACIB QAYDALAR:
- Yalniz yuxaridaki sxemdeki REAL sutun adlarini istifade et
- Semantik layerdeki metric formulalarini istifade et (varsa)
- SQL-i ```sql ``` blokunun icine yaz
- Cavabi Azerbaycan dilinde ver

Istifadeci suali: {body.message}

SQL sorgusu yaz ve izah et."""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1500,
                },
                timeout=30.0,
            )
            data = resp.json()
            if "choices" in data:
                llm_answer = data["choices"][0]["message"]["content"]
            else:
                llm_answer = "API xetasi: " + str(data.get("error", data))

        real_result = ""
        if conn:
            sql_match = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
            if sql_match:
                sql = sql_match.group(1).strip()
                is_safe, err_msg = validate_sql(sql)
                if not is_safe:
                    real_result = f"\n\n🚫 SQL bloklandı: {err_msg}"
                    await db.execute(sa.text(
                        f"UPDATE query_logs SET status = 'BLOCKED' WHERE id = '{query_log_id}'"
                    ))
                    await db.commit()
                    await conn.close()
                    return ChatResponse(
                        session_id=body.session_id,
                        query_log_id=query_log_id,
                        answer=llm_answer + real_result,
                        status="blocked"
                    )
                try:
                    result_rows = await conn.fetch(sql)
                    if result_rows:
                        cols = list(result_rows[0].keys())
                        header = " | ".join(cols)
                        sep = "-" * len(header)
                        rows_text = "\n".join([" | ".join(str(v) for v in r.values()) for r in result_rows[:20]])
                        real_result = f"\n\n📊 Real nəticə ({len(result_rows)} sətir):\n{header}\n{sep}\n{rows_text}"
                        if len(result_rows) > 20:
                            real_result += f"\n... +{len(result_rows)-20} sətir"
                    else:
                        real_result = "\n\n📊 Nəticə: boş"
                except Exception as e:
                    real_result = f"\n\n⚠ SQL icra xətası: {e}"
            await conn.close()

        answer = llm_answer + real_result

        await db.execute(sa.text(
            f"UPDATE query_logs SET status = 'SUCCESS', execution_time_ms = 100 WHERE id = '{query_log_id}'"
        ))
        await db.commit()

        return ChatResponse(
            session_id=body.session_id,
            query_log_id=query_log_id,
            answer=answer,
            status="success"
        )

    except Exception as e:
        err = str(e)[:200].replace("'", "")
        await db.execute(sa.text(
            f"UPDATE query_logs SET status = 'ERROR', error_message = '{err}' WHERE id = '{query_log_id}'"
        ))
        await db.commit()
        return ChatResponse(
            session_id=body.session_id,
            query_log_id=query_log_id,
            answer=f"Xeta: {e}",
            status="error"
        )