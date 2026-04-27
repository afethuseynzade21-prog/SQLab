"""
data_source/mysql.py — MySQL Data Source
asyncmy ilə MySQL bağlantısı və sxem oxuma.
"""

import re
from typing import Optional

try:
    import asyncmy
    ASYNCMY_AVAILABLE = True
except ImportError:
    ASYNCMY_AVAILABLE = False


def parse_mysql_url(db_url: str) -> dict:
    """
    mysql://user:password@host:port/database formatını parse edir.
    """
    pattern = r"mysql(?:\+asyncmy)?://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)"
    m = re.match(pattern, db_url)
    if not m:
        raise ValueError(f"Yanlış MySQL URL formatı: {db_url}\n"
                         f"Düzgün format: mysql://user:password@host:port/database")
    return {
        "user":     m.group(1),
        "password": m.group(2),
        "host":     m.group(3),
        "port":     int(m.group(4) or 3306),
        "db":       m.group(5),
    }


async def get_mysql_schema(db_url: str) -> tuple[str, Optional[object]]:
    """MySQL bağlantısı qurub sxemi oxuyur."""
    if not ASYNCMY_AVAILABLE:
        return ("❌ asyncmy qurulmayıb. Qurmaq üçün:\n"
                "pip install asyncmy", None)
    try:
        params = parse_mysql_url(db_url)
        conn = await asyncmy.connect(**params)
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, ORDINAL_POSITION
            """)
            rows = await cur.fetchall()

        schema: dict[str, list[str]] = {}
        for tbl, col, dtype in rows:
            if tbl not in schema:
                schema[tbl] = []
            schema[tbl].append(f"{col} ({dtype})")

        schema_text = "=== MySQL VERİLƏNLƏR BAZASI SXEMİ ===\n"
        schema_text += f"Baza: {params['db']}\n"
        for tbl, cols in schema.items():
            schema_text += f"\n{tbl}:\n  " + "\n  ".join(cols) + "\n"

        return schema_text, conn
    except Exception as e:
        return f"MySQL bağlantı xətası: {e}", None


async def execute_mysql_sql(conn, sql: str) -> tuple[list[dict], int, str]:
    """
    MySQL-də SQL sorğusu icra edir.
    Returns: (rows, exec_ms, error)
    """
    import time
    try:
        async with conn.cursor() as cur:
            t0 = time.perf_counter()
            await cur.execute(sql)
            rows_raw = await cur.fetchall()
            exec_ms = int((time.perf_counter() - t0) * 1000)
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in rows_raw]
            return rows, exec_ms, ""
    except Exception as e:
        return [], 0, str(e)


async def close_mysql(conn) -> None:
    if conn:
        conn.close()
        await conn.wait_closed()
