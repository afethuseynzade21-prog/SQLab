"""
Judge Service — LLM-as-judge qiymetlendirmesi.
Her cavabi 1-10 arasi avtomatik qiymetlendirir.
"""
import re
from services.llm_client import call_groq


async def judge_answer(message: str, answer: str) -> "int | None":
    """Agentin cavabini 1-10 arasi qiymetlendirir. Xeta olarsa None qaytarir."""
    judge_prompt = (
        "SQL agentinin cavabini 1-10 arasi qiymetlendir.\n\n"
        "Sual: " + message + "\n\n"
        "Cavab: " + answer[:600] + "\n\n"
        "YALNIZ bir reqem yaz (1-10). Basqa hec ne yazma."
    )
    try:
        score_text = await call_groq(judge_prompt, max_tokens=10, timeout=15.0)
        m = re.search(r"(10|[1-9])", score_text.strip())
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None
