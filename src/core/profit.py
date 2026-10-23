from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import math

from src.db.db_manager import get_connection, get_item_name
from src.db.market import get_prices_bulk, DEFAULT_REGION_ID


@dataclass
class PurchasedItem:
    typeid: int
    name: str
    qty: int
    buy_max: Optional[float] = None
    buy_percentile: Optional[float] = None
    sell_min: Optional[float] = None
    sell_percentile: Optional[float] = None
    unit_price_used: Optional[float] = None
    total_price_used: Optional[float] = None


@dataclass
class ProfitReport:
    cost_materials: float = 0.0
    cost_bpc: float = 0.0
    cost_jobs: float = 0.0
    cost_total: float = 0.0

    product_typeid: int = 0
    product_name: str = ""
    product_buy_max: Optional[float] = None
    product_buy_percentile: Optional[float] = None
    product_sell_min: Optional[float] = None
    product_sell_percentile: Optional[float] = None

    revenue_gross_default: float = 0.0
    revenue_gross_best: float = 0.0
    revenue_gross_realistic: float = 0.0
    revenue_net_default: float = 0.0

    profit: float = 0.0
    margin_percent: float = 0.0

    is_complete: bool = True
    missing_prices: List[int] = field(default_factory=list)
    purchased_items: List[PurchasedItem] = field(default_factory=list)

    is_invention: bool = False
    invention_cost: float = 0.0
    invention_chance: Optional[float] = None


def _collect_purchased_items(tree: List[Dict[str, Any]]) -> Dict[int, int]:
    """Собирает только те узлы, которые мы покупаем (produce=False или нет BPC)."""
    items: Dict[int, int] = {}

    def traverse(node):
        tid = node.get("typeid")
        produce = node.get("produce", False)
        has_bp = node.get("has_own_bp", False)
        if not produce or not has_bp:
            if tid is not None:
                items[tid] = items.get(tid, 0) + node.get("qty", 0)
        for child in node.get("children", []):
            traverse(child)

    for root in tree:
        traverse(root)
    return items


def _price_used(p: Optional[Dict[str, Any]], price_mode: str, side: str) -> Optional[float]:
    """Возвращает цену для расчёта."""
    if not p:
        return None

    if price_mode == "default":
        return p.get("max_buy_price") if side == "sell" else p.get("min_sell_price")

    if price_mode == "best":
        return p.get("min_sell_price") if side == "sell" else p.get("max_buy_price")

    # realistic
    return p.get("sell_percentile") if side == "sell" else p.get("buy_percentile")


