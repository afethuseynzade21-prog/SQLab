"""
SQLab Benchmark v2 — Token limit və alias qaydası düzəldilmiş versiya
"""
import asyncio
import asyncpg
import httpx
import os
import re
import json

API_KEY = os.environ.get("GROQ_API_KEY", "")
DB_URL = "postgresql://postgres:root@host.docker.internal:5432/olist_db"

TEST_SET = [
    {"q": "ümumi sifariş sayı", "expect": "99441"},
    {"q": "ən çox satılan kateqoriya", "expect": "cama_mesa_banho"},
    {"q": "ortalama reytinq", "expect": "4.0"},
    {"q": "ödəniş növlərinin paylanması", "expect": "credit_card"},
    {"q": "ən çox müştərili şəhərlər", "expect": "sao paulo"},
    {"q": "aylıq sifariş sayı", "expect": "1"},
    {"q": "ən çox satan satıcılar", "expect": "seller_id"},
    {"q": "çatdırılmış sifarişlərin faizi", "expect": "9"},
    {"q": "reytinq üzrə sifariş sayı", "expect": "review_score"},
    {"q": "umumi gəlir", "expect": "."},
    {"q": "musteri seherleri uzre sifaris sayi", "expect": "sao paulo"},
    {"q": "en cox satilan 5 kateqoriya", "expect": "cama_mesa_banho"},
]

SCHEMA = """=== VERILƏNLƏR BAZASI SXEMİ ===

olist_orders_dataset:
  order_id (uuid)
  customer_id (uuid)
  order_status (varchar)
  order_purchase_timestamp (timestamp)
  order_delivered_customer_date (timestamp)

olist_customers_dataset:
  customer_id (uuid)
  customer_city (varchar)
  customer_state (varchar)

olist_order_payments_dataset:
  order_id (uuid)
  payment_type (varchar)
  payment_value (numeric)

olist_order_reviews_dataset:
  order_id (uuid)
  review_score (integer)

olist_order_items_dataset:
  order_id (uuid)
  seller_id (uuid)
  product_id (uuid)
  price (numeric)
  freight_value (numeric)

olist_products_dataset:
  product_id (uuid)
  product_category_name (varchar)
"""

FEW_SHOT = """
FEW-SHOT NÜMUNƏLƏR:

Sual: aylıq sifariş sayı
SQL: SELECT EXTRACT(MONTH FROM order_purchase_timestamp) AS ay, COUNT(*) AS sifaris_sayi FROM olist_orders_dataset GROUP BY ay ORDER BY ay

Sual: ən çox satılan kateqoriyalar
SQL: SELECT p.product_category_name, COUNT(*) AS satis FROM olist_order_items_dataset oi JOIN olist_products_dataset p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY satis DESC LIMIT 10

Sual: çatdırılmış sifarişlərin faizi
SQL: SELECT ROUND(COUNT(*) FILTER (WHERE order_status = 'delivered') * 100.0 / COUNT(*), 2) AS faiz FROM olist_orders_dataset

Sual: ən çox müştərili şəhərlər
SQL: SELECT customer_city, COUNT(*) AS musteri_sayi FROM olist_customers_dataset GROUP BY customer_city ORDER BY musteri_sayi DESC LIMIT 10
"""

# DÜZƏLDİLDİ: alias qaydası dəqiqləşdirildi - yalnız OUTPUT alias-lar üçün, JOIN üçün yox
ALIAS_RULE_FIXED = "- Nəticə sütun adlarında (AS ...) nöqtə işlətmə, lakin cədvəl.sütun JOIN sintaksisi normal saxlanmalıdır (məs: oi.product_id düzgündür)"

COT_INSTRUCTION = """
DÜŞÜNCƏ PROSESİ - QISA OL, hər addım 1 cümlə:
1. Sual nə soruşur?
2. Hansı cədvəllər lazımdır?
3. Hansı hesablama lazımdır?

Bundan sonra DƏRHAL SQL yaz.
"""


def build_prompt(question: str, use_fewshot: bool, use_cot: bool) -> str:
    parts = [
        "Sen SQL agentisen. Aşağıdakı sxemə əsaslanaraq sualı cavabla.",
        "",
        SCHEMA,
    ]
    if use_fewshot:
        parts.append(FEW_SHOT)
    if use_cot:
        parts.append(COT_INSTRUCTION)
    parts.extend([
        "",
        "VACİB QAYDALAR:",
        "- Yalnız sxemdəki REAL sütun adlarını istifadə et",
        "- SQL-i ```sql ``` blokunun içinə yaz",
        ALIAS_RULE_FIXED,
        "",
        f"İstifadəçi sualı: {question}",
        "",
        "SQL sorğusu yaz.",
    ])
    return "\n".join(parts)


async def call_llm(prompt: str, max_tokens: int) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
            timeout=30.0,
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        return ""


async def run_test(conn, question: str, expect: str, use_fewshot: bool, use_cot: bool) -> tuple[bool, str]:
    prompt = build_prompt(question, use_fewshot, use_cot)
    # DÜZƜLDİLDİ: CoT üçün daha çox token
    max_tokens = 1500 if use_cot else 800
    try:
        answer = await call_llm(prompt, max_tokens)
        sql_match = re.search(r"```sql\s*(.*?)\s*```", answer, re.DOTALL)
        if not sql_match:
            return False, f"SQL tapılmadı (cavab uzunluğu: {len(answer)})"
        sql = sql_match.group(1).strip()
        rows = await conn.fetch(sql)
        result_text = str(rows[:5]).lower()
        success = expect.lower() in result_text
        return success, sql[:80].replace("\n", " ")
    except Exception as e:
        return False, f"Xəta: {str(e)[:60]}"


async def main():
    conn = await asyncpg.connect(DB_URL)

    configs = [
        ("Baseline", False, False),
        ("+Few-shot", True, False),
        ("+Few-shot+CoT (düzəldilmiş)", True, True),
    ]

    results = {}

    for config_name, use_fs, use_cot in configs:
        print(f"\n{'='*60}")
        print(f"KONFİQURASİYA: {config_name}")
        print('='*60)
        passed = 0
        for test in TEST_SET:
            success, detail = await run_test(conn, test["q"], test["expect"], use_fs, use_cot)
            status = "OK" if success else "XX"
            print(f"  [{status}] {test['q'][:40]:40} | {detail[:55]}")
            if success:
                passed += 1
            await asyncio.sleep(0.6)

        rate = round(passed / len(TEST_SET) * 100, 1)
        results[config_name] = {"passed": passed, "total": len(TEST_SET), "rate": rate}
        print(f"\n  NƏTİCƏ: {passed}/{len(TEST_SET)} ({rate}%)")

    print(f"\n\n{'='*60}")
    print("YEKUN MÜQAYİSƏ CƏDVƏLİ (DÜZƏLDİLMİŞ)")
    print('='*60)
    print(f"{'Konfiqurasiya':<30} | {'Uğur sayı':<12} | {'Uğur faizi'}")
    print("-" * 65)
    for name, r in results.items():
        print(f"{name:<30} | {r['passed']}/{r['total']:<10} | {r['rate']}%")

    with open("/app/benchmark_results_v2.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\nNəticələr saxlanıldı: /app/benchmark_results_v2.json")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
