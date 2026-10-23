"""
Выводит содержимое таблиц БД в виде простых текстовых таблиц.
Полезно для быстрой проверки данных без открытия SQL-клиента.

Запуск:
    python tests/sql_overview.py              # Показать ключевые таблицы
    python tests/sql_overview.py <table_name> # Показать конкретную таблицу
"""

import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"

# Таблицы, которые показываем по умолчанию
DEFAULT_TABLES = [
    "production_scenarios",
    "user_bpc",
    "bpc_sources",
    "scenario_components",
    "scenario_invention",
    "price_snapshots"
]


def print_table(conn: sqlite3.Connection, table_name: str, max_rows: int = 50) -> None:
    """Выводит одну таблицу в консоль."""
    print(f"\n{'=' * 80}")
    print(f"  📋 Таблица: {table_name}")
    print(f"{'=' * 80}")

    try:
        cursor = conn.execute(f"SELECT * FROM {table_name}")
    except sqlite3.OperationalError as e:
        print(f"❌ Ошибка: {e}")
        return

    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchmany(max_rows)
    total_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    if not rows:
        print("   (таблица пуста)")
        return

    # Преобразуем Row в обычные кортежи для удобства
    data = [tuple(row) for row in rows]

    # Вычисляем ширину колонок
    widths = [len(col) for col in columns]
    for row in data:
        for i, val in enumerate(row):
            # Обрезаем длинные строки (например, JSON), чтобы не ломать таблицу
            val_str = str(val) if val is not None else "NULL"
            if len(val_str) > 30:
                val_str = val_str[:27] + "..."
            widths[i] = max(widths[i], len(val_str))

    # Формируем разделитель
    separator = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    # Печатаем заголовок
    print(separator)
    header = "|" + "|".join(f" {col:<{widths[i]}} " for i, col in enumerate(columns)) + "|"
    print(header)
    print(separator)

    # Печатаем строки
    for row in data:
        row_str = "|"
        for i, val in enumerate(row):
            val_str = str(val) if val is not None else "NULL"
            if len(val_str) > 30:
                val_str = val_str[:27] + "..."
            row_str += f" {val_str:<{widths[i]}} |"
        print(row_str)

    print(separator)

    if total_count > max_rows:
        print(f"   ... (показано {max_rows} из {total_count} строк)")
    else:
        print(f"   Всего строк: {total_count}")


def main():
    if not DB_PATH.exists():
        print(f"❌ Файл БД не найден: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        if len(sys.argv) > 1:
            # Показать конкретную таблицу
            table_name = sys.argv[1]
            print_table(conn, table_name)
        else:
            # Показать все таблицы по умолчанию
            for table in DEFAULT_TABLES:
                print_table(conn, table)
    finally:
        conn.close()


if __name__ == "__main__":
    main()