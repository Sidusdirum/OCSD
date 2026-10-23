import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"
STATIC_DIR = BASE_DIR / "data" / "static"

TYPES_JSONL = STATIC_DIR / "types.jsonl"
BLUEPRINTS_JSONL = STATIC_DIR / "blueprints.jsonl"
MAP_REGIONS_JSONL = STATIC_DIR / "mapRegions.jsonl"
MAP_SOLAR_SYSTEMS_JSONL = STATIC_DIR / "mapSolarSystems.jsonl"
INV_GROUPS_JSONL = STATIC_DIR / "invGroups.jsonl"
INV_CATEGORIES_JSONL = STATIC_DIR / "invCategories.jsonl"

# Резервные имена для новых SDE (после Equinox 2024)
GROUPS_FALLBACK = STATIC_DIR / "groups.jsonl"
CATEGORIES_FALLBACK = STATIC_DIR / "categories.jsonl"

# Какие активности грузим
ACTIVITIES_TO_LOAD = ("manufacturing", "copying", "invention", "reaction")

# У каких активностей НЕТ ME/TE (нельзя исследовать)
ACTIVITIES_WITHOUT_ME = ("copying", "invention", "reaction")

MAX_ERRORS_TO_PRINT = 10


def _find_file(primary: Path, fallback: Path) -> Path | None:
    if primary.exists():
        return primary
    if fallback.exists():
        return fallback
    return None


def _empty_stats(*keys: str) -> Dict[str, int]:
    return {k: 0 for k in keys}


# ==========================================
# 1. Предметы
# ==========================================

