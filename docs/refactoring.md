# OCSD: план рефакторинга

Документ фиксирует переход от текущей схемы (`production_scenarios`, `user_bpc`, `scenario_*`) к новой модели (`blueprint`, `production_plan`, `plan_strategy`, `plan_invention`, `app_settings`). Код не приводится — только последовательность шагов, что меняется и что тестировать.

## 0. Принципы

- Работаем только с нашими БД. SDE читается только на этапе импорта.
- Без трекинга. Только расчёт: «что получу, если произведу N, и сколько это стоит».
- Инвент — фиксированный слой для T2 (один на план, не сворачивается, не управляется стратегией).
- T2 определяется по наличию инвент-рецепта в `blueprint_products` (activity='invention').
- T1 BPC всегда в `blueprint`. Если используем T1 BPC — он есть в базе чертежей.
- Одна версия BPC/BPO/reaction на `(bp_typeid, kind)`.
- Учитываем `product_quantity` в `jobs_needed`.
- `facility_tax` / `scc_surcharge` вшиты в стоимость запуска.
- Стоимость запуска — свойство BPC (для T1/компонентов/reaction). Для T2 — в `plan_invention`.
- ME/max_runs дочерних узлов — из `blueprint` или дефолт (ME=0, max_runs=1).
- `quantity` BPC — для будущего расчёта параллельных линий, сейчас не влияет на себестоимость.
- Overview = агрегация пула (все планы с `is_active=1`).

## 1. Новая схема БД

```sql
-- Справочники (без изменений)
item_categories, item_groups, items, regions, solar_systems

-- SDE-чертежи (без изменений)
blueprints, blueprint_activities, blueprint_materials, blueprint_products, decryptors

-- Пользовательские чертежи (BPC/BPO/reaction)
blueprint (
    bp_typeid, kind, me, te, max_runs, source, base_cost,
    job_cost_per_run,
    quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (bp_typeid, kind)
)
-- kind: 'bpo' | 'bpc' | 'reaction'

-- Навыки инвента
invention_skills (
    t1_bp_typeid PRIMARY KEY,
    skill_bonus REAL NOT NULL DEFAULT 0.0
)

-- Настройки приложения (одна строка)
app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sales_tax_percent REAL NOT NULL DEFAULT 2.5,
    broker_fee_percent REAL NOT NULL DEFAULT 3.0
)

-- План
production_plan (
    id, label, product_typeid, total_product_qty,
    blueprint_bp_typeid, blueprint_kind,
    activity,
    is_active,
    created_at
)

-- Стратегия
plan_strategy (
    plan_id, typeid, produce_self,
    PRIMARY KEY (plan_id, typeid)
)

-- Параметры инвента (одна на план, только для T2)
plan_invention (
    plan_id PRIMARY KEY,
    t1_bp_typeid, t1_bpc_runs,
    t1_invention_job_cost_per_run,
    t2_manufacturing_job_cost_per_run,
    datacore_a_typeid, datacore_a_qty,
    datacore_b_typeid, datacore_b_qty,
    decryptor_typeid,
    t2_bp_typeid, t2_product_typeid
)

-- Цены (без изменений)
price_snapshots
```

Удаляются: `user_bpc`, `bpc_sources`, `production_scenarios`, `scenario_components`, `scenario_invention`. Поля `status`, `is_invention_scenario`, `base_chance`, `facility_tax_percent`, `scc_surcharge_percent` больше не используются.

## 2. Ключевые формулы (для реализации)

