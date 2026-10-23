"""
Смоук-тест SDE: проверяет, что все таблицы заполнены
и что ключевые взаимосвязи (которые использует калькулятор) работают.

Запуск:
    python tests/sde.py
"""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return row["n"] if row else 0


def _count_where(conn: sqlite3.Connection, table: str, where: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}").fetchone()
    return row["n"] if row else 0


def _print_sample(rows, columns: list[str], limit: int = 5) -> None:
    if not rows:
        print("   (пусто)")
        return
    header = "   " + " | ".join(f"{c:<20}" for c in columns)
    print(header)
    print("   " + "-" * len(header))
    for r in rows[:limit]:
        vals = []
        for c in columns:
            v = r[c] if c in r.keys() else None
            v_str = str(v) if v is not None else "—"
            vals.append(f"{v_str[:20]:<20}")
        print("   " + " | ".join(vals))


# ==========================================
# 1. Общие счётчики
# ==========================================

def check_counts(conn: sqlite3.Connection) -> None:
    _section("1. Количество строк во всех таблицах")

    tables = [
        "item_categories", "item_groups", "items",
        "regions", "solar_systems",
        "blueprints", "blueprint_activities",
        "blueprint_materials", "blueprint_products",
        "decryptors", "price_snapshots",
    ]
    for t in tables:
        try:
            n = _count(conn, t)
            status = "✅" if n > 0 else "⚠️"
            print(f"   {status} {t:<25} {n:>10,}")
        except sqlite3.OperationalError as e:
            print(f"   ❌ {t:<25} ОШИБКА: {e}")


# ==========================================
# 2. Иерархия предметов
# ==========================================

def check_item_hierarchy(conn: sqlite3.Connection) -> None:
    _section("2. Иерархия items → item_groups → item_categories")

    print("\n📊 Топ-10 категорий по количеству предметов:")
    rows = conn.execute("""
        SELECT c.category_id, c.name, COUNT(i.typeid) AS items_count
        FROM item_categories c
        LEFT JOIN item_groups g ON g.category_id = c.category_id
        LEFT JOIN items i ON i.group_id = g.group_id
        GROUP BY c.category_id
        ORDER BY items_count DESC
        LIMIT 10
    """).fetchall()
    _print_sample(rows, ["category_id", "name", "items_count"], limit=10)

    print("\n📊 Пример: категория 'Ship' (category_id = 6)")
    row = conn.execute(
        "SELECT * FROM item_categories WHERE category_id = 6"
    ).fetchone()
    if row:
        print(f"   ✅ Категория Ship: {row['name']}")
        ship_items = conn.execute("""
            SELECT i.typeid, i.name_en, g.name AS group_name
            FROM items i
            JOIN item_groups g ON g.group_id = i.group_id
            WHERE g.category_id = 6
            LIMIT 5
        """).fetchall()
        _print_sample(ship_items, ["typeid", "name_en", "group_name"])
    else:
        print("   ❌ Категория Ship (6) не найдена — что-то не так с SDE")

    print("\n📊 Предметы без группы (не должно быть много):")
    orphan = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE group_id IS NULL"
    ).fetchone()
    print(f"   Предметов без group_id: {orphan['n']:,}")


# ==========================================
# 3. Регионы и системы
# ==========================================

def check_map(conn: sqlite3.Connection) -> None:
    _section("3. Регионы и солнечные системы")

    print("\n📊 Топ-5 регионов по количеству систем:")
    rows = conn.execute("""
        SELECT r.region_id, r.name, COUNT(s.system_id) AS systems
        FROM regions r
        LEFT JOIN solar_systems s ON s.region_id = r.region_id
        GROUP BY r.region_id
        ORDER BY systems DESC
        LIMIT 5
    """).fetchall()
    _print_sample(rows, ["region_id", "name", "systems"])

    print("\n📊 Jita (system_id = 30000142):")
    jita = conn.execute("""
        SELECT s.system_id, s.name, s.security_status,
               r.name AS region_name, r.region_id
        FROM solar_systems s
        JOIN regions r ON r.region_id = s.region_id
        WHERE s.system_id = 30000142
    """).fetchone()
    if jita:
        print(f"   ✅ {jita['name']} | регион: {jita['region_name']} "
              f"({jita['region_id']}) | sec: {jita['security_status']}")
    else:
        print("   ❌ Jita не найдена")