def load_types(conn: sqlite3.Connection) -> Dict[str, int]:
    if not TYPES_JSONL.exists():
        raise FileNotFoundError(f"Файл не найден: {TYPES_JSONL}")

    print(f"📂 Загрузка предметов из {TYPES_JSONL.name}...")
    rows = []
    stats = _empty_stats("total", "loaded", "skipped")
    errors = 0

    with TYPES_JSONL.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                tid = item.get("_key")
                name_obj = item.get("name")
                if isinstance(name_obj, dict):
                    name_en = name_obj.get("en")
                    name_ru = name_obj.get("ru")
                else:
                    name_en = name_ru = None
                name = name_en or name_ru or f"Unknown_{tid}"
                group_id = item.get("groupID")

                if tid is not None and name:
                    rows.append((tid, name, name_ru, group_id))
                    stats["loaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO items (typeid, name_en, name_ru, group_id) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    print(f"✅ Загружено {stats['loaded']} предметов (пропущено {stats['skipped']}).")
    return stats


# ==========================================
# 2. Категории и группы
# ==========================================

def load_item_categories(conn: sqlite3.Connection) -> Dict[str, int]:
    path = _find_file(INV_CATEGORIES_JSONL, CATEGORIES_FALLBACK)
    if not path:
        print(f"⚠️ Не найден файл категорий (ни {INV_CATEGORIES_JSONL.name}, ни {CATEGORIES_FALLBACK.name}), пропускаем.")
        return _empty_stats("total", "loaded", "skipped")

    print(f"📂 Загрузка категорий из {path.name}...")
    rows = []
    stats = _empty_stats("total", "loaded", "skipped")
    errors = 0

    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                cat = json.loads(line)
                cat_id = cat.get("_key")
                name_obj = cat.get("name")
                name_en = name_obj.get("en") if isinstance(name_obj, dict) else None
                name_ru = name_obj.get("ru") if isinstance(name_obj, dict) else None
                name = name_en or name_ru or f"Unknown_{cat_id}"

                if cat_id is not None and name:
                    rows.append((cat_id, name))
                    stats["loaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO item_categories (category_id, name) VALUES (?, ?)",
            rows,
        )
        conn.commit()

    print(f"✅ Загружено {stats['loaded']} категорий.")
    return stats


def load_item_groups(conn: sqlite3.Connection) -> Dict[str, int]:
    path = _find_file(INV_GROUPS_JSONL, GROUPS_FALLBACK)
    if not path:
        print(f"⚠️ Не найден файл групп (ни {INV_GROUPS_JSONL.name}, ни {GROUPS_FALLBACK.name}), пропускаем.")
        return _empty_stats("total", "loaded", "skipped")

    print(f"📂 Загрузка групп из {path.name}...")
    rows = []
    stats = _empty_stats("total", "loaded", "skipped")
    errors = 0

    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                grp = json.loads(line)
                group_id = grp.get("_key")
                category_id = grp.get("categoryID")
                name_obj = grp.get("name")
                name_en = name_obj.get("en") if isinstance(name_obj, dict) else None
                name_ru = name_obj.get("ru") if isinstance(name_obj, dict) else None
                name = name_en or name_ru or f"Unknown_{group_id}"

                if group_id is not None and category_id is not None and name:
                    rows.append((group_id, category_id, name))
                    stats["loaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO item_groups (group_id, category_id, name) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()

    print(f"✅ Загружено {stats['loaded']} групп.")
    return stats


# ==========================================
# 3. Регионы и системы
# ==========================================

def load_regions(conn: sqlite3.Connection) -> Dict[str, int]:
    if not MAP_REGIONS_JSONL.exists():
        print(f"⚠️ Файл не найден: {MAP_REGIONS_JSONL}, пропускаем.")
        return _empty_stats("total", "loaded", "skipped")

    print(f"📂 Загрузка регионов из {MAP_REGIONS_JSONL.name}...")
    rows = []
    stats = _empty_stats("total", "loaded", "skipped")
    errors = 0

    with MAP_REGIONS_JSONL.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                reg = json.loads(line)
                region_id = reg.get("_key")
                name_obj = reg.get("name")
                name_en = name_obj.get("en") if isinstance(name_obj, dict) else None
                name_ru = name_obj.get("ru") if isinstance(name_obj, dict) else None
                name = name_en or name_ru or f"Unknown_{region_id}"

                if region_id is not None and name:
                    rows.append((region_id, name))
                    stats["loaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO regions (region_id, name) VALUES (?, ?)",
            rows,
        )
        conn.commit()

    print(f"✅ Загружено {stats['loaded']} регионов.")
    return stats


def load_solar_systems(conn: sqlite3.Connection) -> Dict[str, int]:
    if not MAP_SOLAR_SYSTEMS_JSONL.exists():
        print(f"⚠️ Файл не найден: {MAP_SOLAR_SYSTEMS_JSONL}, пропускаем.")
        return _empty_stats("total", "loaded", "skipped")

    print(f"📂 Загрузка солнечных систем из {MAP_SOLAR_SYSTEMS_JSONL.name}...")
    rows = []
    stats = _empty_stats("total", "loaded", "skipped")
    errors = 0

    with MAP_SOLAR_SYSTEMS_JSONL.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                sys = json.loads(line)
                system_id = sys.get("_key")
                region_id = sys.get("regionID")
                constellation_id = sys.get("constellationID")
                security_status = sys.get("securityStatus")
                name_obj = sys.get("name")
                name_en = name_obj.get("en") if isinstance(name_obj, dict) else None
                name_ru = name_obj.get("ru") if isinstance(name_obj, dict) else None
                name = name_en or name_ru or f"Unknown_{system_id}"

                if system_id is not None and region_id is not None and name:
                    rows.append((system_id, name, region_id, constellation_id, security_status))
                    stats["loaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO solar_systems "
            "(system_id, name, region_id, constellation_id, security_status) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    print(f"✅ Загружено {stats['loaded']} солнечных систем.")
    return stats


# ==========================================
# 4. Чертежи (manufacturing, copying, invention, reaction)
# ==========================================

def load_blueprints(conn: sqlite3.Connection) -> Dict[str, int]:
    if not BLUEPRINTS_JSONL.exists():
        raise FileNotFoundError(f"Файл не найден: {BLUEPRINTS_JSONL}")

    print(f"📂 Обработка чертежей из {BLUEPRINTS_JSONL.name}...")

    bp_rows: List[tuple] = []
    act_rows: List[tuple] = []
    mat_rows: List[tuple] = []
    prod_rows: List[tuple] = []

    stats = _empty_stats(
        "total_lines", "bps_loaded", "activities_loaded",
        "materials_loaded", "products_loaded", "skipped",
    )
    errors = 0
    activities_found: Dict[str, int] = {a: 0 for a in ACTIVITIES_TO_LOAD}

    with BLUEPRINTS_JSONL.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            stats["total_lines"] += 1
            line = line.strip()
            if not line:
                continue
            try:
                bp = json.loads(line)
                bp_typeid = bp.get("blueprintTypeID")
                if bp_typeid is None:
                    stats["skipped"] += 1
                    continue

                max_prod_limit = bp.get("maxProductionLimit")
                bp_rows.append((bp_typeid, max_prod_limit))
                stats["bps_loaded"] += 1

                activities = bp.get("activities", {})
                if not isinstance(activities, dict):
                    continue

                for activity_name in ACTIVITIES_TO_LOAD:
                    act_data = activities.get(activity_name)
                    if not isinstance(act_data, dict):
                        continue

                    activities_found[activity_name] = activities_found.get(activity_name, 0) + 1

                    time_sec = act_data.get("time", 0) or 0
                    has_me = 0 if activity_name in ACTIVITIES_WITHOUT_ME else 1
                    act_rows.append((bp_typeid, activity_name, float(time_sec), has_me))
                    stats["activities_loaded"] += 1

                    materials = act_data.get("materials", [])
                    if isinstance(materials, list):
                        for mat in materials:
                            mat_tid = mat.get("typeID")
                            qty = mat.get("quantity", 0)
                            if mat_tid is not None and qty > 0:
                                mat_rows.append((bp_typeid, activity_name, mat_tid, float(qty)))
                                stats["materials_loaded"] += 1

                    products = act_data.get("products", [])
                    if isinstance(products, list):
                        for prod in products:
                            prod_tid = prod.get("typeID")
                            qty = prod.get("quantity", 0)
                            prob = prod.get("probability")
                            if prod_tid is not None and qty > 0:
                                prod_rows.append((
                                    bp_typeid, activity_name, prod_tid,
                                    int(qty), float(prob) if prob is not None else None
                                ))
                                stats["products_loaded"] += 1

            except Exception as e:
                stats["skipped"] += 1
                if errors < MAX_ERRORS_TO_PRINT:
                    print(f"❌ Ошибка парсинга строки {line_no}: {e}")
                    errors += 1

    if bp_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO blueprints (blueprint_typeid, max_production_limit) VALUES (?, ?)",
            bp_rows,
        )
    if act_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO blueprint_activities "
            "(blueprint_typeid, activity, time_seconds, has_me) VALUES (?, ?, ?, ?)",
            act_rows,
        )
    if mat_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO blueprint_materials "
            "(blueprint_typeid, activity, material_typeid, quantity) VALUES (?, ?, ?, ?)",
            mat_rows,
        )
    if prod_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO blueprint_products "
            "(blueprint_typeid, activity, product_typeid, quantity, probability) VALUES (?, ?, ?, ?, ?)",
            prod_rows,
        )
    conn.commit()

    print(f"✅ Чертежей: {stats['bps_loaded']}")
    print(f"✅ Активностей: {stats['activities_loaded']}")
    print(f"✅ Материалов: {stats['materials_loaded']}")
    print(f"✅ Продуктов: {stats['products_loaded']}")
    print("\n📊 Активности (сколько чертежей с каждой):")
    for act in ACTIVITIES_TO_LOAD:
        n = activities_found.get(act, 0)
        status = "✅" if n > 0 else "⚠️"
        print(f"   {status} {act:<15} {n:>6}")
    if stats['skipped']:
        print(f"⚠️ Пропущено строк: {stats['skipped']}")
    return stats


# ==========================================
# 5. Main
# ==========================================

def main():
    print("🚀 OCSD_Flow: Import Static Data (v4 — с реакциями)")
    print("-" * 60)

    if not DB_PATH.exists():
        print(f"⚠️ Файл БД не найден: {DB_PATH}")
        print("💡 Сначала запустите setup_sql.py, чтобы создать схему!")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        load_item_categories(conn)
        load_item_groups(conn)
        load_regions(conn)
        load_solar_systems(conn)
        load_types(conn)
        load_blueprints(conn)
    finally:
        conn.close()

    print("-" * 60)
    print("🎉 Импорт статических данных завершён!")
    print("⚠️ Внимание: данные НЕ перезаписываются (INSERT OR IGNORE).")
    print("   Для полного сброса используйте scripts/setup_sql.py.")


if __name__ == "__main__":
    main()