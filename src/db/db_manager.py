import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"


@contextmanager
def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ==========================================
# 1. Предметы
# ==========================================

def get_item_name(typeid: int) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name_ru, name_en FROM items WHERE typeid = ?", (typeid,)
        ).fetchone()
        if not row:
            return f"Unknown Item ({typeid})"
        return row['name_ru'] or row['name_en'] or f"Unknown ({typeid})"


def get_item_names_bulk(typeids: List[int]) -> Dict[int, str]:
    if not typeids:
        return {}
    placeholders = ",".join("?" * len(typeids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT typeid, name_ru, name_en FROM items WHERE typeid IN ({placeholders})",
            typeids,
        ).fetchall()
    return {
        r['typeid']: (r['name_ru'] or r['name_en'] or f"Unknown ({r['typeid']})")
        for r in rows
    }


def find_product_by_name(name_query: str) -> List[Dict[str, Any]]:
    search = f"%{name_query.lower()}%"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT typeid, name_en, name_ru FROM items
            WHERE LOWER(COALESCE(name_en, '')) LIKE ?
               OR LOWER(COALESCE(name_ru, '')) LIKE ?
            LIMIT 10
            """,
            (search, search),
        ).fetchall()
        return [dict(r) for r in rows]


def get_item_category(typeid: int) -> Optional[Dict[str, Any]]:
    """Возвращает category_id и name для предмета через group."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT c.category_id, c.name
            FROM items i
            JOIN item_groups g ON g.group_id = i.group_id
            JOIN item_categories c ON c.category_id = g.category_id
            WHERE i.typeid = ?
        """, (typeid,)).fetchone()
        return dict(row) if row else None


def is_ship(typeid: int) -> bool:
    """Корабль ли это (category_id = 6)."""
    cat = get_item_category(typeid)
    return bool(cat and cat['category_id'] == 6)


# ==========================================
# 2. Чертежи
# ==========================================

def find_bp_by_product(product_typeid: int) -> Optional[int]:
    """Находит blueprint_typeid по product_typeid для manufacturing."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT blueprint_typeid FROM blueprint_products "
            "WHERE activity = 'manufacturing' AND product_typeid = ? LIMIT 1",
            (product_typeid,),
        ).fetchone()
        return row['blueprint_typeid'] if row else None


def get_blueprint_row(bp_typeid: int) -> Optional[Dict[str, Any]]:
    """Возвращает данные manufacturing-активности чертежа."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                b.blueprint_typeid,
                b.max_production_limit,
                a.time_seconds,
                a.has_me,
                p.product_typeid,
                p.quantity AS product_quantity
            FROM blueprints b
            JOIN blueprint_activities a
                ON a.blueprint_typeid = b.blueprint_typeid AND a.activity = 'manufacturing'
            JOIN blueprint_products p
                ON p.blueprint_typeid = b.blueprint_typeid AND p.activity = 'manufacturing'
            WHERE b.blueprint_typeid = ?
            LIMIT 1
        """, (bp_typeid,)).fetchone()
        return dict(row) if row else None


def get_materials_for_blueprint(bp_typeid: int, activity: str = "manufacturing") -> Dict[int, float]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT material_typeid, quantity FROM blueprint_materials "
            "WHERE blueprint_typeid = ? AND activity = ?",
            (bp_typeid, activity),
        ).fetchall()
        return {r['material_typeid']: float(r['quantity']) for r in rows}


