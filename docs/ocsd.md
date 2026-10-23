# OCSD_Flow: Архитектура и бизнес-логика

## 1. Цель проекта

Калькулятор производства и торговли в EVE Online.
Текущий этап: десктопное GUI-приложение с полным SDE, ценами Fuzzwork, сценариями производства, расчётом прибыли и интерактивным деревом материалов.

## 2. Структура проекта

```text
OCSD_Flow_0/
├── main.py                      # Точка входа (PySide6)
├── assets/
│   └── fonts/                   # Roboto-Regular.ttf, Roboto-Medium.ttf
├── scripts/
│   ├── setup_sql.py             # Создание схемы БД
│   ├── setup_staticdata.py      # Загрузка SDE
│   ├── setup_marketdata.py      # Загрузка цен Fuzzwork
│   └── setup_icons.py           # Скачивание иконок EVE
├── tests/
│   ├── sde.py                   # Смоук-тест данных SDE
│   └── sql_overview.py          # Просмотр таблиц БД в консоли
├── docs/
│   └── ocsd.md                  # Этот файл
├── src/
│   ├── core/
│   │   ├── tree_builder.py      # Построение дерева, применение сценария
│   │   ├── bpc_management.py    # Сценарии, стратегии, диалоги
│   │   ├── invention.py         # Расчёт инвента
│   │   └── profit.py            # Себестоимость, выручка, маржа
│   ├── db/
│   │   ├── db_manager.py        # Низкоуровневые запросы
│   │   └── market.py            # Цены и регионы
│   ├── gui/
│   │   ├── main_window.py       # Главное окно, сайдбар, навигация
│   │   ├── theme.py             # Цветовая палитра (@переменные)
│   │   ├── style_loader.py      # Подстановка @переменных в QSS
│   │   ├── window_chrome.py     # Тёмная системная шапка
│   │   ├── styles/
│   │   │   └── main.qss         # Глобальные стили
│   │   ├── models/
│   │   │   └── tree_model.py    # Модель для QTreeView
│   │   ├── dialogs/
│   │   │   └── new_bpc.py       # Модальное окно создания BPC
│   │   └── pages/
│   │       ├── overview.py      # Овервью производства
│   │       └── scenario_editor.py # Редактор сценария
│   └── console_ui/              # Старый консольный интерфейс (архив)
└── data/
    ├── sql/Blueprints.sqlite    # База данных
    ├── static/                  # SDE JSONL
    └── icons/
        ├── types/               # Иконки предметов (32px)
        ├── bpo/                 # Иконки BPO
        └── bpc/                 # Иконки BPC
```

## 3. Модель данных

### 3.1. Справочники

- **`item_categories`** — категории (`category_id`, `name`). `Ship = 6`, `Blueprint = 9`.
- **`item_groups`** — группы (`group_id`, `category_id`, `name`).
- **`items`** — предметы (`typeid`, `name_en`, `name_ru`, `group_id`).
- **`regions`** — регионы (`region_id`, `name`).
- **`solar_systems`** — системы (`system_id`, `name`, `region_id`, `constellation_id`, `security_status`).

### 3.2. Чертежи (нормализованная модель)

- **`blueprints`** — `blueprint_typeid`, `max_production_limit`.
- **`blueprint_activities`** — время по активности (`blueprint_typeid`, `activity`, `time_seconds`, `has_me`).
  - `has_me = 1` для `manufacturing`, `0` для `copying`, `invention`, `reaction`.
- **`blueprint_materials`** — материалы по активности.
- **`blueprint_products`** — продукты по активности, с `probability` для `invention`.

**Ключевые связи:**
- T2 продукт → T2 чертёж: `blueprint_products WHERE activity='manufacturing' AND product_typeid = ?`.
- T2 чертёж → T1 чертёж (для инвента): `blueprint_products WHERE activity='invention' AND product_typeid = ?`.
- T1 чертёж → дейтакоры: `blueprint_materials WHERE activity='invention' AND blueprint_typeid = ?`.

### 3.3. Пользовательские BPC

- **`user_bpc`** — паспорт BPC (`bp_typeid`, `label`, `me_current`, `te_current`, `max_runs`, `is_t2`).
- **`bpc_sources`** — источник (`user_bpc_id`, `source_type` = `copy`/`market`/`invention`, `base_cost`).

### 3.4. Сценарии

- **`production_scenarios`** — `label`, `bp_typeid`, `me`, `te`, `total_product_qty`, `bpc_max_runs`, `user_bpc_id`, `job_cost_per_run`, `is_invention_scenario`, налоги.
  - **`is_active INTEGER DEFAULT 0`** — активный сценарий для продукта.
  - **`status TEXT DEFAULT 'planned'`** — `planned` | `in_progress` | `done` | `cancelled`.
- **`scenario_components`** — стратегия (`scenario_id`, `typeid`, `produce_self`).
- **`scenario_invention`** — параметры инвента.
- **`decryptors`** — 8 декрипторов с модификаторами.

### 3.5. Цены

- **`price_snapshots`** — одна строка на `typeid` + `region_id`:
  - `max_buy_price`, `min_sell_price`, `buy_percentile`, `sell_percentile`
  - `buy_volume`, `sell_volume`, `buy_order_count`, `sell_order_count`

## 4. Ключевые формулы и правила

### 4.1. ME (Material Efficiency)

ME применяется к **заданию целиком** (все раны одной копии BPC):

