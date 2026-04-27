"""
ai/val.py — SQL Validation Engine
Yalnız SELECT sorğularına icazə verir, təhlükəli əməliyyatları bloklayır.
"""

import sqlglot
from sqlglot import exp

BLOCKED_STATEMENT_TYPES = (
    exp.Drop, exp.Delete, exp.Insert, exp.Update,
    exp.Create, exp.TruncateTable, exp.Alter,
    exp.Command, exp.Transaction,
)

BLOCKED_KEYWORDS = [
    "pg_read_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export",
    "information_schema.user_privileges",
]


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    SQL sorğusunu yoxlayır.
    Returns: (is_safe, error_message)
    """
    sql = sql.strip()
    if not sql:
        return False, "Boş SQL sorğusu"

    statements = [s.strip() for s in sql.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Çoxlu SQL sorğusu icazə verilmir (SQL injection riski)"

    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        return False, f"SQL parse xətası: {e}"

    if not isinstance(parsed, exp.Select):
        stmt_type = type(parsed).__name__
        return False, f"'{stmt_type}' əməliyyatına icazə verilmir. Yalnız SELECT icazəlidir."

    for blocked in BLOCKED_STATEMENT_TYPES:
        if parsed.find(blocked):
            return False, f"Təhlükəli əməliyyat aşkar edildi: {blocked.__name__}"

    sql_lower = sql.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in sql_lower:
            return False, f"Bloklanan funksiya: '{kw}'"

    for node in parsed.walk():
        if isinstance(node, BLOCKED_STATEMENT_TYPES):
            return False, "Subquery-də təhlükəli əməliyyat aşkar edildi"

    return True, ""