def get_blueprint_map_for_products(product_typeids: List[int]) -> Dict[int, int]:
    """Пакетно: {product_typeid: blueprint_typeid} для manufacturing."""
    if not product_typeids:
        return {}
    placeholders = ",".join("?" * len(product_typeids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT product_typeid, blueprint_typeid FROM blueprint_products "
            f"WHERE activity = 'manufacturing' AND product_typeid IN ({placeholders})",
            product_typeids,
        ).fetchall()
    return {r['product_typeid']: r['blueprint_typeid'] for r in rows}


def get_activity_info(bp_typeid: int, activity: str) -> Optional[Dict[str, Any]]:
    """Время и has_me по активности."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT time_seconds, has_me FROM blueprint_activities "
            "WHERE blueprint_typeid = ? AND activity = ?",
            (bp_typeid, activity),
        ).fetchone()
        return dict(row) if row else None


def get_products_for_activity(bp_typeid: int, activity: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT product_typeid, quantity, probability FROM blueprint_products "
            "WHERE blueprint_typeid = ? AND activity = ?",
            (bp_typeid, activity),
        ).fetchall()
        return [dict(r) for r in rows]


# ==========================================
# 3. Инвент: поиск T1 → T2
# ==========================================

def get_invention_info_for_t2_product(t2_product_typeid: int) -> Optional[Dict[str, Any]]:
    """
    Для T2 продукта находит:
    - T2 чертёж (manufacturing),
    - T1 чертёж (источник инвента) через blueprint_products(activity='invention'),
    - вероятность и количество ранов из SDE,
    - дейтакоры (материалы invention у T1 чертежа).
    Возвращает словарь или None.
    """
    with get_connection() as conn:
        t2_bp = conn.execute("""
            SELECT blueprint_typeid FROM blueprint_products
            WHERE activity = 'manufacturing' AND product_typeid = ?
            LIMIT 1
        """, (t2_product_typeid,)).fetchone()
        if not t2_bp:
            return None
        t2_bp_typeid = t2_bp['blueprint_typeid']

        # T1 чертёж, из которого инвентится T2 BPC
        t1_row = conn.execute("""
            SELECT blueprint_typeid, quantity, probability
            FROM blueprint_products
            WHERE activity = 'invention' AND product_typeid = ?
            LIMIT 1
        """, (t2_bp_typeid,)).fetchone()
        if not t1_row:
            return None
        t1_bp_typeid = t1_row['blueprint_typeid']

        # Дейтакоры (материалы invention у T1 чертежа)
        datacores = conn.execute("""
            SELECT material_typeid, quantity
            FROM blueprint_materials
            WHERE blueprint_typeid = ? AND activity = 'invention'
        """, (t1_bp_typeid,)).fetchall()

    return {
        "t2_bp_typeid": t2_bp_typeid,
        "t1_bp_typeid": t1_bp_typeid,
        "probability": t1_row['probability'],
        "t2_runs_per_bpc": t1_row['quantity'],
        "datacores": [dict(d) for d in datacores],
    }


# ==========================================
# 4. Лимиты
# ==========================================

def validate_production_limit(bp_typeid: int, requested_runs: int) -> Tuple[bool, str]:
    bp = get_blueprint_row(bp_typeid)
    if not bp:
        return False, f"❌ Чертеж {bp_typeid} не найден."

    limit = bp['max_production_limit']
    if limit is None:
        return True, f"✅ Лимит не ограничен. Разрешено: {requested_runs} запусков."
    if requested_runs <= limit:
        return True, f"✅ Лимит соблюдён. Запрошено: {requested_runs}, максимум: {limit}."
    return False, (
        f"❌ Ошибка лимита! Запрошено {requested_runs}, "
        f"но у этого BPC максимум {limit} запусков."
    )


# ==========================================
# 5. Пользовательские BPC
# ==========================================

def create_user_bpc(
        bp_typeid: int,
        label: str,
        me: int = 0,
        te: int = 0,
        max_runs: int = 1,
        is_t2: bool = False,
        source_type: str = 'copy',
        base_cost: float = 0.0,
) -> Optional[int]:
    # 1. Проверяем, нет ли уже точно такого же BPC
    existing_id = find_identical_bpc(
        bp_typeid, max_runs, me, te, source_type, base_cost
    )
    if existing_id:
        return existing_id

    # 2. Если нет — создаём новый. Но нужно проверить уникальность label.
    final_label = label
    counter = 1

    with get_connection() as conn:
        # Ищем, занято ли такое имя
        while True:
            row = conn.execute(
                "SELECT id FROM user_bpc WHERE label = ?", (final_label,)
            ).fetchone()

            if not row:
                break  # Имя свободно, выходим из цикла

            # Имя занято, добавляем суффикс
            final_label = f"{label} ({counter})"
            counter += 1

        try:
            cur = conn.execute(
                "INSERT INTO user_bpc (bp_typeid, label, me_current, te_current, max_runs, is_t2) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (bp_typeid, final_label, me, te, max_runs, 1 if is_t2 else 0),
            )
            bpc_id = cur.lastrowid
            conn.execute(
                "INSERT INTO bpc_sources (user_bpc_id, source_type, base_cost) VALUES (?, ?, ?)",
                (bpc_id, source_type, base_cost),
            )
            conn.commit()
            return bpc_id
        except sqlite3.IntegrityError as e:
            print(f"⚠️ Ошибка при создании BPC: {e}")
            return None


def get_user_bpc_by_label(label: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM user_bpc WHERE label = ?", (label,)).fetchone()
        return dict(row) if row else None


def list_user_bpcs() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM user_bpc ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_user_bpcs_for_bp(bp_typeid: int) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM user_bpc WHERE bp_typeid = ?", (bp_typeid,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_user_bpcs_for_bp_with_source(bp_typeid: int) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                b.id, b.label, b.me_current, b.te_current,
                b.max_runs, b.is_t2, b.created_at,
                s.source_type, s.base_cost
            FROM user_bpc b
            LEFT JOIN bpc_sources s ON s.user_bpc_id = b.id
            WHERE b.bp_typeid = ?
            ORDER BY b.id DESC
        """, (bp_typeid,)).fetchall()
        return [dict(r) for r in rows]

def find_manufacturable_products(search_text: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Ищет продукты, у которых есть manufacturing-чертёж, по части названия."""
    search = f"%{search_text.lower()}%"
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT i.typeid, i.name_en, i.name_ru, bp.blueprint_typeid
            FROM items i
            JOIN blueprint_products bp ON bp.product_typeid = i.typeid AND bp.activity = 'manufacturing'
            WHERE LOWER(COALESCE(i.name_en, '')) LIKE ?
               OR LOWER(COALESCE(i.name_ru, '')) LIKE ?
            LIMIT ?
        """, (search, search, limit)).fetchall()
        return [dict(r) for r in rows]

def find_identical_bpc(
        bp_typeid: int,
        max_runs: int,
        me: int,
        te: int,
        source_type: str,
        base_cost: float
) -> Optional[int]:
    """
    Ищет BPC с точно такими же параметрами.
    Возвращает ID существующего BPC или None.
    """
    with get_connection() as conn:
        row = conn.execute("""
            SELECT b.id 
            FROM user_bpc b
            JOIN bpc_sources s ON s.user_bpc_id = b.id
            WHERE b.bp_typeid = ? 
              AND b.max_runs = ? 
              AND b.me_current = ? 
              AND b.te_current = ?
              AND s.source_type = ?
              AND ABS(s.base_cost - ?) < 0.01  -- Сравнение float с погрешностью
            LIMIT 1
        """, (bp_typeid, max_runs, me, te, source_type, base_cost)).fetchone()

        return row['id'] if row else None