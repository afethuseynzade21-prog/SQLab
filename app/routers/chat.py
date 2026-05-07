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
from ai.val import validate_sql

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
            for tbl, info in data["tables"].items():
                lines.append(f"  {tbl} -> {info.get(chr(108)+chr(97)+chr(98)+chr(101)+chr(108),'')}: {info.get(chr(100)+chr(101)+chr(115)+chr(99)+chr(114)+chr(105)+chr(112)+chr(116)+chr(105)+chr(111)+chr(110),'')}")
                if "metrics" in info:
                    for m in info["metrics"]:
                        lines.append(f"    - {m}")
        if "common_questions" in data:
            lines.append("\nTez-tez suallar:")
            for q in data["common_questions"]:
                lines.append(f"  '{q['q']}' -> {q['hint']}")
        return "\n".join(lines)
    except Exception:
        return ""


def filter_schema(schema_text: str, question: str) -> str:
    q = question.lower()
    table_keywords = {
        "olist_orders_dataset": ["sifaris","order","status","catdirilma","tarix","delivery","purchase"],
        "olist_customers_dataset": ["musteri","customer","seher","city","eyalet","state","region"],
        "olist_order_items_dataset": ["mehsul","product","qiymet","price","gelir","revenue","satis","seller","satici"],
        "olist_order_payments_dataset": ["odenis","payment","kredit","credit","boleto","taksit"],
        "olist_order_reviews_dataset": ["rey","review","reytinq","rating","score"],
        "olist_products_dataset": ["mehsul","product","kateqoriya","category"],
        "olist_sellers_dataset": ["satici","seller","vendor"],
        "product_category_name_translation": ["kateqoriya","category","ingilis","english"],
    }
    selected = set()
    for table, keywords in table_keywords.items():
        for kw in keywords:
            if kw in q:
                selected.add(table)
                break
    if not selected:
        return schema_text
    if "olist_order_items_dataset" in selected:
        selected.add("olist_orders_dataset")
        selected.add("olist_products_dataset")
    if "olist_order_reviews_dataset" in selected:
        selected.add("olist_orders_dataset")
    if "olist_customers_dataset" in selected:
        selected.add("olist_orders_dataset")
    if "olist_order_payments_dataset" in selected:
        selected.add("olist_orders_dataset")
    lines = schema_text.split("\n")
    filtered = []
    include = True
    current_table = None
    for line in lines:
        stripped = line.strip().rstrip(":")
        if stripped in table_keywords:
            current_table = stripped
            include = current_table in selected
        if include:
            filtered.append(line)
    return "\n".join(filtered) if filtered else schema_text


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
            t = r["table_name"]
            if t not in schema:
                schema[t] = []
            schema[t].append(f"{r[chr(99)+chr(111)+chr(108)+chr(117)+chr(109)+chr(110)+chr(95)+chr(110)+chr(97)+chr(109)+chr(101)]} ({r[chr(100)+chr(97)+chr(116)+chr(97)+chr(95)+chr(116)+chr(121)+chr(112)+chr(101)]})")
        schema_text = "=== VERILƏNLƏR BAZASI SXEMİ ===\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"
        return schema_text, conn
    except Exception as e:
        return f"Baza qosulma xetasi: {e}", None


FEW_SHOT = """
FEW-SHOT NÜMUNƏLƏR:

Sual: aylik sifaris sayi
SQL: SELECT EXTRACT(MONTH FROM order_purchase_timestamp) AS ay, COUNT(*) AS sifaris_sayi FROM olist_orders_dataset GROUP BY ay ORDER BY ay

Sual: en cox satilan kateqoriyalar
SQL: SELECT p.product_category_name, COUNT(*) AS satis FROM olist_order_items_dataset oi JOIN olist_products_dataset p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY satis DESC LIMIT 10

Sual: catdirilmis sifarislerin faizi
SQL: SELECT ROUND(COUNT(*) FILTER (WHERE order_status = 'delivered') * 100.0 / COUNT(*), 2) AS faiz FROM olist_orders_dataset

Sual: en cox musterili sehirler
SQL: SELECT customer_city, COUNT(*) AS musteri_sayi FROM olist_customers_dataset GROUP BY customer_city ORDER BY musteri_sayi DESC LIMIT 10

Sual: odenis novlerinin paylanmasi
SQL: SELECT payment_type, COUNT(*) AS say, ROUND(SUM(payment_value), 2) AS umumi FROM olist_order_payments_dataset GROUP BY payment_type ORDER BY say DESC

Sual: umumi gelir
SQL: SELECT ROUND(SUM(price + freight_value), 2) AS umumi_gelir FROM olist_order_items_dataset

Sual: bazarin 80 faiz satisini nece satici formalaşdirir
SQL: WITH satis AS (SELECT seller_id, SUM(price + freight_value) AS umumi FROM olist_order_items_dataset GROUP BY seller_id), kumul AS (SELECT seller_id, umumi, SUM(umumi) OVER (ORDER BY umumi DESC) AS kumul_satis, SUM(umumi) OVER () AS total_satis FROM satis) SELECT COUNT(*) AS satici_sayi FROM kumul WHERE kumul_satis <= total_satis * 0.8
"""


