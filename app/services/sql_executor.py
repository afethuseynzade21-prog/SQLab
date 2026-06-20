"""
SQL Executor — LLM cavabindan SQL cixarma ve neticenin formatlanmasi.
PostgreSQL ve Excel endpoint-leri arasinda tekrarlanan kod buraya tasinib.
"""
import re


def extract_sql(llm_answer: str) -> "str | None":
    """LLM cavabindan ```sql``` blokunu cixarir."""
    m = re.search(r"```sql\s*(.*?)\s*```", llm_answer, re.DOTALL)
    return m.group(1).strip() if m else None


def format_rows(rows: list) -> str:
    """Sorgu neticesini cedvel metni kimi formatlasdirir."""
    if not rows:
        return "\n\n📊 Netice: bos"
    cols = list(rows[0].keys())
    header = " | ".join(cols)
    sep = "-" * len(header)
    rows_text = "\n".join([" | ".join(str(v) for v in r.values()) for r in rows[:20]])
    result = f"\n\n📊 Real neticə ({len(rows)} sətir):\n{header}\n{sep}\n{rows_text}"
    if len(rows) > 20:
        result += f"\n... +{len(rows)-20} setir"
    return result
