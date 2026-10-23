import math
from typing import List, Dict, Any, Optional, Tuple
import sqlite3

from src.db.db_manager import (
    get_connection,
    create_user_bpc,
    list_user_bpcs_for_bp_with_source,
    get_invention_info_for_t2_product,
    get_item_name,
)
from src.core.invention import calculate_invention_cost


VALID_STATUSES = ("planned", "in_progress", "done", "cancelled")


# ==========================================
# 1. Сценарии
# ==========================================

def create_scenario(
        bp_typeid: int, label: str, total_product_qty: int, bpc_max_runs: int,
        me: int, te: int = 0, user_bpc_id: Optional[int] = None,
        job_cost_per_run: float = 0.0, is_invention_scenario: bool = False,
) -> int:
    with get_connection() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO production_scenarios "
                "(label, bp_typeid, me, te, total_product_qty, bpc_max_runs, user_bpc_id, "
                " job_cost_per_run, is_invention_scenario) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (label, bp_typeid, me, te, total_product_qty, bpc_max_runs,
                 user_bpc_id, job_cost_per_run, 1 if is_invention_scenario else 0),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"Сценарий с именем '{label}' для этого чертежа уже существует.")


def list_all_scenarios() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                s.id, s.label, s.bp_typeid, s.me, s.te,
                s.total_product_qty, s.bpc_max_runs, s.user_bpc_id,
                s.is_invention_scenario, s.is_active, s.status,
                p.product_typeid,
                COALESCE(i.name_ru, i.name_en) AS product_name
            FROM production_scenarios s
            LEFT JOIN blueprint_products p
                ON p.blueprint_typeid = s.bp_typeid AND p.activity = 'manufacturing'
            LEFT JOIN items i ON i.typeid = p.product_typeid
            ORDER BY s.is_active DESC, s.status, s.id
        """).fetchall()
        return [dict(r) for r in rows]


def group_scenarios_by_product() -> Dict[int, List[Dict[str, Any]]]:
    """Группировка на лету: {product_typeid: [scenarios]}."""
    result: Dict[int, List[Dict[str, Any]]] = {}
    for s in list_all_scenarios():
        pid = s.get('product_typeid')
        if pid is None:
            continue
        result.setdefault(pid, []).append(s)
    return result


def set_active_scenario(scenario_id: int) -> None:
    """Сбрасывает is_active у всех сценариев того же bp_typeid и ставит у выбранного."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT bp_typeid FROM production_scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Сценарий #{scenario_id} не найден")
        bp_typeid = row['bp_typeid']
        conn.execute(
            "UPDATE production_scenarios SET is_active = 0 WHERE bp_typeid = ?",
            (bp_typeid,),
        )
        conn.execute(
            "UPDATE production_scenarios SET is_active = 1 WHERE id = ?",
            (scenario_id,),
        )
        conn.commit()


def set_scenario_status(scenario_id: int, status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Неверный статус: {status}. Допустимо: {VALID_STATUSES}")
    with get_connection() as conn:
        conn.execute(
            "UPDATE production_scenarios SET status = ? WHERE id = ?",
            (status, scenario_id),
        )
        conn.commit()


# ==========================================
# 2. Стратегии
# ==========================================

def set_component_strategy(scenario_id: int, typeid: int, produce_self: bool) -> None:
    flag = 1 if produce_self else 0
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO scenario_components (scenario_id, typeid, produce_self) "
            "VALUES (?, ?, ?)",
            (scenario_id, typeid, flag),
        )
        conn.commit()


def get_strategy_map_for_scenario(scenario_id: int) -> Dict[int, bool]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT typeid, produce_self FROM scenario_components WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchall()
        return {r['typeid']: bool(r['produce_self']) for r in rows}


def collect_all_component_ids(tree: List[Dict[str, Any]]) -> List[int]:
    ids: List[int] = []
    for node in tree:
        if node.get("is_root"):
            continue
        if node.get("has_own_bp"):
            ids.append(node["typeid"])
        if node.get("children"):
            ids.extend(collect_all_component_ids(node["children"]))
    return ids


# ==========================================
# 3. Ввод
# ==========================================

def _input_int(prompt: str, min_val: int, max_val: Optional[int] = None) -> int:
    while True:
        try:
            value = int(input(prompt).strip())
        except ValueError:
            print("❌ Введите целое число.")
            continue
        if value < min_val:
            print(f"❌ Значение должно быть >= {min_val}.")
            continue
        if max_val is not None and value > max_val:
            print(f"❌ Значение должно быть <= {max_val}.")
            continue
        return value


def _input_float(prompt: str, min_val: float = 0.0) -> float:
    while True:
        try:
            value = float(input(prompt).strip())
        except ValueError:
            print("❌ Введите число.")
            continue
        if value < min_val:
            print(f"❌ Значение должно быть >= {min_val}.")
            continue
        return value


