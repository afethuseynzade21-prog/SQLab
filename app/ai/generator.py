"""
ai/gen.py — LLM SQL Generation Engine
Groq API ilə natural language → SQL çevirməsi.
Semantic layer dəstəyi ilə.
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


# ── Pydantic modellər ──────────────────────────────────────
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


# ── Köməkçi funksiyalar ────────────────────────────────────
def get_db_name(db_url: str) -> str:
    return db_url.rstrip("/").split("/")[-1]


def load_semantic(db_url: str) -> str:
    """Semantic YAML faylını yükləyir."""
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
            lines.append("\nÜmumi birləşmələr:")
            for j in data["common_joins"]:
                lines.append(f"  {j['description']}: {j['join']}")
        if "common_questions" in data:
            lines.append("\nTez-tez suallar:")
            for q in data["common_questions"]:
                lines.append(f"  '{q['q']}' -> {q['hint']}")
        return "\n".join(lines)
    except Exception:
        return ""


async def generate_semantic(db_url: str, schema_text: str, api_key: str) -> None:
    """LLM ilə semantic layer yaradır."""
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


async def get_schema(db_url: str) -> tuple[str, asyncpg.Connection | None]:
    """Verilənlər bazasının sxemini asyncpg ilə oxuyur."""
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
        schema_text = "=== VERILƏNLƏR BAZASI SXEMİ ===\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"
        return schema_text, conn
    except Exception as e:
        return f"Baza qoşulma xətası: {e}", None


# ── Ana endpoint ───────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse, summary="Agent-ə sual ver")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    api_key = os.environ.get("GROQ_API_KEY", "")

    conn: asyncpg.Connection | None = None
    schema_info = ""
    semantic_info = ""

    # Schema + semantic layer yüklə
    if body.db_url:
        schema_info, conn = await get_schema(body.db_url)
        db_name = get_db_name(body.db_url)
        sem_path = Path(__file__).parent.parent / f"semantic_{db_name}.yaml"
        if not sem_path.exists():
            await generate_semantic(body.db_url, schema_info, api_key)
        semantic_info = load_semantic(body.db_url)

    # Parametrli INSERT — SQL injection yoxdur
    nl_input_safe = body.message[:400]
    ql_result = await db.execute(
        sa.text(
            "INSERT INTO query_logs (session_id, nl_input, status) "
            "VALUES (:session_id, :nl_input, :status) RETURNING id"
        ),
        {"session_id": body.session_id, "nl_input": nl_input_safe, "status": "pending_approval"},
    )
    await db.commit()
    query_log_id = str(ql_result.scalar())

    semantic_block = semantic_info if semantic_info else "(semantic layer yoxdur)"

    prompt = f"""Sen SQL agentisen. Aşağıdakı sxem və semantik layerə əsaslanaraq istifadəçinin sualını cavabla.

{schema_info}

{semantic_block}

FEW-SHOT NÜMUNƏLƏR (bu nümunələrə əsaslanaraq SQL yaz):

Sual: aylıq sifariş sayı
SQL: SELECT EXTRACT(MONTH FROM order_purchase_timestamp) AS ay, COUNT(*) AS sifaris_sayi FROM olist_orders_dataset GROUP BY ay ORDER BY ay

Sual: ən çox satılan kateqoriyalar
SQL: SELECT p.product_category_name, COUNT(*) AS satis FROM olist_order_items_dataset oi JOIN olist_products_dataset p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY satis DESC LIMIT 10

Sual: çatdırılmış sifarişlərin faizi
SQL: SELECT ROUND(COUNT(*) FILTER (WHERE order_status = 'delivered') * 100.0 / COUNT(*), 2) AS faiz FROM olist_orders_dataset

Sual: ən çox müştərili şəhərlər
SQL: SELECT customer_city, COUNT(*) AS musteri_sayi FROM olist_customers_dataset GROUP BY customer_city ORDER BY musteri_sayi DESC LIMIT 10

Sual: ortalama çatdırılma vaxtı gün
SQL: SELECT ROUND(AVG(EXTRACT(EPOCH FROM (order_delivered_customer_date - order_purchase_timestamp))/86400), 1) AS orta_gun FROM olist_orders_dataset WHERE order_delivered_customer_date IS NOT NULL

Sual: reytinq üzrə sifariş sayı
SQL: SELECT review_score, COUNT(*) AS say FROM olist_order_reviews_dataset GROUP BY review_score ORDER BY review_score

