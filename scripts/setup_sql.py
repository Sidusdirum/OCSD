import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sql" / "Blueprints.sqlite"


def init_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print("🗑️ Очистка и пересоздание всех таблиц...")
    tables_to_drop = [
        "scenario_components",
        "scenario_invention",
        "production_scenarios",
        "bpc_sources",
        "user_bpc",
        "price_snapshots",
        "blueprint_products",
        "blueprint_materials",
        "blueprint_activities",
        "blueprints",
        "items",
        "item_groups",
        "item_categories",
        "solar_systems",
        "regions",
        "decryptors",
    ]
    for table in tables_to_drop:
        cur.execute(f"DROP TABLE IF EXISTS {table}")

    # ==========================================
    # Справочники
    # ==========================================

    cur.execute("""
        CREATE TABLE item_categories (
            category_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE item_groups (
            group_id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY(category_id) REFERENCES item_categories(category_id)
        )
    """)

    cur.execute("""
        CREATE TABLE items (
            typeid INTEGER PRIMARY KEY,
            name_en TEXT NOT NULL,
            name_ru TEXT,
            group_id INTEGER,
            FOREIGN KEY(group_id) REFERENCES item_groups(group_id)
        )
    """)

    cur.execute("""
        CREATE TABLE regions (
            region_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE solar_systems (
            system_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            region_id INTEGER NOT NULL,
            constellation_id INTEGER,
            security_status REAL,
            FOREIGN KEY(region_id) REFERENCES regions(region_id)
        )
    """)

    # ==========================================
    # Чертежи
    # ==========================================

    cur.execute("""
        CREATE TABLE blueprints (
            blueprint_typeid INTEGER PRIMARY KEY,
            max_production_limit INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE blueprint_activities (
            blueprint_typeid INTEGER NOT NULL,
            activity TEXT NOT NULL,
            time_seconds REAL NOT NULL DEFAULT 0,
            has_me INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (blueprint_typeid, activity),
            FOREIGN KEY(blueprint_typeid) REFERENCES blueprints(blueprint_typeid)
        )
    """)

    cur.execute("""
        CREATE TABLE blueprint_materials (
            blueprint_typeid INTEGER NOT NULL,
            activity TEXT NOT NULL,
            material_typeid INTEGER NOT NULL,
            quantity REAL NOT NULL,
            PRIMARY KEY (blueprint_typeid, activity, material_typeid),
            FOREIGN KEY(blueprint_typeid) REFERENCES blueprints(blueprint_typeid),
            FOREIGN KEY(material_typeid) REFERENCES items(typeid)
        )
    """)

    cur.execute("""
        CREATE TABLE blueprint_products (
            blueprint_typeid INTEGER NOT NULL,
            activity TEXT NOT NULL,
            product_typeid INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            probability REAL,
            PRIMARY KEY (blueprint_typeid, activity, product_typeid),
            FOREIGN KEY(blueprint_typeid) REFERENCES blueprints(blueprint_typeid),
            FOREIGN KEY(product_typeid) REFERENCES items(typeid)
        )
    """)

    # ==========================================
    # Пользовательские BPC
    # ==========================================

    cur.execute("""
        CREATE TABLE user_bpc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bp_typeid INTEGER NOT NULL,
            label TEXT NOT NULL,
            me_current INTEGER NOT NULL DEFAULT 0,
            te_current INTEGER NOT NULL DEFAULT 0,
            max_runs INTEGER NOT NULL DEFAULT 1,
            is_t2 INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bp_typeid, label)
        )
    """)

    cur.execute("""
        CREATE TABLE bpc_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_bpc_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            base_cost REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(user_bpc_id) REFERENCES user_bpc(id) ON DELETE CASCADE
        )
    """)

    # ==========================================
    # Сценарии
    # ==========================================

    cur.execute("""
        CREATE TABLE production_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            bp_typeid INTEGER NOT NULL,
            me INTEGER NOT NULL,
            te INTEGER NOT NULL,
            total_product_qty INTEGER NOT NULL,
            bpc_max_runs INTEGER NOT NULL DEFAULT 1,
            user_bpc_id INTEGER,
            job_cost_per_run REAL DEFAULT 0,
            is_invention_scenario INTEGER DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN ('planned', 'in_progress', 'done', 'cancelled')),
            facility_tax_percent REAL DEFAULT 0,
            scc_surcharge_percent REAL DEFAULT 0.5,
            sales_tax_percent REAL DEFAULT 2.5,
            broker_fee_percent REAL DEFAULT 3.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(label, bp_typeid),
            FOREIGN KEY(user_bpc_id) REFERENCES user_bpc(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE scenario_components (
            scenario_id INTEGER NOT NULL,
            typeid INTEGER NOT NULL,
            produce_self INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (scenario_id, typeid),
            FOREIGN KEY(scenario_id) REFERENCES production_scenarios(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE scenario_invention (
            scenario_id INTEGER PRIMARY KEY,
            t1_bp_typeid INTEGER NOT NULL,
            t1_bpc_runs INTEGER NOT NULL DEFAULT 1,
            t1_bpc_cost_per_run REAL NOT NULL DEFAULT 0,
            datacore_a_typeid INTEGER NOT NULL,
            datacore_a_qty INTEGER NOT NULL,
            datacore_b_typeid INTEGER NOT NULL,
            datacore_b_qty INTEGER NOT NULL,
            decryptor_typeid INTEGER,
            base_chance REAL NOT NULL,
            t2_bp_typeid INTEGER NOT NULL,
            t2_product_typeid INTEGER NOT NULL,
            is_ship INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(scenario_id) REFERENCES production_scenarios(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE decryptors (
            typeid INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            chance_multiplier REAL NOT NULL,
            runs_modifier INTEGER NOT NULL,
            me_modifier INTEGER NOT NULL,
            te_modifier INTEGER NOT NULL
        )
    """)

    decryptor_data = [
        (34201, "Augmentation", 0.6, 9, -2, 2),
        (34202, "Optimized Augmentation", 0.9, 7, 2, 0),
        (34203, "Symmetry", 1.0, 2, 1, 8),
        (34204, "Process", 1.1, 0, 3, 6),
        (34205, "Accelerant", 1.2, 1, 2, 10),
        (34206, "Parity", 1.5, 3, 1, -2),
        (34207, "Attainment", 1.8, 4, -1, 4),
        (34208, "Optimized Attainment", 1.9, 2, 1, -2),
    ]
    cur.executemany(
        "INSERT INTO decryptors (typeid, name, chance_multiplier, runs_modifier, me_modifier, te_modifier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        decryptor_data,
    )

    # ==========================================
    # Цены
    # ==========================================

    cur.execute("""
        CREATE TABLE price_snapshots (
            typeid INTEGER NOT NULL,
            region_id INTEGER NOT NULL,
            max_buy_price REAL,
            min_sell_price REAL,
            buy_percentile REAL,
            sell_percentile REAL,
            buy_volume INTEGER,
            sell_volume INTEGER,
            buy_order_count INTEGER,
            sell_order_count INTEGER,
            snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (typeid, region_id)
        )
    """)

    # ==========================================
    # Индексы
    # ==========================================

    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_group ON items(group_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_groups_category ON item_groups(category_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_systems_region ON solar_systems(region_id)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_bp_activities ON blueprint_activities(activity)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bp_activities_has_me ON blueprint_activities(activity, has_me)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bp_materials_lookup ON blueprint_materials(blueprint_typeid, activity)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bp_products_lookup ON blueprint_products(activity, product_typeid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bp_products_bp ON blueprint_products(blueprint_typeid, activity)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_typeid ON price_snapshots(typeid, region_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bpc_sources_bpc ON bpc_sources(user_bpc_id)")

    # Индекс для овервью: активные/статусы по продуктам
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_active ON production_scenarios(is_active, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_bp ON production_scenarios(bp_typeid)")

    conn.commit()
    conn.close()
    print(f"✅ Схема БД полностью пересоздана: {DB_PATH}")
    print("💡 Теперь запустите:")
    print("   1. scripts/setup_staticdata.py")
    print("   2. scripts/setup_marketdata.py")


if __name__ == "__main__":
    init_schema()