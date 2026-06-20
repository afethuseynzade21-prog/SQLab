"""
LLM Client — Groq API ilə əlaqə üçün mərkəzləşdirilmiş köməkçi.
Əvvəllər hər endpoint öz httpx.AsyncClient kodunu təkrarlayırdı —
indi vahid funksiya istifadə olunur.
"""
import os
import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"


async def call_groq(prompt: str, max_tokens: int = 1500, timeout: float = 30.0) -> str:
    """Groq API-yə sorgu gonderir, metn cavabi qaytarir."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        return "API xetasi: " + str(data.get("error", data))