```text
# jobs_needed
product_quantity = blueprint_products.quantity
jobs_needed = ceil(total_product_qty / (bpc_max_runs * product_quantity))
actual_runs = jobs_needed * bpc_max_runs

# ME (поузлово)
per_job = ceil(base_qty * (1 - node.me/100) * node.max_runs)   # has_me=1
per_job = ceil(base_qty * node.max_runs)                        # has_me=0

# cost_jobs
cost_jobs = sum(node.job_cost_per_run * node.actual_runs)
# T1/компоненты/reaction: из blueprint.job_cost_per_run
# T2: из plan_invention.t2_manufacturing_job_cost_per_run

# Инвент — шанс (предварительная формула)
chance = (base_chance + skill_bonus) * decryptor_mult

# Инвент — expected_cost
amortization = (blueprint.base_cost / blueprint.max_runs) * t1_bpc_runs
cost_per_attempt = amortization + t1_invention_job_cost_per_run
                 + dc_a_cost + dc_b_cost + decryptor_cost
expected_cost = cost_per_attempt / chance

# Себестоимость и прибыль
cost_total = cost_materials + cost_bpc + cost_jobs
revenue_net = revenue_gross * (1 - sales_tax/100 - broker_fee/100)
profit = revenue_net - cost_total
margin = profit / revenue_net * 100
```

## 3. Порядок рефакторинга

Порядок выбран так, чтобы после каждого шага проект оставался запускаемым (или падал предсказуемо), а тесты можно было добавлять постепенно.

### Шаг 1. Схема БД и setup-скрипты

Файлы: `scripts/setup_sql.py`.

Что делаем:
- Переписать `init_schema()` под новую схему.
- Добавить `app_settings` с одной строкой (sales_tax=2.5, broker_fee=3.0).
- Добавить `invention_skills` (пустая, заполняется вручную).
- Добавить `blueprint` с `kind`, `job_cost_per_run`, `quantity`.
- Заменить `production_scenarios` на `production_plan`, `scenario_components` на `plan_strategy`, `scenario_invention` на `plan_invention`.
- Удалить `user_bpc`, `bpc_sources`, `tax_profile` (не создаём).
- Индексы: под `plan_strategy(typeid)`, `plan_invention(t2_bp_typeid)`, `production_plan(is_active)`, `blueprint(kind)`.
- `DROP TABLE IF EXISTS` для старых таблиц — на случай, если БД уже существует.

Что тестировать:
- `python scripts/setup_sql.py` создаёт БД без ошибок.
- `tests/sql_overview.py` показывает новые таблицы (или расширить его под них).
- `app_settings` содержит одну строку с ожидаемыми значениями.

### Шаг 2. Слой БД: `db_manager.py`

Файлы: `src/db/db_manager.py`.

Что делаем:
- Удалить функции `user_bpc`/`bpc_sources` (`create_user_bpc`, `list_user_bpcs`, `get_user_bpcs_for_bp`, `list_user_bpcs_for_bp_with_source`, `find_identical_bpc`, `get_user_bpc_by_label`).
- Добавить CRUD для `blueprint`: `get_blueprint(bp_typeid, kind)`, `list_blueprints(kind=None)`, `create_blueprint(...)`, `update_blueprint(...)`, `delete_blueprint(...)`.
- `delete_blueprint` проверяет ссылки: `production_plan.blueprint_bp_typeid` + `blueprint_kind`, `plan_invention.t1_bp_typeid`. Если ссылается — запрет с сообщением.
- Добавить `get_invention_skills(t1_bp_typeid)` / `set_invention_skills(...)`.
- Добавить `get_app_settings()` / `update_app_settings(...)`.
- Переписать `get_blueprint_map_for_products` — теперь должна учитывать и manufacturing, и reaction (для `tree_builder`).
- Добавить `get_reaction_products_for_materials(mat_ids)` — обратный поиск reaction formula по продукту (аналог `get_blueprint_map_for_products`, но с `activity='reaction'`).
- `get_products_for_activity` — оставить, но использовать для reaction тоже.

Что тестировать:
- `get_blueprint`/`create_blueprint`/`update_blueprint`/`delete_blueprint` на тестовых данных.
- `delete_blueprint` запрещает удаление, если BPC используется в плане.
- `get_app_settings` возвращает одну строку.

### Шаг 3. Ядро: `invention.py`

Файлы: `src/core/invention.py`.