# ==========================================
# 4. Готовый BPC
# ==========================================

def _choose_or_create_bpc(
        bp_typeid: int, scenario_label: str
) -> Tuple[Optional[int], int]:
    existing = list_user_bpcs_for_bp_with_source(bp_typeid)

    if existing:
        print("\n💾 Уже есть сохранённые BPC для этого чертежа:")
        print(f"   {'ID':>3} | {'Метка':<28} | {'Runs':>5} | {'ME':>3} | "
              f"{'Источник':<10} | {'Стоимость':>15}")
        print("   " + "-" * 80)
        for b in existing:
            source = b.get('source_type') or '—'
            cost = f"{b['base_cost']:>15,.0f}" if b.get('base_cost') is not None else f"{'—':>15}"
            print(
                f"   {b['id']:>3} | {(b['label'] or '')[:28]:<28} | "
                f"{b['max_runs']:>5} | {b['me_current']:>3} | "
                f"{source[:10]:<10} | {cost}"
            )

        print("\n  0. Создать новый BPC")
        choice = input("Введите ID существующего BPC или 0 для создания нового: ").strip()

        if choice != "0":
            try:
                bpc_id = int(choice)
            except ValueError:
                print("❌ Неверный ID, создаём новый BPC.")
                bpc_id = 0

            if bpc_id > 0:
                selected = next((b for b in existing if b['id'] == bpc_id), None)
                if selected:
                    print(f"✅ Используем BPC #{selected['id']} '{selected['label']}' "
                          f"(runs={selected['max_runs']})")
                    return selected['id'], selected['max_runs']
                print("❌ BPC с таким ID не найден, создаём новый.")

    print("\n🆕 Создание нового BPC")
    bpc_runs = _input_int("📜 Сколько ранов в твоём BPC (1, 10, ...): ", min_val=1)

    print("\n🏷️ Как получен этот BPC?")
    print("  1. Копирование с BPO (copy)")
    print("  2. Покупка на рынке/контракте (market)")

    source_choice = input("Выбор (1/2, Enter = 1): ").strip()
    source_type = "copy"
    base_cost = 0.0

    if source_choice == "2":
        source_type = "market"
        base_cost = _input_float("💰 Цена покупки BPC в ISK: ")
    else:
        base_cost = _input_float("💰 Стоимость копирования в ISK (Enter = 0): ")

    bpc_label = input(f"📝 Метка BPC (Enter = '{scenario_label}_BPC'): ").strip() or f"{scenario_label}_BPC"

    new_id = create_user_bpc(
        bp_typeid=bp_typeid,
        label=bpc_label,
        me=0, te=0,
        max_runs=bpc_runs,
        source_type=source_type,
        base_cost=base_cost,
    )

    if not new_id:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, max_runs FROM user_bpc WHERE label = ?", (bpc_label,)
            ).fetchone()
            if row:
                print(f"ℹ️ Используем существующий BPC '{bpc_label}' (ID: {row['id']})")
                return row['id'], row['max_runs']
        return None, bpc_runs

    print(f"✅ Создан BPC '{bpc_label}' (ID: {new_id}, runs={bpc_runs})")
    return new_id, bpc_runs


# ==========================================
# 5. Инвент-сценарий
# ==========================================

