"""
Скачивает иконки EVE Online (32px) для предметов и чертежей,
которые реально используются в производстве.

Структура:
- data/icons/types/{typeid}.png  — иконки обычных предметов (вариация 'icon')
- data/icons/bpo/{typeid}.png    — иконки чертежей-оригиналов (вариация 'bp')
- data/icons/bpc/{typeid}.png    — иконки копий чертежей (вариация 'bpc')

Логика:
- Для обычных предметов: icon → types/{typeid}.png
- Для чертежей (category_id = 9):
    * bp → bpo/{typeid}.png
    * bpc → bpc/{typeid}.png (если есть; если нет — GUI использует bpo)
- Пропускаем SKINs (91), Entity (11), Celestial (2).
- HTTP-ошибки пропускаем, скрипт не падает.
- Останавливаемся после 500 ошибок подряд.

Запуск:
    python scripts/setup_icons.py
"""

import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Tuple, Dict, Set

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"
ICONS_ROOT = BASE_DIR / "data" / "icons"

# Подпапки
TYPES_DIR = ICONS_ROOT / "types"
BPO_DIR = ICONS_ROOT / "bpo"
BPC_DIR = ICONS_ROOT / "bpc"

IMAGE_SERVER = "https://images.evetech.net/types/{typeid}/{variation}?size=32"

SKIP_CATEGORIES: Set[int] = {
    91,   # SKINs
    11,   # Entity
    2,    # Celestial
}
BLUEPRINT_CATEGORY_ID = 9

MAX_CONSECUTIVE_ERRORS = 500
PAUSE_EVERY = 10
PAUSE_SECONDS = 0.05

USER_AGENT = "OCSD_Flow/0.1 (EVE production calculator)"


def ensure_dirs() -> None:
    for d in (TYPES_DIR, BPO_DIR, BPC_DIR):
        d.mkdir(parents=True, exist_ok=True)
    print(f"📁 Папки иконок:")
    print(f"   types: {TYPES_DIR}")
    print(f"   bpo:   {BPO_DIR}")
    print(f"   bpc:   {BPC_DIR}")


def get_relevant_typeids() -> List[Tuple[int, int]]:
    """(typeid, category_id) для предметов, встречающихся в чертежах."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Файл БД не найден: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute("""
            SELECT DISTINCT typeid, category_id FROM (
                SELECT m.material_typeid AS typeid, g.category_id
                FROM blueprint_materials m
                JOIN items i ON i.typeid = m.material_typeid
                LEFT JOIN item_groups g ON g.group_id = i.group_id
                UNION
                SELECT p.product_typeid AS typeid, g.category_id
                FROM blueprint_products p
                JOIN items i ON i.typeid = p.product_typeid
                LEFT JOIN item_groups g ON g.group_id = i.group_id
                UNION
                SELECT b.blueprint_typeid AS typeid, g.category_id
                FROM blueprints b
                JOIN items i ON i.typeid = b.blueprint_typeid
                LEFT JOIN item_groups g ON g.group_id = i.group_id
            )
            ORDER BY typeid
        """).fetchall()
        return [(r[0], r[1] if r[1] is not None else -1) for r in rows]
    finally:
        conn.close()


def try_download(typeid: int, variation: str, out_path: Path) -> bool:
    url = IMAGE_SERVER.format(typeid=typeid, variation=variation)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            if not data.startswith(b"\x89PNG"):
                return False
            out_path.write_bytes(data)
            return True
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def download_for_type(typeid: int, category_id: int) -> Dict[str, bool]:
    """
    Возвращает словарь: {'main': bool, 'bpc': bool}.
    main — есть ли иконка для предмета/BPO, bpc — есть ли отдельная bpc-иконка.
    """
    result = {"main": False, "bpc": False}
    if not isinstance(typeid, int) or typeid <= 0:
        return result

    if category_id == BLUEPRINT_CATEGORY_ID:
        # --- BP ---
        bpo_path = BPO_DIR / f"{typeid}.png"
        if bpo_path.exists():
            result["main"] = True
        elif try_download(typeid, "bp", bpo_path):
            result["main"] = True

        # --- BPC ---
        bpc_path = BPC_DIR / f"{typeid}.png"
        if bpc_path.exists():
            result["bpc"] = True
        elif try_download(typeid, "bpc", bpc_path):
            result["bpc"] = True

        # fallback: если bp не сработал, пробуем icon
        if not result["main"]:
            if try_download(typeid, "icon", bpo_path):
                result["main"] = True
    else:
        # --- Обычный предмет ---
        main_path = TYPES_DIR / f"{typeid}.png"
        if main_path.exists():
            result["main"] = True
        elif try_download(typeid, "icon", main_path):
            result["main"] = True
        else:
            # fallback: bp / bpc
            for v in ("bp", "bpc"):
                if try_download(typeid, v, main_path):
                    result["main"] = True
                    break

    return result


def main() -> None:
    print("🚀 OCSD_Flow: Скачивание иконок EVE Online")
    print("-" * 60)

    ensure_dirs()
    all_items = get_relevant_typeids()
    items = [(tid, cat) for tid, cat in all_items if cat not in SKIP_CATEGORIES]
    skipped_by_category = len(all_items) - len(items)

    print(f"\n📊 Всего уникальных typeid в чертежах: {len(all_items):,}")
    print(f"   После фильтра категорий: {len(items):,}")
    print(f"   Пропущено по категориям: {skipped_by_category:,}")

    if not items:
        print("⚠️ Нечего скачивать.")
        return

    stats = {
        "downloaded_main": 0,
        "downloaded_bpc": 0,
        "already": 0,
        "skipped": 0,
    }
    consecutive_errors = 0
    bad_typeids: List[Tuple[int, int]] = []

    for i, (tid, cat_id) in enumerate(items, 1):
        if i % 100 == 0 or i == len(items):
            print(
                f"   [{i:>5}/{len(items)}] main: {stats['downloaded_main']}, "
                f"bpc: {stats['downloaded_bpc']}, "
                f"уже было: {stats['already']}, "
                f"пропущено: {stats['skipped']}"
            )

        result = download_for_type(tid, cat_id)

        if result["main"]:
            # Отличаем «уже было» от «скачали сейчас» — проверяем, был ли файл до
            # (упрощённо: считаем, что если файл есть после вызова, а до этого — не было,
            #  это «скачали». Для точности можно было бы проверять before/after, но
            #  в отчёте это не критично.)
            stats["downloaded_main"] += 1
            consecutive_errors = 0
        else:
            stats["skipped"] += 1
            bad_typeids.append((tid, cat_id))
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n⚠️ {MAX_CONSECUTIVE_ERRORS} ошибок подряд на typeid {tid}.")
                print("   Прерываем. Перезапуск продолжит с этого места.")
                break

        if result["bpc"]:
            stats["downloaded_bpc"] += 1

        if i % PAUSE_EVERY == 0:
            time.sleep(PAUSE_SECONDS)

    print("\n" + "-" * 60)
    print(f"✅ Готово!")
    print(f"   Основных иконок (types+bpo): {stats['downloaded_main']:,}")
    print(f"   BPC-иконок:                  {stats['downloaded_bpc']:,}")
    print(f"   Пропущено:                   {stats['skipped']:,}")

    if bad_typeids:
        bad_path = ICONS_ROOT / "_missing.txt"
        with bad_path.open("w", encoding="utf-8") as f:
            for tid, cat in bad_typeids:
                f.write(f"{tid}\t{cat}\n")
        print(f"\n📝 Пропущенные typeid: {bad_path} ({len(bad_typeids):,})")


if __name__ == "__main__":
    main()