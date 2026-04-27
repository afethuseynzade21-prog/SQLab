"""
data_source/excel.py — Excel / CSV Data Source
Excel və CSV fayllarını yükləyib SQLite-a çevirir, sonra SQL sorğusu icra edir.
"""

import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd


SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}


class ExcelDataSource:
    """Excel/CSV faylını yükləyib SQLite-da sorğu icra edir."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.table_name = self._safe_table_name(self.file_path.stem)
        self._conn: Optional[sqlite3.Connection] = None
        self._df: Optional[pd.DataFrame] = None

    def _safe_table_name(self, name: str) -> str:
        """Fayl adından təhlükəsiz SQL cədvəl adı düzəldir."""
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if name[0].isdigit():
            name = "t_" + name
        return name.lower()

    def load(self) -> None:
        """Faylı oxuyub SQLite-a yükləyir."""
        ext = self.file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Dəstəklənməyən fayl formatı: {ext}. "
                             f"Dəstəklənənlər: {SUPPORTED_EXTENSIONS}")

        if ext == ".csv":
            self._df = pd.read_csv(self.file_path, encoding="utf-8-sig")
        elif ext == ".tsv":
            self._df = pd.read_csv(self.file_path, sep="\t", encoding="utf-8-sig")
        else:
            self._df = pd.read_excel(self.file_path)

        # Sütun adlarını təmizlə
        self._df.columns = [
            re.sub(r"[^a-zA-Z0-9_]", "_", str(c)).strip("_").lower()
            for c in self._df.columns
        ]

        # In-memory SQLite
        self._conn = sqlite3.connect(":memory:")
        self._df.to_sql(self.table_name, self._conn, if_exists="replace", index=False)

    def get_schema(self) -> str:
        """Sxemi mətn formatında qaytarır."""
        if self._df is None:
            self.load()
        schema = f"=== FAYL: {self.file_path.name} ===\n"
        schema += f"\nCədvəl adı: {self.table_name}\n"
        schema += f"Sətir sayı: {len(self._df)}\n"
        schema += "\nSütunlar:\n"
        for col, dtype in zip(self._df.columns, self._df.dtypes):
            schema += f"  {col} ({dtype})\n"
        # İlk 3 sətri nümunə kimi göstər
        schema += "\nNümunə məlumat (ilk 3 sətir):\n"
        schema += self._df.head(3).to_string(index=False) + "\n"
        return schema

    def execute(self, sql: str) -> list[dict]:
        """SQL sorğusunu icra edir və nəticəni qaytarır."""
        if self._conn is None:
            self.load()
        cursor = self._conn.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def get_excel_schema(file_path: str) -> tuple[str, Optional["ExcelDataSource"]]:
    """Faylı yükləyib sxemi qaytarır."""
    try:
        ds = ExcelDataSource(file_path)
        ds.load()
        return ds.get_schema(), ds
    except Exception as e:
        return f"Fayl oxuma xətası: {e}", None


def execute_excel_sql(ds: "ExcelDataSource", sql: str) -> tuple[list[dict], str]:
    """
    SQL sorğusunu Excel datasource-da icra edir.
    Returns: (rows, error_message)
    """
    try:
        # Cədvəl adını avtomatik əvəz et — LLM yanlış ad yaza bilər
        sql_fixed = re.sub(
            r"\bFROM\s+\w+",
            f"FROM {ds.table_name}",
            sql,
            flags=re.IGNORECASE,
            count=1,
        )
        rows = ds.execute(sql_fixed)
        return rows, ""
    except Exception as e:
        return [], str(e)
