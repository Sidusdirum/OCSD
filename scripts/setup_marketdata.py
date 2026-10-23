import csv
import gzip
import io
import sqlite3
import urllib.request
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"

AGGREGATE_URL = "https://market.fuzzwork.co.uk/aggregatecsv.csv.gz"
DEFAULT_REGION_ID = 10000002  # The Forge (Jita)

DEBUG_SAMPLE_ROWS = 5


def _to_float(value: str) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: str) -> int:
    try:
        return int(float(value)) if value not in ("", None) else 0
    except (TypeError, ValueError):
        return 0


def _parse_what(what: str) -> tuple[int, int, bool] | None:
    """
    Разбирает поле 'what' формата 'region_id|typeid|is_buy'.
    Возвращает (region_id, typeid, is_buy) или None, если формат не тот.
    """
    if not what:
        return None
    parts = what.split("|")
    if len(parts) != 3:
        return None
    try:
        region_id = int(parts[0])
        typeid = int(parts[1])
        is_buy = parts[2].strip().lower() == "true"
    except (ValueError, AttributeError):
        return None
    return region_id, typeid, is_buy


def _debug_print_headers(reader: csv.DictReader) -> None:
    if reader.fieldnames:
        print("🔍 Заголовки CSV:", reader.fieldnames)
    else:
        print("⚠️ Не удалось прочитать заголовки CSV (fieldnames пуст).")


def _debug_sample_rows(reader: csv.DictReader, limit: int = DEBUG_SAMPLE_ROWS) -> None:
    print(f"\n🔍 Первые {limit} строк (для отладки):")
    for i, row in enumerate(reader):
        if i >= limit:
            break
        keys = ["what", "maxval", "minval", "fivepercent", "volume", "numorders"]
        sample = {k: row.get(k, "<MISSING>") for k in keys}
        print(f"  Строка {i + 1}: {sample}")
    print()


def load_prices(conn: sqlite3.Connection, region_id: int = DEFAULT_REGION_ID) -> int:
    """
    Скачивает CSV Fuzzwork, склеивает buy/sell строки в одну запись на typeid
    и пишет в price_snapshots (одна строка на typeid+region).
    """
    print(f"📡 Скачивание цен Fuzzwork (region_id={region_id})...")
    with urllib.request.urlopen(AGGREGATE_URL, timeout=180) as resp:
        gz_data = resp.read()
    print(f"✅ Скачано {len(gz_data):,} байт (gzip).")

    # --- Отладка: заголовки и первые строки ---
    with gzip.open(io.BytesIO(gz_data), "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _debug_print_headers(reader)
        _debug_sample_rows(reader)

    # --- Основной проход ---
    print("📂 Парсинг CSV и склейка buy/sell...")
    by_type: Dict[int, Dict[str, Any]] = {}
    rows_total = 0
    rows_matched_region = 0
    rows_skipped = 0
    rows_bad_what = 0

    with gzip.open(io.BytesIO(gz_data), "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Проверяем наличие ожидаемых колонок до цикла
        expected = {"what", "maxval", "minval", "fivepercent", "volume", "numorders"}
        actual = set(reader.fieldnames or [])
        missing = expected - actual
        if missing:
            print(f"❌ В CSV отсутствуют ожидаемые колонки: {missing}")
            print(f"   Реальные колонки: {sorted(actual)}")
            return 0

        for row in reader:
            rows_total += 1

            parsed = _parse_what(row.get("what", ""))
            if parsed is None:
                rows_bad_what += 1
                rows_skipped += 1
                continue

            row_region, typeid, is_buy = parsed

            if row_region != region_id:
                continue
            rows_matched_region += 1

            entry = by_type.setdefault(typeid, {
                "max_buy_price": None,
                "min_sell_price": None,
                "buy_percentile": None,
                "sell_percentile": None,
                "buy_volume": None,
                "sell_volume": None,
                "buy_order_count": None,
                "sell_order_count": None,
            })

            if is_buy:
                entry["max_buy_price"] = _to_float(row.get("maxval", ""))
                entry["buy_percentile"] = _to_float(row.get("fivepercent", ""))
                entry["buy_volume"] = _to_int(row.get("volume", ""))
                entry["buy_order_count"] = _to_int(row.get("numorders", ""))
            else:
                entry["min_sell_price"] = _to_float(row.get("minval", ""))
                entry["sell_percentile"] = _to_float(row.get("fivepercent", ""))
                entry["sell_volume"] = _to_int(row.get("volume", ""))
                entry["sell_order_count"] = _to_int(row.get("numorders", ""))

    # --- Статистика ---
    print(f"\n📊 Статистика парсинга:")
    print(f"   Всего строк в CSV:              {rows_total:,}")
    print(f"   Строк для региона {region_id}:       {rows_matched_region:,}")
    print(f"   Строк с битым 'what':           {rows_bad_what:,}")
    print(f"   Пропущено всего:                {rows_skipped:,}")
    print(f"   Уникальных typeid:               {len(by_type):,}")

    if not by_type:
        print("❌ Не удалось собрать ни одной записи. Проверь отладочный вывод выше.")
        return 0

    # --- Запись в БД ---
    rows_to_insert = [
        (
            typeid,
            region_id,
            e["max_buy_price"],
            e["min_sell_price"],
            e["buy_percentile"],
            e["sell_percentile"],
            e["buy_volume"],
            e["sell_volume"],
            e["buy_order_count"],
            e["sell_order_count"],
        )
        for typeid, e in by_type.items()
    ]

    with conn:
        conn.execute("DELETE FROM price_snapshots WHERE region_id = ?", (region_id,))
        conn.executemany(
            "INSERT INTO price_snapshots "
            "(typeid, region_id, max_buy_price, min_sell_price, "
            " buy_percentile, sell_percentile, buy_volume, sell_volume, "
            " buy_order_count, sell_order_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows_to_insert,
        )

    print(f"\n✅ Загружено {len(rows_to_insert)} записей цен (region_id={region_id}).")
    return len(rows_to_insert)


def main():
    print("🚀 OCSD_Flow: Import Market Data (Fuzzwork)")
    print("-" * 60)

    if not DB_PATH.exists():
        print(f"⚠️ Файл БД не найден: {DB_PATH}")
        print("💡 Сначала запустите setup_sql.py.")
        return

    region_id = DEFAULT_REGION_ID
    try:
        user_input = input(f"🌍 region_id (Enter = {region_id}): ").strip()
        if user_input:
            region_id = int(user_input)
    except ValueError:
        print("⚠️ Неверный region_id, используем Jita по умолчанию.")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        load_prices(conn, region_id)
    finally:
        conn.close()

    print("-" * 60)
    print("🎉 Импорт цен завершён!")


if __name__ == "__main__":
    main()