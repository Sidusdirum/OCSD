from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import math

from src.db.db_manager import (
    get_connection,
    get_invention_info_for_t2_product,
    get_item_name,
)
from src.db.market import get_prices_bulk, DEFAULT_REGION_ID


@dataclass
class VirtualT2BPC:
    bp_typeid: int
    product_typeid: int
    runs: int
    me: int
    te: int
    expected_cost: float
    success_chance: float
    datacores: List[Dict[str, Any]]  # для отладки


def calculate_invention_cost(
        t2_product_typeid: int,
        datacore_a_typeid: int,
        datacore_a_qty: int,
        datacore_b_typeid: int,
        datacore_b_qty: int,
        decryptor_typeid: Optional[int],
        base_chance_override: Optional[float],
        t1_bpc_cost_per_run: float = 0.0,
        region_id: int = DEFAULT_REGION_ID,
) -> Optional[VirtualT2BPC]:
    """
    Считает ожидаемую стоимость T2 BPC.
    - t2_product_typeid: T2 продукт (например, Gila = 17715)
    - базовый шанс из SDE (probability), если base_chance_override=None
    - T1 BPC стоимость за ран: вводится вручную (0 если копируешь сам)
    """
    info = get_invention_info_for_t2_product(t2_product_typeid)
    if not info:
        return None

    # Шанс: из SDE или override
    base_chance = base_chance_override if base_chance_override is not None else info['probability']
    if base_chance is None:
        base_chance = 0.34  # fallback для модулей

    chance = base_chance
    runs_mod = 0
    me_mod = 0
    te_mod = 0
    decryptor_cost = 0.0

    if decryptor_typeid:
        with get_connection() as conn:
            dec = conn.execute(
                "SELECT * FROM decryptors WHERE typeid = ?", (decryptor_typeid,)
            ).fetchone()
            if dec:
                dec = dict(dec)
                chance *= dec['chance_multiplier']
                runs_mod = dec['runs_modifier']
                me_mod = dec['me_modifier']
                te_mod = dec['te_modifier']

    # Цены дейтакоров и декриптора
    price_ids = [datacore_a_typeid, datacore_b_typeid]
    if decryptor_typeid:
        price_ids.append(decryptor_typeid)
    prices = get_prices_bulk(price_ids, region_id)

    def _price(tid):
        p = prices.get(tid)
        return p.get("min_sell_price") if p else 0.0

    dc_a_cost = _price(datacore_a_typeid) * datacore_a_qty
    dc_b_cost = _price(datacore_b_typeid) * datacore_b_qty
    if decryptor_typeid:
        decryptor_cost = _price(decryptor_typeid)

    cost_per_attempt = t1_bpc_cost_per_run + dc_a_cost + dc_b_cost + decryptor_cost
    expected_cost = cost_per_attempt / chance if chance > 0 else float('inf')

    # Характеристики T2 BPC
    base_runs = info['t2_runs_per_bpc']
    t2_runs = max(1, base_runs + runs_mod)
    t2_me = max(0, 2 + me_mod)
    t2_te = max(0, 4 + te_mod)

    # Определяем, корабль ли T2 продукт (по группе)
    from src.db.db_manager import is_ship as _is_ship

    return VirtualT2BPC(
        bp_typeid=info['t2_bp_typeid'],
        product_typeid=t2_product_typeid,
        runs=t2_runs,
        me=t2_me,
        te=t2_te,
        expected_cost=expected_cost,
        success_chance=chance,
        datacores=info['datacores'],
    )