```text
jobs_needed = ceil(total_product_qty / bpc_max_runs)
actual_runs = jobs_needed * bpc_max_runs
per_job     = ceil(base_qty * (1 - ME/100) * bpc_max_runs)   # has_me=1
per_job     = ceil(base_qty * bpc_max_runs)                  # has_me=0
total_qty   = per_job * jobs_needed
```

### 4.2. Полный BPC

Если хочешь 7 предметов, а BPC на 10 ранов — запускается 1 полный BPC (10 ранов). Лишние — на продажу.

### 4.3. Стратегия компонентов

`strategy_map: {typeid: bool}` — глобальна по `typeid`.
В GUI реализовано через раскрытие/сворачивание дерева:
- **Ветка раскрыта** → `produce_self = True` (производим).
- **Ветка свернута** → `produce_self = False` (покупаем).

Локальная стратегия (`local_strategy`) работает до сохранения сценария, затем переносится в БД.

### 4.4. Выбор цен

Режимы (`price_mode`):
- **`default`** (по умолчанию) — консервативный: закупки по `BUY max`, продажа по `SELL min`.
- **`best`** — оптимистичный: закупки по `SELL min`, продажа по `BUY max`.
- **`realistic`** — с учётом глубины: `SELL %ile` для закупок, `BUY %ile` для продажи.

### 4.5. Себестоимость

```text
cost_total = cost_materials + cost_bpc + cost_jobs
```

- `cost_materials` — сумма по покупным узлам (produce=False или нет BPC).
- `cost_bpc` — для `market`/`copy`: `base_cost * jobs_needed`; для инвента: `expected_cost * jobs_needed`.
- `cost_jobs` — `job_cost_per_run * total_product_qty`.

### 4.6. Инвент

```text
chance = base_chance (из SDE или вручную) * decryptor_chance_multiplier
cost_per_attempt = t1_bpc_cost_per_run + datacore_a_cost + datacore_b_cost + decryptor_cost
expected_cost_per_bpc = cost_per_attempt / chance
```

Характеристики T2 BPC: `runs = base_runs + decryptor_runs_mod`, `ME = 2 + decryptor_me_mod`, `TE = 4 + decryptor_te_mod`.

### 4.7. Выручка и прибыль

```text
revenue_gross = total_product_qty * unit_price
revenue_net   = revenue_gross * (1 - sales_tax - broker_fee)
profit        = revenue_net - cost_total
margin        = profit / revenue_net * 100
```

## 5. GUI: ключевые особенности

### 5.1. Главное окно

- Тёмная тема (`QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)` + `Fusion`).
- Сайдбар слева (Industry / Trade), верхняя чёрная шапка.
- `QStackedWidget` для переключения страниц.
- Тёмная системная шапка Windows через `DwmSetWindowAttribute`.

### 5.2. Овервью

- Группировка сценариев по продукту.
- Карточки продуктов с списком сценариев.
- Кликабельные названия сценариев (цвет `AccentColorBlueLight`), переход в редактор.

### 5.3. Редактор сценария

- Поиск продукта через `QCompleter` (из БД).
- Выбор BPC из сохранённых или создание нового (модальное окно).
- Живой пересчёт экономики (`QTimer` с задержкой 300 мс).
- Интерактивное дерево (`QTreeView`): сворачивание/разворачивание = стратегия.
- Save / Delete с обновлением Овервью.

### 5.4. Система стилей

- Цвета в `theme.py` (словарь `PALETTE`).
- `style_loader.py` подставляет `@переменные` в QSS (сортировка по длине ключа).
- Локальные стили виджетов используют `PALETTE[...]` напрямую через f-строки.

## 6. Внешние источники

- **SDE JSONL:** `types.jsonl`, `blueprints.jsonl`, `mapRegions.jsonl`, `mapSolarSystems.jsonl`, `groups.jsonl`, `categories.jsonl`.
- **Fuzzwork Market Data:** `https://market.fuzzwork.co.uk/aggregatecsv.csv.gz`. Колонка `what` = `region_id|typeid|is_buy`. Регион по умолчанию: Jita (10000002).
- **EVE Image Server:** `https://images.evetech.net/types/{typeid}/{variation}?size=32`.
  - `icon` — для предметов, `bp` — для BPO, `bpc` — для BPC.

## 7. Порядок запуска

```text
1. python scripts/setup_sql.py
2. python scripts/setup_staticdata.py
3. python scripts/setup_marketdata.py
4. python scripts/setup_icons.py    # опционально
5. python tests/sde.py              # проверка данных
6. python main.py                   # запуск GUI
```

## 8. Известные ограничения

- Время производства считается только по корневому чертежу.
- Стратегия глобальна по `typeid` (не по пути в дереве).
- Реакции загружены в SDE, но в `tree_builder` пока не используются.
- Нет `node-level BPC` — один BPC на сценарий.
- Регион захардкожен (Jita).
- Инвент в GUI пока не реализован (только в консоли).
- Овервью не показывает экономику (прибыль/маржу) в карточках.
- Пока сценарий не сохранён, стратегия живёт в `local_strategy` (в памяти).

## 9. Планы

1. **Инвент в GUI** — выбор инвента при создании сценария, ввод T1 BPC, дейтакоров, шанса.
2. **Прибыль в Овервью** — показывать маржу в карточках сценариев.
3. **Кнопка обновления цен** — запуск `setup_marketdata` из интерфейса.
4. **Доводка верстки** — полировка Овервью и Редактора.
5. **Время с учётом дочерних чертежей**.
6. **Выбор региона в UI**.
7. **Реакции в дереве** — строить поддерево реакций.
8. **Buy vs Build** — отложено (несущественно).