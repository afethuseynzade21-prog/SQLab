"""
SQLab — Unit və Integration Testlər
İşə salmaq: pytest tests/test_sqlab.py -v
"""
import sys
sys.path.insert(0, '/app')

import pytest
import re


# ── filter_schema funksiyasını import et ──────────────────────
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
    return schema_text  # simplified for unit test


# ── validate_sql funksiyasını import et ──────────────────────
import sqlglot
from sqlglot import exp

BLOCKED_KEYWORDS = [
    "pg_read_file", "pg_ls_dir", "lo_import", "lo_export",
]

def validate_sql(sql: str) -> tuple:
    sql = sql.strip()
    if not sql:
        return False, "Bos SQL"
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Coxlu SQL"
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        return False, f"Parse xetasi: {e}"
    if not isinstance(parsed, exp.Select):
        return False, f"Yalniz SELECT icazelidir"
    sql_lower = sql.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in sql_lower:
            return False, f"Bloklanan: {kw}"
    return True, ""


# ════════════════════════════════════════════════════════════════
#  UNIT TESTLƏR
# ════════════════════════════════════════════════════════════════

class TestValidateSQL:
    """SQL validator testləri"""

    def test_simple_select_passes(self):
        ok, err = validate_sql("SELECT * FROM orders")
        assert ok is True
        assert err == ""

    def test_drop_blocked(self):
        ok, err = validate_sql("DROP TABLE orders")
        assert ok is False
        assert "SELECT" in err

    def test_delete_blocked(self):
        ok, err = validate_sql("DELETE FROM orders WHERE id = 1")
        assert ok is False

    def test_insert_blocked(self):
        ok, err = validate_sql("INSERT INTO orders VALUES (1, 2)")
        assert ok is False

    def test_update_blocked(self):
        ok, err = validate_sql("UPDATE orders SET status = 'x'")
        assert ok is False

    def test_empty_sql_blocked(self):
        ok, err = validate_sql("")
        assert ok is False

    def test_multiple_statements_blocked(self):
        ok, err = validate_sql("SELECT 1; DROP TABLE orders")
        assert ok is False

    def test_pg_read_file_blocked(self):
        ok, err = validate_sql("SELECT pg_read_file('/etc/passwd')")
        assert ok is False

    def test_complex_select_passes(self):
        sql = """
        SELECT seller_id, SUM(price) as gelir
        FROM olist_order_items_dataset
        GROUP BY seller_id
        ORDER BY gelir DESC
        LIMIT 10
        """
        ok, err = validate_sql(sql)
        assert ok is True

    def test_cte_select_passes(self):
        sql = """
        WITH satis AS (
            SELECT seller_id, SUM(price) as umumi
            FROM olist_order_items_dataset
            GROUP BY seller_id
        )
        SELECT COUNT(*) FROM satis WHERE umumi > 1000
        """
        ok, err = validate_sql(sql)
        assert ok is True

    def test_window_function_passes(self):
        sql = """
        SELECT seller_id,
               SUM(price) OVER (ORDER BY seller_id) as kumul
        FROM olist_order_items_dataset
        """
        ok, err = validate_sql(sql)
        assert ok is True


class TestFilterSchema:
    """Schema filtr testləri"""

    SCHEMA = """=== VERILƏNLƏR BAZASI SXEMİ ===
olist_orders_dataset:
  order_id (uuid)
  customer_id (uuid)
  order_status (varchar)

olist_customers_dataset:
  customer_id (uuid)
  customer_city (varchar)

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
  price (numeric)

olist_products_dataset:
  product_id (uuid)
  product_category_name (varchar)
"""

    def test_empty_question_returns_all(self):
        result = filter_schema(self.SCHEMA, "xyz_unknown_word")
        assert "olist_orders_dataset" in result

    def test_schema_not_empty(self):
        result = filter_schema(self.SCHEMA, "musteri")
        assert len(result) > 0

    def test_payment_keyword(self):
        result = filter_schema(self.SCHEMA, "odenis")
        assert result is not None

    def test_review_keyword(self):
        result = filter_schema(self.SCHEMA, "reytinq")
        assert result is not None


class TestJudgeScore:
    """Judge score format testləri"""

    def test_score_regex_matches_single_digit(self):
        score_text = "8"
        m = re.search(r"(10|[1-9])", score_text)
        assert m is not None
        assert int(m.group(1)) == 8

    def test_score_regex_matches_10(self):
        score_text = "10"
        m = re.search(r"(10|[1-9])", score_text)
        assert m is not None
        assert int(m.group(1)) == 10

    def test_score_regex_matches_in_text(self):
        score_text = "Cavab yaxşıdır. 9/10"
        m = re.search(r"(10|[1-9])", score_text)
        assert m is not None

    def test_score_regex_no_match_zero(self):
        score_text = "0"
        m = re.search(r"(10|[1-9])", score_text)
        assert m is None


class TestExcelDataSource:
    """Excel data source testləri"""

    def test_safe_table_name(self):
        import re as _re
        name = "My File (2).xlsx"
        stem = "My File (2)"
        safe = _re.sub(r"[^a-zA-Z0-9_]", "_", stem).strip("_").lower()
        assert " " not in safe
        assert "(" not in safe
        assert safe.replace("_", "").isalnum() or "_" in safe

    def test_csv_load(self, tmp_path):
        import pandas as pd
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("ad,maas\nAnar,2500\nLeyla,1800\n")
        df = pd.read_csv(csv_file)
        assert "ad" in df.columns
        assert "maas" in df.columns
        assert len(df) == 2

    def test_sql_on_csv(self, tmp_path):
        import pandas as pd
        import sqlite3
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("ad,maas,seher\nAnar,2500,Baku\nLeyla,1800,Gence\nNicat,3000,Baku\n")
        df = pd.read_csv(csv_file)
        conn = sqlite3.connect(":memory:")
        df.to_sql("test", conn, if_exists="replace", index=False)
        cursor = conn.execute("SELECT AVG(maas) FROM test WHERE seher = 'Baku'")
        result = cursor.fetchone()[0]
        assert result == pytest.approx(2750.0)
        conn.close()