def calculate_profit(
        tree: List[Dict[str, Any]],
        total_product_qty: int,
        product_typeid: int,
        scenario_id: Optional[int] = None,
        region_id: int = DEFAULT_REGION_ID,
        price_mode: str = "default",
        # --- Параметры для "живого" расчёта (если scenario_id=None или для переопределения) ---
        job_cost_per_run: Optional[float] = None,
        user_bpc_id: Optional[int] = None,
        bpc_max_runs: Optional[int] = None,
        is_invention_scenario: Optional[bool] = None,
) -> ProfitReport:
    """
    Считает экономику сценария.
    - Если передан scenario_id, базовые параметры (job_cost, user_bpc_id, bpc_max_runs)
      берутся из БД, но могут быть переопределены явными аргументами.
    - Если scenario_id=None, используются переданные аргументы (или дефолты).
    """
    # 1. Загружаем данные сценария (если есть ID)
    scenario = None
    if scenario_id is not None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM production_scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            scenario = dict(row) if row else None

    # 2. Определяем параметры
    if scenario:
        eff_job_cost = job_cost_per_run if job_cost_per_run is not None else scenario.get('job_cost_per_run', 0.0)
        eff_bpc_id = user_bpc_id if user_bpc_id is not None else scenario.get('user_bpc_id')
        eff_bpc_runs = bpc_max_runs if bpc_max_runs is not None else scenario.get('bpc_max_runs', 1)
        eff_is_invention = is_invention_scenario if is_invention_scenario is not None else (scenario.get('is_invention_scenario', 0) == 1)
        sales_tax = scenario.get('sales_tax_percent', 2.5) / 100
        broker_fee = scenario.get('broker_fee_percent', 3.0) / 100
    else:
        eff_job_cost = job_cost_per_run if job_cost_per_run is not None else 0.0
        eff_bpc_id = user_bpc_id
        eff_bpc_runs = bpc_max_runs if bpc_max_runs is not None else 1
        eff_is_invention = is_invention_scenario if is_invention_scenario is not None else False
        sales_tax = 2.5 / 100
        broker_fee = 3.0 / 100

    # 3. Job Cost
    cost_jobs = eff_job_cost * total_product_qty

    # 4. BPC Cost
    cost_bpc = 0.0
    bpc_data = None
    virtual_bpc = None

    if eff_is_invention:
        # Инвент (загрузка из scenario_invention, если есть ID сценария)
        if scenario_id:
            with get_connection() as conn:
                inv_row = conn.execute(
                    "SELECT * FROM scenario_invention WHERE scenario_id = ?", (scenario_id,)
                ).fetchone()
                if inv_row:
                    inv = dict(inv_row)
                    from src.core.invention import calculate_invention_cost
                    virtual_bpc = calculate_invention_cost(
                        t2_product_typeid=inv['t2_product_typeid'],
                        datacore_a_typeid=inv['datacore_a_typeid'],
                        datacore_a_qty=inv['datacore_a_qty'],
                        datacore_b_typeid=inv['datacore_b_typeid'],
                        datacore_b_qty=inv['datacore_b_qty'],
                        decryptor_typeid=inv['decryptor_typeid'],
                        base_chance_override=inv['base_chance'],
                        t1_bpc_cost_per_run=inv['t1_bpc_cost_per_run'],
                        region_id=region_id,
                    )
        if virtual_bpc:
            jobs_needed = math.ceil(total_product_qty / eff_bpc_runs)
            cost_bpc = virtual_bpc.expected_cost * jobs_needed
    elif eff_bpc_id:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT b.*, s.source_type, s.base_cost
                FROM user_bpc b
                LEFT JOIN bpc_sources s ON s.user_bpc_id = b.id
                WHERE b.id = ?
            """, (eff_bpc_id,)).fetchone()
            if row:
                bpc_data = dict(row)
                if bpc_data.get('source_type') in ('market', 'copy'):
                    jobs_needed = math.ceil(total_product_qty / bpc_data['max_runs'])
                    cost_bpc = bpc_data['base_cost'] * jobs_needed

    # 5. Закупки (материалы)
    purchased = _collect_purchased_items(tree)
    prices = get_prices_bulk(list(purchased.keys()) + [product_typeid], region_id)

    cost_materials = 0.0
    missing: List[int] = []
    purchased_report: List[PurchasedItem] = []

    for tid, qty in purchased.items():
        p = prices.get(tid)
        unit = _price_used(p, price_mode, side="sell")
        item = PurchasedItem(
            typeid=tid,
            name=get_item_name(tid),
            qty=qty,
            buy_max=p.get("max_buy_price") if p else None,
            buy_percentile=p.get("buy_percentile") if p else None,
            sell_min=p.get("min_sell_price") if p else None,
            sell_percentile=p.get("sell_percentile") if p else None,
        )
        if unit is None or unit == 0:
            missing.append(tid)
        else:
            item.unit_price_used = unit
            item.total_price_used = qty * unit
            cost_materials += item.total_price_used
        purchased_report.append(item)

    # 6. Цены готовой продукции
    pp = prices.get(product_typeid)
    product_buy_max = pp.get("max_buy_price") if pp else None
    product_buy_percentile = pp.get("buy_percentile") if pp else None
    product_sell_min = pp.get("min_sell_price") if pp else None
    product_sell_percentile = pp.get("sell_percentile") if pp else None

    unit_default = _price_used(pp, "default", side="buy")
    unit_best = _price_used(pp, "best", side="buy")
    unit_realistic = _price_used(pp, "realistic", side="buy")

    if unit_default is None or unit_default == 0:
        if product_typeid not in missing:
            missing.append(product_typeid)

    revenue_gross_default = total_product_qty * (unit_default or 0.0)
    revenue_gross_best = total_product_qty * (unit_best or 0.0)
    revenue_gross_realistic = total_product_qty * (unit_realistic or 0.0)

    # 7. Выручка после налогов
    revenue_net_default = revenue_gross_default * (1 - sales_tax - broker_fee)

    # 8. Итог
    total_cost = cost_materials + cost_bpc + cost_jobs
    profit = revenue_net_default - total_cost
    margin = (profit / revenue_net_default * 100) if revenue_net_default > 0 else 0.0

    return ProfitReport(
        cost_materials=cost_materials,
        cost_bpc=cost_bpc,
        cost_jobs=cost_jobs,
        cost_total=total_cost,
        product_typeid=product_typeid,
        product_name=get_item_name(product_typeid),
        product_buy_max=product_buy_max,
        product_buy_percentile=product_buy_percentile,
        product_sell_min=product_sell_min,
        product_sell_percentile=product_sell_percentile,
        revenue_gross_default=revenue_gross_default,
        revenue_gross_best=revenue_gross_best,
        revenue_gross_realistic=revenue_gross_realistic,
        revenue_net_default=revenue_net_default,
        profit=profit,
        margin_percent=margin,
        is_complete=(len(missing) == 0),
        missing_prices=missing,
        purchased_items=purchased_report,
        is_invention=eff_is_invention,
        invention_cost=cost_bpc if eff_is_invention else 0.0,
        invention_chance=virtual_bpc.success_chance if virtual_bpc else None,
    )