from typing import Optional, List, Dict, Any

from src.db.db_manager import (
    find_bp_by_product,
    find_product_by_name,
    get_blueprint_row,
    get_item_name,
    get_connection,
    is_ship,
    get_invention_info_for_t2_product,
)
from src.core.tree_builder import build_scenario_tree
from src.console_ui.reports import (
    calculate_requirements_from_tree,
    report_results,
    print_profit_report,
)
from src.core.bpc_management import (
    set_component_strategy,
    collect_all_component_ids,
    list_all_scenarios,
    group_scenarios_by_product,
    get_strategy_map_for_scenario,
    create_new_scenario_interactive,
    set_active_scenario,
    set_scenario_status,
    VALID_STATUSES,
)
from src.core.profit import calculate_profit
from src.core.invention import calculate_invention_cost
from src.console_ui.formatting import format_time


def resolve_product() -> Optional[int]:
    user_input = input("📦 Что хотим произвести? (название или TypeID): ").strip()
    if not user_input:
        return None

    if user_input.isdigit():
        pid = int(user_input)
        name = get_item_name(pid)
        if name.startswith("Unknown"):
            print("❌ Предмет не найден.")
            return None
        print(f"✅ Выбрано: {name} (ID: {pid})")
        return pid

    matches = find_product_by_name(user_input)
    if not matches:
        print("❌ Совпадений не найдено.")
        return None

    if len(matches) == 1:
        m = matches[0]
        print(f"✅ Найдено: {m['name_ru'] or m['name_en']} (ID: {m['typeid']})")
        return m['typeid']

    print("🔍 Найдено несколько совпадений:")
    for i, m in enumerate(matches, 1):
        print(f"  {i}. {m['name_ru'] or m['name_en']} (ID: {m['typeid']})")

    while True:
        choice = input("Номер варианта (0 — отмена): ").strip()
        if choice == "0":
            return None
        try:
            idx = int(choice) - 1
        except ValueError:
            print("❌ Введите число.")
            continue
        if 0 <= idx < len(matches):
            m = matches[idx]
            print(f"✅ Выбрано: {m['name_ru'] or m['name_en']} (ID: {m['typeid']})")
            return m['typeid']
        print("❌ Нет такого варианта.")


def interactive_strategy_setup(tree: List[Dict[str, Any]], scenario_id: int) -> None:
    print("\n🛠️ Настройка стратегии (1 = производить, 0 = покупать):")
    components = collect_all_component_ids(tree)

    if not components:
        print("ℹ️ Нет компонентов, для которых имеет смысл настраивать стратегию.")
        return

    MAX_ASK = 50
    if len(components) > MAX_ASK:
        print(f"⚠️ Найдено {len(components)} компонентов. Спросим только первые {MAX_ASK}.")
        components = components[:MAX_ASK]

    for tid in components:
        name = get_item_name(tid)
        while True:
            ans = input(f"❓ {name} (TypeID: {tid}) → [1] производить / [0] покупать: ").strip()
            if ans in ("0", "1"):
                produce = (ans == "1")
                set_component_strategy(scenario_id, tid, produce)
                print(f"   ✅ {'производим' if produce else 'покупаем'}")
                break
            print("   Введите 0 или 1.")