Что делаем:
- Убрать `base_chance_override` (больше не нужен).
- Добавить `skill_bonus` (из `invention_skills` по `t1_bp_typeid`).
- `chance = (base_chance + skill_bonus) * decryptor_mult`. Формулу вынести в отдельную функцию `compute_invention_chance(...)`.
- `base_chance` — из `blueprint_products.probability` (наша БД), fallback 0.34 (вынести в константу `DEFAULT_BASE_CHANCE`).
- `amortization` — из `blueprint.base_cost / blueprint.max_runs * t1_bpc_runs`.
- `expected_cost = (amortization + t1_invention_job_cost_per_run + dc_a + dc_b + decryptor) / chance`.
- Убрать мёртвый импорт `is_ship`.
- `VirtualT2BPC` — оставить, но без `base_chance` (шанс считается снаружи).
- Заменить `inf` при `chance = 0` на `None` (или явную ошибку), чтобы `profit` не ломался.

Что тестировать:
- `compute_invention_chance` на известных данных (например, Gila, декриптор, skill_bonus=0.2).
- `calculate_invention_cost` возвращает `None`, если `chance = 0` (а не `inf`).
- `expected_cost` сходится с ручным расчётом на тестовом примере.

### Шаг 4. Ядро: `tree_builder.py`

Файлы: `src/core/tree_builder.py`.

Что делаем:
- `build_production_tree`:
    - для каждого материала проверять: есть manufacturing-чертёж ИЛИ reaction formula.
    - если reaction formula и `produce_self=True` — раскрывать как reaction-узел (`activity='reaction'`, `has_me=0`).
    - для каждого узла с `produce_self=True` и `has_own_bp=True` — брать `me`/`max_runs`/`job_cost_per_run` из `blueprint` (для manufacturing → `kind in ('bpo','bpc')`, для reaction → `kind='reaction'`). Если BPC нет — `me=0`, `max_runs=1`, `job_cost_per_run=0`.
    - узел несёт `me`, `max_runs`, `job_cost_per_run`, `product_quantity`, `activity`.
- `apply_scenario`:
    - `jobs_needed = ceil(total_product_qty / (node.max_runs * node.product_quantity))`.
    - `per_job = ceil(base * (1 - node.me/100) * node.max_runs)` для `has_me=1`; иначе `ceil(base * node.max_runs)`.
    - `qty = per_job * jobs_needed`.
    - `actual_runs = jobs_needed * node.max_runs`.
- `build_scenario_tree`: принимает `plan_invention` (или `None`). Для T2 строит инвент-слой **один раз** (корень), для дочерних T2-компонентов инвент не строит.
- `depth_limit` — вынести в константу, проверить на реальных данных (возможно, увеличить).

Что тестировать:
- Дерево для T1 продукта (без инвента) строится, ME применяется поузлово.
- Дерево для T2 продукта с инвентом: инвент-слой присутствует, дейтакоры/декриптор/T1 BPC — в дереве.
- Компонент с reaction formula раскрывается как reaction-узел, `has_me=0`.
- Компонент без BPC — `me=0`, `max_runs=1`, `job_cost_per_run=0`.
- `product_quantity > 1` (патроны) — `jobs_needed` считается корректно.

### Шаг 5. Ядро: `profit.py`

Файлы: `src/core/profit.py`.

Что делаем:
- `_collect_purchased_items` — без изменений (produce=False или нет BPC).
- `cost_jobs` — сумма по всем производимым узлам: `node.job_cost_per_run * node.actual_runs`. Для T2 — из `plan_invention.t2_manufacturing_job_cost_per_run`.
- `cost_bpc` — сумма по всем производимым узлам с `blueprint`: `base_cost * jobs_needed` (market/copy). Для инвента (корень T2) — `expected_cost * jobs_needed`.
- `sales_tax`/`broker_fee` — из `app_settings`, не из сценария.
- `price_mode` — оставить как есть (default/best/realistic).
- `ProfitReport` — добавить поля: `bpc_shortage` (если `actual_runs > blueprint.quantity * max_runs`), `is_invention`, `invention_chance`, `invention_cost`.
- Обработать `expected_cost = None` (если `chance = 0`) — не ломать `profit`, показывать «инвент невозможен».

Что тестировать:
- `calculate_profit` для T1 продукта (без инвента) — сходится с ручным расчётом.
- `calculate_profit` для T2 продукта (с инвентом) — `cost_bpc` = `expected_cost * jobs_needed`.
- `price_mode` default/best/realistic — цены выбираются корректно.
- `sales_tax`/`broker_fee` — из `app_settings`.
- `bpc_shortage` — предупреждение, если не хватает BPC.