Sual: ödəniş növlərinin paylanması
SQL: SELECT payment_type, COUNT(*) AS say, ROUND(SUM(payment_value), 2) AS umumi FROM olist_order_payments_dataset GROUP BY payment_type ORDER BY say DESC

Sual: ümumi gəlir
SQL: SELECT ROUND(SUM(price + freight_value), 2) AS umumi_gelir FROM olist_order_items_dataset

Sual: hər regionda ən çox satılan kateqoriya
SQL: WITH s AS (SELECT c.customer_state AS region, p.product_category_name AS cat, COUNT(*) AS n FROM olist_order_items_dataset oi JOIN olist_orders_dataset o ON oi.order_id=o.order_id JOIN olist_customers_dataset c ON o.customer_id=c.customer_id JOIN olist_products_dataset p ON oi.product_id=p.product_id GROUP BY region, cat) SELECT region, cat, n FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY region ORDER BY n DESC) AS rn FROM s) t WHERE rn=1

Sual: ən çox satan satıcılar
SQL: SELECT seller_id, COUNT(*) AS satis, ROUND(SUM(price), 2) AS gelir FROM olist_order_items_dataset GROUP BY seller_id ORDER BY satis DESC LIMIT 10

VACİB QAYDA: Yuxarıdakı nümunələrə baxaraq oxşar suallar üçün oxşar SQL strukturu istifadə et. SQL alias adlarında nöqtə işlətmə.

VACİB QAYDALAR:
- Yalnız yuxarıdakı sxemdəki REAL sütun adlarını istifadə et
- Semantik layerdəki metric formulalarını istifadə et (varsa)
- SQL-i ```sql ``` blokunun içinə yaz
- Cavabı Azərbaycan dilində ver
- SQL alias adlarında nöqtə işlətmə (rvw.score deyil, score yaz)

İstifadəçi sualı: {{body.message}}

SQL sorğusu yaz və izah et."""

    try:
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
                    llm_answer = "API xətası: " + str(data.get("error", data))

            real_result = ""
            exec_ms = 0

            if conn:
                sql_match = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
                if sql_match:
                    sql = sql_match.group(1).strip()
                    is_safe, err_msg = validate_sql(sql)
                    if not is_safe:
                        real_result = f"\n\n🚫 SQL bloklandı: {err_msg}"
                        await db.execute(
                            sa.text("UPDATE query_logs SET status = :status WHERE id = :id"),
                            {"status": "blocked", "id": query_log_id},
                        )
                        await db.commit()
                        return ChatResponse(
                            session_id=body.session_id,
                            query_log_id=query_log_id,
                            answer=llm_answer + real_result,
                            status="blocked",
                        )
                    try:
                        t0 = time.perf_counter()
                        result_rows = await conn.fetch(sql)
                        exec_ms = int((time.perf_counter() - t0) * 1000)
                        if result_rows:
                            cols = list(result_rows[0].keys())
                            header = " | ".join(cols)
                            sep = "-" * len(header)
                            rows_text = "\n".join(
                                [" | ".join(str(v) for v in r.values()) for r in result_rows[:20]]
                            )
                            real_result = (
                                f"\n\n📊 Real nəticə ({len(result_rows)} sətir):\n"
                                f"{header}\n{sep}\n{rows_text}"
                            )
                            if len(result_rows) > 20:
                                real_result += f"\n... +{len(result_rows) - 20} sətir"
                        else:
                            real_result = "\n\n📊 Nəticə: boş"
                    except Exception as e:
                        real_result = f"\n\n⚠ SQL icra xətası: {e}"
        finally:
            if conn:
                await conn.close()

        answer = llm_answer + real_result

        await db.execute(
            sa.text(
                "UPDATE query_logs SET status = :status, execution_time_ms = :ms WHERE id = :id"
            ),
            {"status": "success", "ms": exec_ms, "id": query_log_id},
        )
        await db.commit()

        return ChatResponse(
            session_id=body.session_id,
            query_log_id=query_log_id,
            answer=answer,
            status="success",
        )

    except Exception as e:
        err = str(e)[:200]
        await db.execute(
            sa.text(
                "UPDATE query_logs SET status = :status, error_message = :err WHERE id = :id"
            ),
            {"status": "error", "err": err, "id": query_log_id},
        )
        await db.commit()
        return ChatResponse(
            session_id=body.session_id,
            query_log_id=query_log_id,
            answer=f"Xəta: {e}",
            status="error",
        )