# ==========================================
# 4. Чертежи: manufacturing
# ==========================================

def _show_blueprint_full(conn: sqlite3.Connection, bp_id: int, activity: str) -> None:
    bp = conn.execute(
        "SELECT * FROM blueprints WHERE blueprint_typeid = ?", (bp_id,)
    ).fetchone()
    if not bp:
        print("   ❌ Чертёж не найден")
        return

    act = conn.execute("""
        SELECT time_seconds, has_me FROM blueprint_activities
        WHERE blueprint_typeid = ? AND activity = ?
    """, (bp_id, activity)).fetchone()
    if act:
        print(f"   Время: {act['time_seconds']} сек., has_me: {act['has_me']}")
    else:
        print("   Время: —")

    prods = conn.execute("""
        SELECT product_typeid, quantity, probability
        FROM blueprint_products
        WHERE blueprint_typeid = ? AND activity = ?
    """, (bp_id, activity)).fetchall()
    if prods:
        print(f"   Продукты ({len(prods)}):")
        for p in prods:
            name = conn.execute(
                "SELECT name_en FROM items WHERE typeid = ?",
                (p['product_typeid'],)
            ).fetchone()
            print(f"     - {name['name_en'] if name else '?'} x {p['quantity']}"
                  + (f" (prob={p['probability']})" if p['probability'] else ""))

    mats = conn.execute("""
        SELECT material_typeid, quantity
        FROM blueprint_materials
        WHERE blueprint_typeid = ? AND activity = ?
        ORDER BY quantity DESC
        LIMIT 10
    """, (bp_id, activity)).fetchall()
    if mats:
        print(f"   Материалы (топ-10):")
        for m in mats:
            name = conn.execute(
                "SELECT name_en FROM items WHERE typeid = ?",
                (m['material_typeid'],)
            ).fetchone()
            print(f"     - {name['name_en'] if name else '?'} x {m['quantity']}")


def check_manufacturing(conn: sqlite3.Connection) -> None:
    _section("4. Manufacturing: чертёж → продукт → материалы → время")

    print("\n📊 Чертёж с наибольшим числом материалов (manufacturing):")
    row = conn.execute("""
        SELECT blueprint_typeid, COUNT(*) AS n
        FROM blueprint_materials
        WHERE activity = 'manufacturing'
        GROUP BY blueprint_typeid
        ORDER BY n DESC
        LIMIT 1
    """).fetchone()
    if row:
        bp_id = row["blueprint_typeid"]
        print(f"   blueprint_typeid = {bp_id}, материалов = {row['n']}")
        _show_blueprint_full(conn, bp_id, "manufacturing")


def check_copying(conn: sqlite3.Connection) -> None:
    _section("5. Copying: есть ли активность и её данные")

    n = _count_where(conn, "blueprint_activities", "activity = 'copying'")
    print(f"   Активностей copying: {n:,}")

    if n == 0:
        print("   ⚠️ Copying не загружен — проверить парсер")
        return

    print("\n📊 Пример чертежа с copying:")
    row = conn.execute("""
        SELECT blueprint_typeid, time_seconds, has_me
        FROM blueprint_activities
        WHERE activity = 'copying'
        LIMIT 1
    """).fetchone()
    if row:
        print(f"   blueprint_typeid = {row['blueprint_typeid']}, "
              f"время копирования = {row['time_seconds']} сек., "
              f"has_me = {row['has_me']}")


# ==========================================
# 6. Инвент: обратный поиск T1 → T2
# ==========================================