### Шаг 6. Новый модуль: `aggregate.py`

Файлы: `src/core/aggregate.py` (новый).

Что делаем:
- `aggregate_active_plans(region_id) -> PoolReport`.
- Для каждого плана с `is_active=1` — `build_scenario_tree` + `calculate_profit`.
- Суммировать `profit`, `margin`, `cost_total`.
- Агрегировать `purchases: {typeid: {qty, total_cost, avg_price}}`.
- Агрегировать `inventions: {t2_bp_typeid: {attempts, expected_cost, datacores}}`.
- Агрегировать `jobs: {activity: {runs, cost}}`.
- `PoolReport` — dataclass.

Что тестировать:
- Два активных плана → `PoolReport` суммирует цифры.
- Одинаковый `typeid` в двух планах → агрегируется в одну строку с суммарным `qty`.
- План с `is_active=0` не попадает в пул.

### Шаг 7. GUI: менеджер BPC (`Blueprints`)

Файлы: `src/gui/pages/blueprints.py` (новый), `src/gui/main_window.py`.

Что делаем:
- Новый экран `BlueprintsPage`: список `blueprint` (фильтр по `kind`, поиск по имени), кнопки Create/Edit/Delete.
- Диалог создания/редактирования: `bp_typeid` (QCompleter), `kind`, `me`, `te`, `max_runs`, `source`, `base_cost`, `job_cost_per_run`, `quantity`.
- При редактировании `bp_typeid`/`kind` — заблокированы (ключ).
- Удаление — с проверкой ссылок (через `delete_blueprint`).
- В `main_window.py` заменить заглушку `btn_blueprints` на переход на `BlueprintsPage`.

Что тестировать:
- Создание BPC/BPO/reaction через диалог.
- Редактирование `me`/`max_runs`/`quantity`/`job_cost_per_run`.
- Удаление BPC, не используемого в планах — успешно; используемого — запрет.
- Поиск/фильтр по `kind`.

### Шаг 8. GUI: редактор плана (`scenario_editor.py`)

Файлы: `src/gui/pages/scenario_editor.py`.

Что делаем:
- Переименовать `ScenarioEditorPage` → `PlanEditorPage` (или оставить имя, но переписать логику).
- Добавить поле `total_product_qty` (отдельно от `runs`).
- При выборе продукта: определить T2 (по наличию инвент-рецепта).
- Если T2 — показать блок «Инвент»:
    - T1 BPC (combo из `blueprint` kind='bpc' + кнопка «Создать»);
    - `t1_invention_job_cost_per_run`;
    - `t2_manufacturing_job_cost_per_run`;
    - декриптор (combo из `decryptors` + «без»);
    - дейтакоры (справочно);
    - расчётный шанс и `expected_cost` (на лету).
- Если T1 — блок «Инвент» скрыт.
- `job_cost_per_run` — из `blueprint` для выбранного BPC (read-only) или из `plan_invention` для T2.
- `local_strategy` — по-прежнему `{typeid: bool}` (стратегия по пути отложена).
- Save: создание `production_plan` + `plan_strategy` + `plan_invention` (если T2). Обновление существующего плана — реализовать (сейчас Save работает только на создание).
- При смене продукта — сбрасывать `current_scenario_id` (сейчас не сбрасывается — баг).
- `_apply_strategy_visual_state` — обходить **все** `root_node.children`, а не только первый (сейчас баг).
- Убрать `except Exception: pass` в `_calculate_and_show_economy` — хотя бы логировать.

Что тестировать:
- Создание плана T1: продукт, `total_qty`, BPC, `job_cost_per_run` — расчёт корректен.
- Создание плана T2: инвент-блок появляется, `expected_cost` считается, план сохраняется.
- Обновление существующего плана: изменение `total_qty`/BPC/стратегии — сохраняется.
- Смена продукта сбрасывает `current_scenario_id`.
- Стратегия визуально применяется ко всем корневым узлам.
- Дерево: инвент-слой не сворачивается, T1 BPC сворачивается.