def _create_invention_scenario(
        bp_typeid: int, t2_product_typeid: int, label: str, total_qty: int
) -> Tuple[int, int, int, int, int, Optional[int], Dict[int, bool]]:
    print("\n🔬 Настройка инвента")
    info = get_invention_info_for_t2_product(t2_product_typeid)
    if not info:
        raise ValueError(f"Не найдена информация об инвенте для продукта {t2_product_typeid}")

    print(f"   T1 чертёж (источник): {info['t1_bp_typeid']} ({get_item_name(info['t1_bp_typeid'])})")
    print(f"   Базовый шанс из SDE: {info['probability']}")
    print(f"   Ранов в T2 BPC: {info['t2_runs_per_bpc']}")
    print(f"   Дейтакоров: {len(info['datacores'])}")
    for d in info['datacores']:
        print(f"     - {get_item_name(d['material_typeid'])} x {d['quantity']}")

    t1_cost = _input_float("💰 Стоимость 1 рана T1 BPC (Enter = 0): ")

    use_dec = input("Использовать декриптор? (да/нет): ").strip().lower()
    decryptor_typeid = None
    if use_dec in ("да", "y", "yes"):
        decryptor_typeid = _input_int("TypeID декриптора: ", min_val=1)

    use_override = input("Переопределить базовый шанс? (да/нет): ").strip().lower()
    base_chance = None
    if use_override in ("да", "y", "yes"):
        base_chance = _input_float("Базовый шанс (0.0-1.0): ", min_val=0.01)

    if len(info['datacores']) >= 2:
        dc_a = info['datacores'][0]['material_typeid']
        dc_a_qty = int(info['datacores'][0]['quantity'])
        dc_b = info['datacores'][1]['material_typeid']
        dc_b_qty = int(info['datacores'][1]['quantity'])
    else:
        raise ValueError("В SDE меньше 2 дейтакоров — не можем продолжить")

    virtual_bpc = calculate_invention_cost(
        t2_product_typeid=t2_product_typeid,
        datacore_a_typeid=dc_a, datacore_a_qty=dc_a_qty,
        datacore_b_typeid=dc_b, datacore_b_qty=dc_b_qty,
        decryptor_typeid=decryptor_typeid,
        base_chance_override=base_chance,
        t1_bpc_cost_per_run=t1_cost,
    )
    if not virtual_bpc:
        raise ValueError("Не удалось рассчитать инвент")

    print(f"\n✅ Инвент:")
    print(f"   Шанс: {virtual_bpc.success_chance*100:.1f}%")
    print(f"   Ожидаемая стоимость T2 BPC: {virtual_bpc.expected_cost:,.0f} ISK")
    print(f"   ME инвентованного BPC: {virtual_bpc.me}%, runs: {virtual_bpc.runs}")

    job_cost = _input_float("💸 Стоимость 1 рана (ISK, Enter = 0): ")

    scenario_id = create_scenario(
        bp_typeid, label, total_qty, virtual_bpc.runs, virtual_bpc.me, te=0,
        user_bpc_id=None, job_cost_per_run=job_cost,
        is_invention_scenario=True,
    )

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO scenario_invention
            (scenario_id, t1_bp_typeid, t1_bpc_runs, t1_bpc_cost_per_run,
             datacore_a_typeid, datacore_a_qty, datacore_b_typeid, datacore_b_qty,
             decryptor_typeid, base_chance, t2_bp_typeid, t2_product_typeid, is_ship)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (scenario_id, info['t1_bp_typeid'], 1, t1_cost,
              dc_a, dc_a_qty, dc_b, dc_b_qty, decryptor_typeid,
              virtual_bpc.success_chance, info['t2_bp_typeid'],
              t2_product_typeid, 1))
        conn.commit()

    print(f"✅ Сценарий '{label}' создан (ID: {scenario_id})")
    return scenario_id, total_qty, virtual_bpc.runs, virtual_bpc.me, 0, None, {}


# ==========================================
# 6. Главный диалог создания
# ==========================================

def create_new_scenario_interactive(
        bp_typeid: int,
        t2_product_typeid: int,
        is_t2: bool,
        max_production_limit: Optional[int] = None,
) -> Tuple[int, int, int, int, int, Optional[int], Dict[int, bool]]:
    label = input("📝 Имя нового сценария: ").strip() or "Default"
    total_qty = _input_int("📦 Сколько предметов хотим произвести всего: ", min_val=1)

    if is_t2:
        print("\n🏷️ Как получаем T2 BPC?")
        print("  1. Готовый BPC (покупка/копирование)")
        print("  2. Инвент")
        source = input("Выбор (1/2, Enter = 1): ").strip()
        if source == "2":
            return _create_invention_scenario(
                bp_typeid, t2_product_typeid, label, total_qty
            )

    user_bpc_id, bpc_runs = _choose_or_create_bpc(bp_typeid, label)

    jobs = math.ceil(total_qty / bpc_runs)
    actual_runs = jobs * bpc_runs
    if max_production_limit is not None and actual_runs > max_production_limit:
        print(
            f"⚠️ Внимание: для {total_qty} шт. понадобится {actual_runs} ранов, "
            f"а лимит чертежа — {max_production_limit}. "
            f"Будет использовано {jobs} BPC (фактически {actual_runs} ранов)."
        )

    me = _input_int("🧠 Material Efficiency (ME, 0-20): ", min_val=0, max_val=20)
    job_cost = _input_float("💸 Стоимость 1 рана (ISK, Enter = 0): ")

    while True:
        try:
            scenario_id = create_scenario(
                bp_typeid, label, total_qty, bpc_runs, me, te=0,
                user_bpc_id=user_bpc_id, job_cost_per_run=job_cost,
                is_invention_scenario=False,
            )
            print(f"✅ Сценарий '{label}' создан (ID: {scenario_id})")
            return scenario_id, total_qty, bpc_runs, me, 0, user_bpc_id, {}
        except ValueError as e:
            print(f"❌ {e}")
            new_label = input("📝 Введите другое имя (Enter — отмена): ").strip()
            if not new_label:
                raise ValueError("Создание отменено.")
            label = new_label

def get_scenario_by_id(scenario_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает полные данные сценария по его ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM production_scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        return dict(row) if row else None