def run_scenario(
        scenario_id: int,
        bp_typeid: int,
        total_qty: int,
        bpc_runs: int,
        me: int,
        strategy_map: Dict[int, bool],
) -> None:
    bp_row = get_blueprint_row(bp_typeid)
    if not bp_row:
        print("❌ Данные чертежа не найдены в БД.")
        return

    product_typeid = bp_row['product_typeid']
    root_name = get_item_name(product_typeid)
    total_time_seconds = bp_row['time_seconds']

    effective_me = me
    with get_connection() as conn:
        is_inv_row = conn.execute(
            "SELECT is_invention_scenario FROM production_scenarios WHERE id = ?",
            (scenario_id,)
        ).fetchone()

        if is_inv_row and is_inv_row['is_invention_scenario']:
            inv = conn.execute(
                "SELECT * FROM scenario_invention WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
            if inv:
                inv = dict(inv)
                virtual_bpc = calculate_invention_cost(
                    t2_product_typeid=inv['t2_product_typeid'],
                    datacore_a_typeid=inv['datacore_a_typeid'],
                    datacore_a_qty=inv['datacore_a_qty'],
                    datacore_b_typeid=inv['datacore_b_typeid'],
                    datacore_b_qty=inv['datacore_b_qty'],
                    decryptor_typeid=inv['decryptor_typeid'],
                    base_chance_override=inv['base_chance'],
                    t1_bpc_cost_per_run=inv['t1_bpc_cost_per_run'],
                )
                if virtual_bpc:
                    effective_me = virtual_bpc.me
                    print(f"\n🔬 Инвент: шанс {virtual_bpc.success_chance*100:.1f}%, "
                          f"стоимость BPC: {virtual_bpc.expected_cost:,.0f} ISK, "
                          f"ME={effective_me}%")

    print(f"\n📋 Чертеж: TypeID = {bp_typeid}")
    print(f"🏭 Производим: {root_name} (TypeID: {product_typeid})")
    print(f"⏱️ Время на 1 запуск: {format_time(total_time_seconds)}")
    if bp_row['max_production_limit']:
        print(f"🚧 Лимит ранов на чертёж: {bp_row['max_production_limit']}")

    scenario_tree = build_scenario_tree(
        bp_typeid, total_qty, effective_me, bpc_runs, strategy_map, depth_limit=6
    )
    totals = calculate_requirements_from_tree(scenario_tree)

    report_results(
        scenario_tree, totals, total_qty, bpc_runs, effective_me, total_time_seconds
    )

    profit_report = calculate_profit(
        tree=scenario_tree,
        total_product_qty=total_qty,
        product_typeid=product_typeid,
        scenario_id=scenario_id,
        price_mode="default",
    )
    print_profit_report(profit_report, price_mode="default")

    ask = input("\n🔧 Настроить стратегию компонентов? (да/нет): ").strip().lower()
    if ask in ("да", "y", "yes"):
        interactive_strategy_setup(scenario_tree, scenario_id)
        print("✅ Стратегия обновлена. Перезапусти калькулятор для пересчёта.")


# ==========================================
# 3. Овервью производства
# ==========================================

STATUS_ICONS = {
    "planned": "📝",
    "in_progress": "⚙️",
    "done": "✅",
    "cancelled": "❌",
}


def show_overview() -> None:
    """Показывает овервью: группировка сценариев по продукту."""
    groups = group_scenarios_by_product()

    if not groups:
        print("\nℹ️ Сохранённых сценариев пока нет.")
        return

    print("\n📊 ОВЕРВЬЮ ПРОИЗВОДСТВА")
    print("=" * 110)

    for product_id, scenarios in groups.items():
        product_name = scenarios[0].get('product_name') or f"Product {product_id}"
        print(f"\n📦 {product_name} (ID: {product_id})")
        print(
            f"   {'ID':>3} | {'Акт':>3} | {'Статус':<12} | {'Сценарий':<25} | "
            f"{'ME':>3} | {'Кол-во':>7} | {'BPC':>5} | {'Тип':<8}"
        )
        print("   " + "-" * 100)
        for s in scenarios:
            active = "✅" if s['is_active'] else " "
            status_icon = STATUS_ICONS.get(s['status'], "?")
            inv_type = "инвент" if s['is_invention_scenario'] else "BPC"
            print(
                f"   {s['id']:>3} |  {active}  | {status_icon} {s['status']:<10} | "
                f"{(s['label'] or '')[:25]:<25} | {s['me']:>3} | "
                f"{s['total_product_qty']:>7} | {s['bpc_max_runs']:>5} | {inv_type:<8}"
            )

    print("\n" + "=" * 110)


def overview_menu() -> None:
    """Меню овервью с действиями."""
    while True:
        show_overview()
        print("\nДействия:")
        print("  1. Посчитать сценарий")
        print("  2. Сделать сценарий активным")
        print("  3. Изменить статус сценария")
        print("  0. Назад")

        choice = input("Выбор: ").strip()

        if choice == "0":
            return

        if choice == "1":
            try:
                sid = int(input("ID сценария: ").strip())
            except ValueError:
                print("❌ Введите число.")
                continue
            groups = group_scenarios_by_product()
            selected = next(
                (s for group in groups.values() for s in group if s['id'] == sid),
                None,
            )
            if not selected:
                print("❌ Сценарий не найден.")
                continue
            run_scenario(
                scenario_id=selected['id'],
                bp_typeid=selected['bp_typeid'],
                total_qty=selected['total_product_qty'],
                bpc_runs=selected['bpc_max_runs'],
                me=selected['me'],
                strategy_map=get_strategy_map_for_scenario(selected['id']),
            )

        elif choice == "2":
            try:
                sid = int(input("ID сценария для активации: ").strip())
                set_active_scenario(sid)
                print(f"✅ Сценарий #{sid} теперь активный (для своего продукта).")
            except ValueError as e:
                print(f"❌ {e}")

        elif choice == "3":
            print(f"Доступные статусы: {', '.join(VALID_STATUSES)}")
            try:
                sid = int(input("ID сценария: ").strip())
                status = input(f"Новый статус ({'/'.join(VALID_STATUSES)}): ").strip()
                set_scenario_status(sid, status)
                print(f"✅ Статус сценария #{sid} → {status}.")
            except ValueError as e:
                print(f"❌ {e}")

        else:
            print("❌ Нет такого пункта.")


# ==========================================
# 4. Создание нового сценария
# ==========================================

def create_new_scenario_flow() -> None:
    product_id = resolve_product()
    if product_id is None:
        return

    bp_typeid = find_bp_by_product(product_id)
    if not bp_typeid:
        print(f"❌ Для предмета {product_id} не найден чертеж производства.")
        return

    bp_row = get_blueprint_row(bp_typeid)
    if not bp_row:
        print("❌ Данные чертежа не найдены в БД.")
        return

    invention_info = get_invention_info_for_t2_product(product_id)
    has_invention = invention_info is not None

    try:
        scenario_id, total_qty, bpc_runs, me, te, user_bpc_id, strategy_map = (
            create_new_scenario_interactive(
                bp_typeid=bp_typeid,
                t2_product_typeid=product_id,
                is_t2=has_invention,
                max_production_limit=bp_row['max_production_limit'],
            )
        )
    except ValueError as e:
        print(f"❌ {e}")
        return

    run_scenario(
        scenario_id=scenario_id,
        bp_typeid=bp_typeid,
        total_qty=total_qty,
        bpc_runs=bpc_runs,
        me=me,
        strategy_map=strategy_map,
    )


# ==========================================
# 5. Главное меню
# ==========================================

def run_calculator() -> None:
    print("🚀 OCSD_Flow: Калькулятор производства")

    while True:
        print("\n" + "=" * 50)
        print("Главное меню:")
        print("  1. Овервью производства")
        print("  2. Создать новый сценарий")
        print("  0. Выход")
        print("=" * 50)

        choice = input("Выбор: ").strip()

        if choice == "0":
            print("👋 До встречи!")
            return
        if choice == "1":
            overview_menu()
        elif choice == "2":
            create_new_scenario_flow()
        else:
            print("❌ Нет такого пункта меню.")


if __name__ == "__main__":
    run_calculator()