### Шаг 9. GUI: Overview (агрегация пула)

Файлы: `src/gui/pages/overview.py`.

Что делаем:
- Переписать под `PoolReport` из `aggregate.py`.
- Секция 1: суммарные цифры (прибыль, маржа, `cost_total`).
- Секция 2: агрегированные закупки (таблица: item, qty, total cost).
- Секция 3: агрегированные инвенты (T2 BPC, attempts, datacores).
- Секция 4: агрегированные запуски (activity, runs, cost).
- Секция 5: список активных планов (с `is_active`).
- Кнопка «Обновить» (пересчёт пула).
- Клик по плану — переход в редактор.

Что тестировать:
- Пул из двух активных планов: суммарные цифры сходятся.
- Одинаковый `typeid` в двух планах — агрегируется.
- Неактивные планы не попадают в пул.
- Клик по плану открывает редактор.

### Шаг 10. Тесты и данные

Файлы: `tests/sde.py`, `tests/sql_overview.py`, новые тесты.

Что делаем:
- Обновить `tests/sql_overview.py` под новые таблицы.
- `tests/sde.py` — оставить (SDE не меняется), но добавить проверку `app_settings` и `blueprint`.
- Добавить тесты на `tree_builder` (T1, T2, reaction, `product_quantity > 1`).
- Добавить тесты на `profit` (default/best/realistic, `app_settings`).
- Добавить тесты на `aggregate` (пул).
- Добавить тест на `invention` (`chance`, `expected_cost`, `chance=0` → `None`).

Что тестировать:
- Все тесты проходят на чистой БД.
- `python tests/sde.py` — без ошибок.
- `python tests/sql_overview.py` — показывает новые таблицы.

### Шаг 11. Документация

Файлы: `docs/ocsd.md`, `docs/refactoring.md`.

Что делаем:
- Обновить `docs/ocsd.md` под новую схему и формулы.
- Отметить отложенные пункты (время, ISK/hour, параллельные линии, стратегия по пути, `realistic` с объёмом, история цен).
- `docs/refactoring.md` — оставить как историю рефакторинга.

## 4. Что отложено (зафиксировано)

1. Время производства, TE, ISK/hour, параллельные линии. `blueprint.quantity` уже готов.
2. Предупреждения о конкуренции за параллельные линии (когда появится время).
3. Стратегия по пути (path-based).
4. `realistic` с учётом объёма стакана.
5. История цен (append-only + latest view).
6. Формула шанса инвента — предварительная, отредактируем при отладке.
7. `depth_limit = 6` — проверить на реальных данных, возможно увеличить.
8. Реакции в Overview (агрегация reaction-запусков) — после того, как реакции появятся в дереве.

## 5. Риски и заметки

- **Миграция не нужна** — данные можно потерять, схема создаётся с нуля.
- **`product_quantity > 1`** (патроны/заряды) — критично для корректности `jobs_needed`; покрыть тестами.
- **`chance = 0`** — вернуть `None`, не `inf`, чтобы не ломать `profit`.
- **`delete_blueprint`** — обязательно проверять ссылки, иначе планы «повиснут».
- **`total_product_qty` vs `runs`** — в GUI это разные поля; не путать.
- **`_apply_strategy_visual_state`** — обходить все корневые узлы.
- **`current_scenario_id`** — сбрасывать при смене продукта.
- **`except Exception: pass`** — убрать или логировать.

## 6. Критерии готовности

- `python scripts/setup_sql.py` создаёт новую схему.
- `python scripts/setup_staticdata.py` и `setup_marketdata.py` работают без изменений.
- `python main.py` запускает GUI.
- Overview показывает агрегацию пула.
- Менеджер BPC позволяет создавать/редактировать/удалять BPC/BPO/reaction.
- Редактор плана создаёт и обновляет планы T1 и T2.
- Дерево корректно строит инвент-слой для T2 и reaction-узлы.
- Тесты `tree_builder`, `profit`, `invention`, `aggregate` проходят.
- `docs/ocsd.md` обновлён.