def check_invention(conn: sqlite3.Connection) -> None:
    _section("6. Инвент: обратный поиск T1 чертежа по T2 продукту")

    n = _count_where(conn, "blueprint_products", "activity = 'invention'")
    print(f"   Записей invention в blueprint_products: {n:,}")

    if n == 0:
        print("   ⚠️ Инвент не загружен — проверить парсер")
        return

    t2_product = 11578  # Covert Ops Cloaking Device II
    print(f"\n📊 Для T2 продукта {t2_product} (Covert Ops Cloaking Device II):")

    t2_bp = conn.execute("""
        SELECT blueprint_typeid, product_typeid, quantity, probability
        FROM blueprint_products
        WHERE activity = 'manufacturing' AND product_typeid = ?
    """, (t2_product,)).fetchone()

    if t2_bp:
        print(f"   ✅ T2 чертёж: {t2_bp['blueprint_typeid']}")

        t1_bp = conn.execute("""
            SELECT blueprint_typeid, quantity, probability
            FROM blueprint_products
            WHERE activity = 'invention' AND product_typeid = ?
        """, (t2_bp['blueprint_typeid'],)).fetchone()

        if t1_bp:
            print(f"   ✅ T1 чертёж (источник инвента): {t1_bp['blueprint_typeid']}")
            print(f"      базовый шанс из SDE (probability): {t1_bp['probability']}")
            print(f"      количество ранов в T2 BPC: {t1_bp['quantity']}")

            datacores = conn.execute("""
                SELECT material_typeid, quantity
                FROM blueprint_materials
                WHERE blueprint_typeid = ? AND activity = 'invention'
            """, (t1_bp['blueprint_typeid'],)).fetchall()
            print(f"      дейтакоров в рецепте: {len(datacores)}")
            for d in datacores:
                name = conn.execute(
                    "SELECT name_en FROM items WHERE typeid = ?",
                    (d['material_typeid'],)
                ).fetchone()
                print(f"        - {name['name_en'] if name else '?'} "
                      f"(ID {d['material_typeid']}) x {d['quantity']}")
        else:
            print(f"   ❌ Не нашли T1 чертёж для T2 BPC {t2_bp['blueprint_typeid']}")
    else:
        print(f"   ⚠️ T2 продукт {t2_product} не найден в manufacturing")

    print("\n📊 Распределение базовых шансов инвента (probability):")
    rows = conn.execute("""
        SELECT probability, COUNT(*) AS n
        FROM blueprint_products
        WHERE activity = 'invention' AND probability IS NOT NULL
        GROUP BY probability
        ORDER BY probability DESC
    """).fetchall()
    _print_sample(rows, ["probability", "n"], limit=20)


# ==========================================
# 7. Реакции
# ==========================================

