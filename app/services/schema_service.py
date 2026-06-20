"""
Schema Service — verilenler bazasi sxeminin oxunmasi, acar-soz filtri
ve semantik layer (YAML) idare edilmesi.
"""
import asyncpg
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent  # app/


def get_db_name(db_url: str) -> str:
    return db_url.rstrip("/").split("/")[-1]


def load_semantic(db_url: str) -> str:
    """Bazaya aid semantic_{db_name}.yaml faylini oxuyur (varsa)."""
    try:
        import yaml
        db_name = get_db_name(db_url)
        path = ROOT_DIR / f"semantic_{db_name}.yaml"
        if not path.exists():
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        lines = ["\n=== SEMANTIK LAYER ==="]
        if "tables" in data:
            for tbl, info in data["tables"].items():
                label = info.get("label", "")
                desc = info.get("description", "")
                lines.append(f"  {tbl} -> {label}: {desc}")
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


TABLE_KEYWORDS = {
    "olist_orders_dataset": ["sifaris", "order", "status", "catdirilma", "tarix", "delivery", "purchase"],
    "olist_customers_dataset": ["musteri", "customer", "seher", "city", "eyalet", "state", "region"],
    "olist_order_items_dataset": ["mehsul", "product", "qiymet", "price", "gelir", "revenue", "satis", "seller", "satici"],
    "olist_order_payments_dataset": ["odenis", "payment", "kredit", "credit", "boleto", "taksit"],
    "olist_order_reviews_dataset": ["rey", "review", "reytinq", "rating", "score"],
    "olist_products_dataset": ["mehsul", "product", "kateqoriya", "category"],
    "olist_sellers_dataset": ["satici", "seller", "vendor"],
    "product_category_name_translation": ["kateqoriya", "category", "ingilis", "english"],
}

# Hansi cedvel secilende hansi elaveler de lazimdir (JOIN ucun)
RELATED_TABLES = {
    "olist_order_items_dataset": ["olist_orders_dataset", "olist_products_dataset"],
    "olist_order_reviews_dataset": ["olist_orders_dataset"],
    "olist_customers_dataset": ["olist_orders_dataset"],
    "olist_order_payments_dataset": ["olist_orders_dataset"],
}


def filter_schema(schema_text: str, question: str) -> str:
    """Acar-soz esasli sxem filtri (RAG elcatmaz oldugda fallback)."""
    q = question.lower()
    selected = set()
    for table, keywords in TABLE_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            selected.add(table)

    if not selected:
        return schema_text

    for table in list(selected):
        selected.update(RELATED_TABLES.get(table, []))

    lines = schema_text.split("\n")
    filtered = []
    include = True
    for line in lines:
        stripped = line.strip().rstrip(":")
        if stripped in TABLE_KEYWORDS:
            include = stripped in selected
        if include:
            filtered.append(line)
    return "\n".join(filtered) if filtered else schema_text


async def get_schema(db_url: str):
    """PostgreSQL baglantisi acir, sxemi metn seklinde qaytarir, baglantini da qaytarir."""
    try:
        conn = await asyncpg.connect(db_url)
        col_rows = await conn.fetch("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        schema: dict = {}
        for r in col_rows:
            t = r["table_name"]
            schema.setdefault(t, []).append(f"{r['column_name']} ({r['data_type']})")
        schema_text = "=== VERILENLER BAZASI SXEMI ===\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"
        return schema_text, conn
    except Exception as e:
        return f"Baza qosulma xetasi: {e}", None
