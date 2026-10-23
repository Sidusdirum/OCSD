from typing import List, Dict, Any, Optional
import math

from src.db.db_manager import get_item_name
from src.console_ui.formatting import format_time, format_qty, print_tree_visual
from src.core.profit import ProfitReport


def calculate_requirements_from_tree(tree: List[Dict[str, Any]]) -> Dict[int, int]:
    """Суммирует итоговые qty из готового дерева."""
    totals: Dict[int, int] = {}

    def traverse(node: Dict[str, Any]) -> None:
        tid = node.get("typeid")
        if tid is not None:
            totals[tid] = totals.get(tid, 0) + node.get("qty", 0)
        for child in node.get("children", []):
            traverse(child)

    for root in tree:
        traverse(root)
    return totals


def report_results(
        tree: List[Dict[str, Any]],
        totals: Dict[int, int],
        total_product_qty: int,
        bpc_max_runs: int,
        me: int,
        root_time_seconds: float,
) -> None:
    jobs = math.ceil(total_product_qty / bpc_max_runs)
    actual_runs = jobs * bpc_max_runs

    print(
        f"\n🌲 ДЕРЕВО ПРОИЗВОДСТВА "
        f"(хотим {total_product_qty} шт., BPC={bpc_max_runs} ранов, "
        f"заданий: {jobs}, фактически ранов: {actual_runs}, ME={me}%)"
    )
    print_tree_visual(tree)

    print("\n💰 Итоговые потребности (по убыванию количества):")
    if not totals:
        print("   (нет компонентов для расчёта)")
    else:
        for tid, qty in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            print(f"   {get_item_name(tid)} (ID: {tid}): {format_qty(qty)} шт.")

    total_seconds = root_time_seconds * actual_runs
    print("\n⏱️ Время производства (только по корневому чертежу):")
    print(f"   {format_time(total_seconds)} ({int(total_seconds):,} сек.)")
    print(f"   ME: {me}%, ранов: {actual_runs}")
    print("   ⚠️ Время по дочерним чертежам здесь не учитывается.")


def _fmt(v: Optional[float], width: int = 15) -> str:
    """Форматирует число или прочерк, если None."""
    if v is None:
        return f"{'—':>{width}}"
    return f"{v:>{width},.2f}"


def print_profit_report(report: ProfitReport, price_mode: str = "default") -> None:
    # Маркеры для активных колонок в текущем режиме
    mark_buy_max = "*" if price_mode == "default" else " "
    mark_sell_min = "*" if price_mode == "default" else " "
    mark_buy_pct = "*" if price_mode == "realistic" else " "
    mark_sell_pct = "*" if price_mode == "realistic" else " "

    print(f"\n📋 РАСКЛАДКА ЗАКУПОК С РЫНКА (режим: {price_mode}):")
    if not report.purchased_items:
        print("   (нет покупных предметов)")
    else:
        header = (
            f"   {'Предмет':<34} {'Кол-во':>9} | "
            f"{'BUY max'+mark_buy_max:>13} {'BUY %ile'+mark_buy_pct:>13} | "
            f"{'SELL min'+mark_sell_min:>13} {'SELL %ile'+mark_sell_pct:>13} | "
            f"{'Сумма(исп.)':>15}"
        )
        print(header)
        print("   " + "-" * len(header))

        for item in sorted(report.purchased_items, key=lambda x: -(x.total_price_used or 0)):
            total = (
                f"{item.total_price_used:>15,.0f}"
                if item.total_price_used is not None
                else f"{'НЕТ ЦЕНЫ':>15}"
            )
            print(
                f"   {item.name[:34]:<34} {item.qty:>9,} | "
                f"{_fmt(item.buy_max, 13)} {_fmt(item.buy_percentile, 13)} | "
                f"{_fmt(item.sell_min, 13)} {_fmt(item.sell_percentile, 13)} | "
                f"{total}"
            )
        print("   " + "-" * len(header))
        print(
            f"   {'ИТОГО материалов:':<34} {'':>9} | {'':>13} {'':>13} | "
            f"{'':>13} {'':>13} | {report.cost_materials:>15,.0f}"
        )
        if price_mode == "default":
            print("   * Закупки по BUY max (консервативно: покупаем по высокой цене)")
        elif price_mode == "realistic":
            print("   * Закупки по SELL %ile (реалистично: с учётом глубины стакана)")
        elif price_mode == "best":
            print("   * Закупки по SELL min (оптимистично: лучший sell-ордер)")

    print("\n💵 ЭКОНОМИКА ПРОИЗВОДСТВА (ISK):")
    print(f"   Готовая продукция: {report.product_name} (ID: {report.product_typeid})")
    print(f"     ├─ BUY max (продажа по лучшей):        {_fmt(report.product_buy_max, 18)}")
    print(f"     ├─ BUY %ile (продажа реалистичная):    {_fmt(report.product_buy_percentile, 18)}")
    print(f"     ├─ SELL min (покупка по лучшей):       {_fmt(report.product_sell_min, 18)}")
    print(f"     └─ SELL %ile (покупка реалистичная):   {_fmt(report.product_sell_percentile, 18)}")

    # Явно показываем, какая цена пошла в расчёт
    if price_mode == "default":
        used_price = report.product_sell_min
        used_label = "SELL min"
    elif price_mode == "best":
        used_price = report.product_buy_max
        used_label = "BUY max"
    else:
        used_price = report.product_buy_percentile
        used_label = "BUY %ile"

    if used_price is not None and used_price > 0:
        print(f"   💰 Цена продукции для расчёта: {used_label} = {used_price:,.2f} ISK/шт")
    else:
        print(f"   ⚠️ Цена продукции для расчёта ({used_label}) не найдена!")

    print(f"\n   Выручка (грязная, best):      {report.revenue_gross_best:>18,.0f}")
    print(f"   Выручка (грязная, realistic): {report.revenue_gross_realistic:>18,.0f}")
    print(f"   Выручка (грязная, default):   {report.revenue_gross_default:>18,.0f}")
    print(f"   Выручка (после налогов):      {report.revenue_net_default:>18,.0f}")

    print(f"   Затраты:")
    print(f"     ├─ Материалы:               {report.cost_materials:>15,.0f}")
    print(f"     ├─ Стоимость BPC:           {report.cost_bpc:>15,.0f}")
    print(f"     └─ Стоимость работ:         {report.cost_jobs:>15,.0f}")
    print(f"   ИТОГО затрат:                 {report.cost_total:>18,.0f}")
    print("   " + "-" * 50)

    color = "\033[92m" if report.profit > 0 else "\033[91m"
    reset = "\033[0m"

    print(f"   ПРИБЫЛЬ:                      {color}{report.profit:>18,.0f}{reset}")
    print(f"   МАРЖА:                        {color}{report.margin_percent:>17.2f}%{reset}")

    if not report.is_complete:
        missing_names = ", ".join(get_item_name(t) for t in report.missing_prices[:5])
        extra = "..." if len(report.missing_prices) > 5 else ""
        print(f"\n⚠️ Нет цен на {len(report.missing_prices)} предметов: {missing_names}{extra}")
        print("   Себестоимость и/или выручка неполные.")