@router.post("/chat", response_model=ChatResponse, summary="Agent-e sual ver")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    api_key = os.environ.get("GROQ_API_KEY", "")
    conn = None
    schema_info = ""
    semantic_info = ""

    if body.db_url:
        schema_info, conn = await get_schema(body.db_url)
        semantic_info = load_semantic(body.db_url)

    nl_input_safe = body.message[:400].replace("'", "")
    ql_result = await db.execute(sa.text(
        "INSERT INTO query_logs (session_id, nl_input, status) VALUES (:sid, :nl, :st) RETURNING id"
    ), {"sid": body.session_id, "nl": nl_input_safe, "st": "pending_approval"})
    await db.commit()
    query_log_id = str(ql_result.scalar())

    semantic_block = semantic_info if semantic_info else "(semantic layer yoxdur)"
    filtered_schema = filter_schema(schema_info, body.message)

    prompt = (
        "Sen SQL agentisen. Asagidaki sxem ve semantik layere esaslanaraq sualini cavabla.\n\n"
        + filtered_schema + "\n\n"
        + semantic_block + "\n\n"
        + FEW_SHOT + "\n\n"
        "DUSUNCE PROSESI - SQL yazmadan evvel:\n"
        "1. Sual ne sorusur?\n"
        "2. Hansi cedveller lazimdir?\n"
        "3. Hansi hesablamalar lazimdir?\n"
        "4. Netice nece olmalidir?\n\n"
        "VACIB QAYDALAR:\n"
        "- Yalniz sxemdeki REAL sutun adlarini istifade et\n"
        "- SQL-i ```sql ``` blokunun icine yaz\n"
        "- Cavabi Azerbaycan dilinde ver\n"
        "- SQL alias adlarinda noqte isletme\n\n"
        "Istifadeci suali: " + body.message + "\n\n"
        "Yuxaridaki dusunce prosesini izle, sonra SQL sorgusu yaz."
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500},
                timeout=30.0,
            )
            data = resp.json()
            llm_answer = data["choices"][0]["message"]["content"] if "choices" in data else "API xetasi: " + str(data.get("error", data))

        real_result = ""
        exec_ms = 0
        if conn:
            import time as _time
            sql_match = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
            if sql_match:
                sql = sql_match.group(1).strip()
                is_safe, err_msg = validate_sql(sql)
                if not is_safe:
                    real_result = f"\n\n Bloklandı: {err_msg}"
                    await db.execute(sa.text("UPDATE query_logs SET status = :s WHERE id = :id"), {"s": "blocked", "id": query_log_id})
                    await db.commit()
                    await conn.close()
                    return ChatResponse(session_id=body.session_id, query_log_id=query_log_id, answer=llm_answer + real_result, status="blocked")
                try:
                    t0 = _time.perf_counter()
                    result_rows = await conn.fetch(sql)
                    exec_ms = int((_time.perf_counter() - t0) * 1000)
                    if result_rows:
                        cols = list(result_rows[0].keys())
                        header = " | ".join(cols)
                        sep = "-" * len(header)
                        rows_text = "\n".join([" | ".join(str(v) for v in r.values()) for r in result_rows[:20]])
                        real_result = f"\n\n📊 Real nəticə ({len(result_rows)} sətir):\n{header}\n{sep}\n{rows_text}"
                        if len(result_rows) > 20:
                            real_result += f"\n... +{len(result_rows)-20} setir"
                    else:
                        real_result = "\n\n Netice: bos"
                except Exception as e:
                    real_result = f"\n\n SQL icra xetasi: {e}"
            await conn.close()

        answer = llm_answer + real_result

        # LLM-as-judge
        judge_score = None
        try:
            judge_prompt = (
                "SQL agentinin cavabini 1-10 arasi qiymetlendir.\n\n"
                "Sual: " + body.message + "\n\n"
                "Cavab: " + answer[:600] + "\n\n"
                "YALNIZ bir reqem yaz (1-10). Basqa hec ne yazma."
            )
            async with httpx.AsyncClient() as jc:
                jr = await jc.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": judge_prompt}], "max_tokens": 10},
                    timeout=15.0,
                )
                jdata = jr.json()
                if "choices" in jdata:
                    score_text = jdata["choices"][0]["message"]["content"].strip()
                    m = re.search(r"([1-9]|10)", score_text)
                    if m:
                        judge_score = int(m.group(1))
        except Exception:
            pass

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
