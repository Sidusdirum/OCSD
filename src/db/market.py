from typing import Optional, Dict, Any, List

from src.db.db_manager import get_connection

# Регионы
REGION_THE_FORGE = 10000002    # Jita
REGION_DELVE = 10000060
REGION_DOMAIN = 10000043       # Amarr
REGION_SINQ_LAISON = 10000032  # Dodixie

# Системы
SYSTEM_JITA = 30000142
SYSTEM_AMARR = 30002187
SYSTEM_DODIXIE = 30002659

DEFAULT_REGION_ID = REGION_THE_FORGE


def get_price(typeid: int, region_id: int = DEFAULT_REGION_ID) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM price_snapshots WHERE typeid = ? AND region_id = ?",
            (typeid, region_id),
        ).fetchone()
        return dict(row) if row else None


def get_prices_bulk(
        typeids: List[int], region_id: int = DEFAULT_REGION_ID
) -> Dict[int, Dict[str, Any]]:
    if not typeids:
        return {}
    placeholders = ",".join("?" * len(typeids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM price_snapshots WHERE typeid IN ({placeholders}) AND region_id = ?",
            [*typeids, region_id],
        ).fetchall()
    return {r["typeid"]: dict(r) for r in rows}


def get_region_name(region_id: int) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute("SELECT name FROM regions WHERE region_id = ?", (region_id,)).fetchone()
        return row['name'] if row else None


def list_regions() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT region_id, name FROM regions ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_system_info(system_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT s.system_id, s.name, s.security_status,
                   r.region_id, r.name AS region_name
            FROM solar_systems s
            JOIN regions r ON r.region_id = s.region_id
            WHERE s.system_id = ?
        """, (system_id,)).fetchone()
        return dict(row) if row else None