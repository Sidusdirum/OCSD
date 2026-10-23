import math
from typing import List, Dict, Any, Optional, Set

from src.db.db_manager import (
    get_item_names_bulk,
    get_materials_for_blueprint,
    get_blueprint_map_for_products,
    get_activity_info,
)


def build_production_tree(
        bp_typeid: int,
        depth_limit: int = 6,
        current_depth: int = 0,
        visited_bps: Optional[Set[int]] = None,
        strategy_map: Optional[Dict[int, bool]] = None,
) -> List[Dict[str, Any]]:
    if current_depth >= depth_limit:
        return []
    if visited_bps is None:
        visited_bps = set()
    if bp_typeid in visited_bps:
        return []

    materials = get_materials_for_blueprint(bp_typeid, activity="manufacturing")
    if not materials:
        return []

    activity_info = get_activity_info(bp_typeid, "manufacturing")
    has_me = activity_info['has_me'] if activity_info else 1

    visited_bps.add(bp_typeid)
    try:
        mat_ids = list(materials.keys())
        name_map = get_item_names_bulk(mat_ids)
        bp_map = get_blueprint_map_for_products(mat_ids)

        nodes: List[Dict[str, Any]] = []
        for mat_id, qty in materials.items():
            child_bp = bp_map.get(mat_id)
            has_own_bp = child_bp is not None

            produce_self = True
            if strategy_map is not None and mat_id in strategy_map:
                produce_self = strategy_map[mat_id]

            node: Dict[str, Any] = {
                "typeid": mat_id,
                "name": name_map.get(mat_id, f"Unknown:{mat_id}"),
                "quantity_per_run": qty,
                "produce": produce_self,
                "has_own_bp": has_own_bp,
                "has_me": has_me,
                "children": [],
            }
            if produce_self and has_own_bp:
                node["children"] = build_production_tree(
                    child_bp,
                    depth_limit=depth_limit,
                    current_depth=current_depth + 1,
                    visited_bps=visited_bps,
                    strategy_map=strategy_map,
                )
            nodes.append(node)
        return nodes
    finally:
        visited_bps.discard(bp_typeid)


def apply_scenario(
        tree: List[Dict[str, Any]],
        total_product_qty: int,
        me: int,
        bpc_max_runs: int,
        strategy_map: Optional[Dict[int, bool]] = None,
) -> List[Dict[str, Any]]:
    assert 0 <= me <= 20, f"ME вне диапазона: {me}"
    assert bpc_max_runs >= 1, f"bpc_max_runs должен быть >= 1"
    assert total_product_qty >= 1

    jobs_needed = math.ceil(total_product_qty / bpc_max_runs)
    actual_runs = jobs_needed * bpc_max_runs
    me_factor = 1.0 - me / 100.0

    def _apply(node: Dict[str, Any]) -> Dict[str, Any]:
        new_node = dict(node)
        base = node.get("quantity_per_run", 1)
        has_me = node.get("has_me", 1)

        if has_me:
            per_job = math.ceil(base * me_factor * bpc_max_runs)
        else:
            per_job = math.ceil(base * bpc_max_runs)  # без ME (реакции, инвент)

        new_node["qty_per_job"] = per_job
        new_node["qty"] = per_job * jobs_needed
        new_node["actual_runs"] = actual_runs

        tid = node.get("typeid")
        if tid is not None and strategy_map and tid in strategy_map:
            new_node["produce"] = strategy_map[tid]

        new_node["children"] = [_apply(c) for c in node.get("children", [])]
        return new_node

    return [_apply(root) for root in tree]


def build_scenario_tree(
        bp_typeid: int,
        total_product_qty: int,
        me: int,
        bpc_max_runs: int,
        strategy_map: Optional[Dict[int, bool]] = None,
        depth_limit: int = 6,
) -> List[Dict[str, Any]]:
    recipe_tree = build_production_tree(
        bp_typeid, depth_limit=depth_limit, strategy_map=strategy_map
    )
    return apply_scenario(recipe_tree, total_product_qty, me, bpc_max_runs, strategy_map)