def check_reactions(conn: sqlite3.Connection) -> None:
    _section("7. Реакции: формулы, материалы, продукты")

    n_act = _count_where(conn, "blueprint_activities", "activity = 'reaction'")
    n_prod = _count_where(conn, "blueprint_products", "activity = 'reaction'")
    n_mat = _count_where(conn, "blueprint_materials", "activity = 'reaction'")

    print(f"   Активностей reaction: {n_act:,}")
    print(f"   Продуктов reaction:   {n_prod:,}")
    print(f"   Материалов reaction:  {n_mat:,}")

    if n_act == 0:
        print("   ⚠️ Реакции не загружены — проверить парсер")
        return

    # Проверяем, что у реакций has_me = 0
    has_me_stats = conn.execute("""
        SELECT has_me, COUNT(*) AS n
        FROM blueprint_activities
        WHERE activity = 'reaction'
        GROUP BY has_me
    """).fetchall()
    print("\n📊 has_me у реакций (должно быть 0 = без ME):")
    _print_sample(has_me_stats, ["has_me", "n"])

    # Пример реакции
    print("\n📊 Пример реакции (чертёж + продукт + материалы):")
    row = conn.execute("""
        SELECT blueprint_typeid, time_seconds
        FROM blueprint_activities
        WHERE activity = 'reaction'
        LIMIT 1
    """).fetchone()
    if row:
        bp_id = row["blueprint_typeid"]
        print(f"   blueprint_typeid = {bp_id}, "
              f"время = {row['time_seconds']} сек.")

        prod = conn.execute("""
            SELECT product_typeid, quantity
            FROM blueprint_products
            WHERE blueprint_typeid = ? AND activity = 'reaction'
        """, (bp_id,)).fetchone()
        if prod:
            name = conn.execute(
                "SELECT name_en FROM items WHERE typeid = ?",
                (prod['product_typeid'],)
            ).fetchone()
            print(f"   Продукт: {name['name_en'] if name else '?'} "
                  f"x {prod['quantity']}")

        mats = conn.execute("""
            SELECT material_typeid, quantity
            FROM blueprint_materials
            WHERE blueprint_typeid = ? AND activity = 'reaction'
        """, (bp_id,)).fetchall()
        if mats:
            print(f"   Материалы ({len(mats)}):")
            for m in mats:
                name = conn.execute(
                    "SELECT name_en FROM items WHERE typeid = ?",
                    (m['material_typeid'],)
                ).fetchone()
                print(f"     - {name['name_en'] if name else '?'} x {m['quantity']}")

    # Топ-5 реакций по количеству материалов
    print("\n📊 Топ-5 реакций по количеству входных материалов:")
    rows = conn.execute("""
        SELECT bp.blueprint_typeid, i.name_en AS product_name, COUNT(m.material_typeid) AS n_mats
        FROM blueprint_materials m
        JOIN blueprint_products p ON p.blueprint_typeid = m.blueprint_typeid
                                 AND p.activity = 'reaction'
        JOIN items i ON i.typeid = p.product_typeid
        JOIN blueprints bp ON bp.blueprint_typeid = m.blueprint_typeid
        WHERE m.activity = 'reaction'
        GROUP BY m.blueprint_typeid
        ORDER BY n_mats DESC
        LIMIT 5
    """).fetchall()
    _print_sample(rows, ["blueprint_typeid", "product_name", "n_mats"], limit=5)


# ==========================================
# 8. Сводка по активностям
# ==========================================

def check_activities_summary(conn: sqlite3.Connection) -> None:
    _section("8. Сводка по активностям чертежей")

    rows = conn.execute("""
        SELECT activity,
               COUNT(*) AS n_activities,
               SUM(has_me) AS n_with_me,
               AVG(time_seconds) AS avg_time,
               MIN(time_seconds) AS min_time,
               MAX(time_seconds) AS max_time
        FROM blueprint_activities
        GROUP BY activity
        ORDER BY n_activities DESC
    """).fetchall()
    _print_sample(
        rows,
        ["activity", "n_activities", "n_with_me", "avg_time", "min_time", "max_time"],
    )

    multi = conn.execute("""
        SELECT n_activities, COUNT(*) AS n
        FROM (
            SELECT blueprint_typeid, COUNT(*) AS n_activities
            FROM blueprint_activities
            GROUP BY blueprint_typeid
        )
        GROUP BY n_activities
        ORDER BY n_activities
    """).fetchall()
    print("\n📊 Сколько активностей у одного чертежа:")
    _print_sample(multi, ["n_activities", "n"])


# ==========================================
# Main
# ==========================================

def main() -> None:
    if not DB_PATH.exists():
        print(f"❌ Файл БД не найден: {DB_PATH}")
        print("💡 Сначала запустите: python scripts/setup_sql.py и setup_staticdata.py")
        return

    print(f"🔍 Проверка SDE в БД: {DB_PATH}")

    conn = _connect()
    try:
        check_counts(conn)
        check_item_hierarchy(conn)
        check_map(conn)
        check_manufacturing(conn)
        check_copying(conn)
        check_invention(conn)
        check_reactions(conn)
        check_activities_summary(conn)
    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("  ✅ Проверка завершена")
    print("=" * 70)


if __name__ == "__main__":
    main()