"""
SQLab RAG — Semantic Table Search
Cədvəl sxemlərini embedding-ə çevirir, sual üçün ən oxşar cədvəlləri tapır.
"""
import json
import sqlite3
import numpy as np
from pathlib import Path
from typing import Optional

EMBEDDING_DB = Path(__file__).parent.parent / "semantic_embeddings.db"


def _get_model():
    """Embedding modelini yüklə (lazy loading)."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    except ImportError:
        return None


def init_embedding_db():
    """Embedding bazasını yarad."""
    conn = sqlite3.connect(EMBEDDING_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS table_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            db_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            description TEXT,
            embedding TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(db_name, table_name)
        )
    """)
    conn.commit()
    conn.close()


def embed_schema(db_name: str, schema_text: str) -> int:
    """
    Sxemi analiz edib hər cədvəl üçün embedding yaradır.
    Returns: embedded table count
    """
    model = _get_model()
    if model is None:
        return 0

    init_embedding_db()

    # Sxemi cədvəllərə ayır
    tables = {}
    current_table = None
    for line in schema_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("==="):
            continue
        if line.endswith(":") and not line.startswith("-") and not line.startswith(" "):
            current_table = line.rstrip(":")
            tables[current_table] = []
        elif current_table and line:
            tables[current_table].append(line)

    if not tables:
        return 0

    conn = sqlite3.connect(EMBEDDING_DB)
    count = 0

    # Azərbaycan dilində cədvəl açıqlamaları
    az_descriptions = {
        "olist_orders_dataset": "sifarişlər sifariş order status çatdırılma tarix alış vaxtı",
        "olist_customers_dataset": "müştərilər müştəri şəhər region əyalət zip poçt",
        "olist_order_payments_dataset": "ödəniş ödəmə kredit kartı boleto taksit ödəniş növü məbləğ",
        "olist_order_reviews_dataset": "rəy şərh reytinq qiymət bal məmnuniyyət score",
        "olist_order_items_dataset": "satış qiymət gəlir məhsul miqdarı freight çatdırılma haqqı",
        "olist_products_dataset": "məhsul kateqoriya ad çəki ölçü en uzunluq hündürlük",
        "olist_sellers_dataset": "satıcı mağaza şəhər əyalət ünvan zip",
        "product_category_name_translation": "kateqoriya adı ingilis dilində tərcümə",
    }

    for table_name, columns in tables.items():
        az_desc = az_descriptions.get(table_name, "")
        description = f"Cədvəl: {table_name}. {az_desc}. Sütunlar: {', '.join(columns[:10])}"
        embedding = model.encode(description).tolist()
        embedding_json = json.dumps(embedding)

        conn.execute("""
            INSERT OR REPLACE INTO table_embeddings
            (db_name, table_name, description, embedding)
            VALUES (?, ?, ?, ?)
        """, (db_name, table_name, description, embedding_json))
        count += 1

    conn.commit()
    conn.close()
    return count


def find_relevant_tables(db_name: str, question: str, top_k: int = 5) -> list[str]:
    """
    Sual üçün ən oxşar cədvəlləri tapır.
    Returns: table name list
    """
    model = _get_model()
    if model is None:
        return []

    conn = sqlite3.connect(EMBEDDING_DB)
    rows = conn.execute(
        "SELECT table_name, embedding FROM table_embeddings WHERE db_name = ?",
        (db_name,)
    ).fetchall()
    conn.close()

    if not rows:
        return []

    question_emb = model.encode(question)

    scores = []
    for table_name, emb_json in rows:
        table_emb = np.array(json.loads(emb_json))
        # Cosine similarity
        score = float(np.dot(question_emb, table_emb) /
                      (np.linalg.norm(question_emb) * np.linalg.norm(table_emb) + 1e-8))
        scores.append((table_name, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return [t[0] for t in scores[:top_k]]


def filter_schema_rag(schema_text: str, db_name: str, question: str) -> str:
    """
    RAG ilə sxemi filtrələ — ən oxşar cədvəlləri qaytar.
    Fallback: keyword-based filter.
    """
    relevant = find_relevant_tables(db_name, question, top_k=5)

    if not relevant:
        return schema_text  # RAG yoxdursa tam sxem

    lines = schema_text.split("\n")
    filtered = []
    include = False
    current_table = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("==="):
            filtered.append(line)
            continue
        if stripped.endswith(":") and not stripped.startswith("-") and not stripped.startswith(" "):
            current_table = stripped.rstrip(":")
            include = current_table in relevant
        if include:
            filtered.append(line)

    result = "\n".join(filtered) if filtered else schema_text
    return result if len(result) > 50 else schema_text
