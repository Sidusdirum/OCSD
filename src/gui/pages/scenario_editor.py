from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QFrame,
    QCompleter, QSizePolicy, QMessageBox, QTreeView
)
from PySide6.QtCore import Qt, QStringListModel, QTimer, QModelIndex, Signal
from PySide6.QtGui import QIntValidator, QDoubleValidator

from src.gui.dialogs.new_bpc import NewBPCDialog
from src.gui.models.tree_model import ProductionTreeModel
from src.db.db_manager import (
    find_manufacturable_products,
    list_user_bpcs_for_bp_with_source,
    get_connection,
    get_blueprint_row,
    get_item_name
)
from src.core.bpc_management import (
    create_scenario,
    get_scenario_by_id,
    get_strategy_map_for_scenario,
    set_component_strategy
)
from src.core.tree_builder import build_scenario_tree
from src.core.profit import calculate_profit

MARGIN = 24


class ScenarioEditorPage(QWidget):

    scenario_deleted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_scenario_id = None
        self.current_product_id = None
        self.current_bp_typeid = None
        self.current_user_bpc_id = None
        self._product_map = {}

        # Локальная стратегия (работает до сохранения)
        self.local_strategy = {}

        self._is_updating_tree = False

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(300)
        self.update_timer.timeout.connect(lambda: self._calculate_and_show_economy(update_tree=False))

        self._setup_ui()
        self._setup_completer()

        self.btn_save.clicked.connect(self._on_save_scenario)
        self.btn_delete.clicked.connect(self._on_delete_scenario)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(MARGIN, 20, MARGIN, 20)
        main_layout.setSpacing(20)

        # 1. Верхняя панель
        header_layout = QHBoxLayout()
        header_layout.setSpacing(15)
        self.lbl_scenario_name = QLabel("Scenario name:")
        self.lbl_scenario_name.setFixedWidth(100)
        self.input_scenario_name = QLineEdit("New scenario")
        self.btn_save = QPushButton("Save")
        self.btn_save.setProperty("class", "primary")
        self.btn_save.setFixedWidth(100)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setProperty("class", "danger")
        self.btn_delete.setFixedWidth(100)
        self.btn_delete.setEnabled(False)

        header_layout.addWidget(self.lbl_scenario_name)
        header_layout.addWidget(self.input_scenario_name, stretch=1)
        header_layout.addWidget(self.btn_save)
        header_layout.addWidget(self.btn_delete)
        main_layout.addLayout(header_layout)

        # 2. Форма
        form_layout = QGridLayout()
        form_layout.setSpacing(10)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(3, 1)

        form_layout.addWidget(QLabel("Produce:"), 0, 0)
        self.input_produce = QLineEdit()
        self.input_produce.setPlaceholderText("Например, Leshak")
        form_layout.addWidget(self.input_produce, 0, 1)

        form_layout.addWidget(QLabel("BPC:"), 1, 0)
        self.combo_bpc = QComboBox()
        form_layout.addWidget(self.combo_bpc, 1, 1)

        self.lbl_bpc_hint = QLabel("Select BPC or create new")
        self.lbl_bpc_hint.setStyleSheet("color: #888888; font-style: italic;")
        form_layout.addWidget(self.lbl_bpc_hint, 1, 2, 1, 2)

        form_layout.addWidget(QLabel("Runs:"), 2, 0)
        self.input_runs = QLineEdit("1")
        self.input_runs.setValidator(QIntValidator(1, 999999, self))
        form_layout.addWidget(self.input_runs, 2, 1)

        form_layout.addWidget(QLabel("ME:"), 2, 2)
        self.input_me = QLineEdit("0")
        self.input_me.setValidator(QIntValidator(0, 20, self))
        form_layout.addWidget(self.input_me, 2, 3)

        form_layout.addWidget(QLabel("TE:"), 2, 4)
        self.input_te = QLineEdit("0")
        self.input_te.setValidator(QIntValidator(0, 20, self))
        form_layout.addWidget(self.input_te, 2, 5)

        form_layout.addWidget(QLabel("Cost:"), 2, 6)
        self.input_cost = QLineEdit("0.00")
        self.input_cost.setValidator(QDoubleValidator(0.0, 1e15, 2, self))
        form_layout.addWidget(self.input_cost, 2, 7)

        main_layout.addLayout(form_layout)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #2a2a35;")
        main_layout.addWidget(line)

        # 3. Блок Экономики
        self.economy_widget = QFrame()
        self.economy_widget.setObjectName("EconomyWidget")
        self.economy_widget.setVisible(False)

        eco_layout = QVBoxLayout(self.economy_widget)
        eco_layout.setContentsMargins(20, 20, 20, 20)
        eco_layout.setSpacing(10)

        lbl_eco_title = QLabel("💰 Экономика производства")
        lbl_eco_title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff;")
        eco_layout.addWidget(lbl_eco_title)

        self.lbl_eco_stats = QLabel("")
        self.lbl_eco_stats.setStyleSheet("font-size: 11pt; color: #dcdcdc;")
        eco_layout.addWidget(self.lbl_eco_stats)

        main_layout.addWidget(self.economy_widget)

        # 4. Materials Tree
        self.tree_view = QTreeView()
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree_view.setSelectionMode(QTreeView.SingleSelection)
        self.tree_view.setVisible(False)

        headers = ["Item", "Quantity", "Buy price (ISK)", "Sell price (ISK)", "Produce price (ISK)"]
        self.tree_model = ProductionTreeModel(headers, self)
        self.tree_view.setModel(self.tree_model)

        self.tree_view.setColumnWidth(0, 350)
        self.tree_view.setColumnWidth(1, 100)
        self.tree_view.setColumnWidth(2, 120)
        self.tree_view.setColumnWidth(3, 120)
        self.tree_view.setColumnWidth(4, 120)

        main_layout.addWidget(self.tree_view, stretch=1)

        self.lbl_tree_placeholder = QLabel("Выберите продукт и BPC для отображения дерева")
        self.lbl_tree_placeholder.setStyleSheet("color: #888888; font-size: 12pt;")
        self.lbl_tree_placeholder.setAlignment(Qt.AlignCenter)
        self.lbl_tree_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.lbl_tree_placeholder, stretch=1)

        # 5. Сигналы
        self.combo_bpc.currentIndexChanged.connect(self._on_bpc_changed)
        self.input_runs.textChanged.connect(self._trigger_realtime_update)
        self.input_me.textChanged.connect(self._trigger_realtime_update)
        self.input_te.textChanged.connect(self._trigger_realtime_update)
        self.input_cost.textChanged.connect(self._trigger_realtime_update)

        self.tree_view.expanded.connect(self._on_tree_expanded)
        self.tree_view.collapsed.connect(self._on_tree_collapsed)

    def _trigger_realtime_update(self):
        if self.current_bp_typeid:
            self.update_timer.start()

    def _setup_completer(self):
        self.produce_completer_model = QStringListModel()
        self.produce_completer = QCompleter(self.produce_completer_model, self)
        self.produce_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.produce_completer.setFilterMode(Qt.MatchContains)
        self.produce_completer.activated.connect(self._on_product_selected)
        self.input_produce.setCompleter(self.produce_completer)
        self.input_produce.textEdited.connect(self._on_produce_text_edited)

    def _on_produce_text_edited(self, text: str):
        if len(text) < 2:
            return
        products = find_manufacturable_products(text, limit=15)
        names = [p['name_ru'] or p['name_en'] for p in products]
        self.produce_completer_model.setStringList(names)
        self._product_map = {(p['name_ru'] or p['name_en']): (p['typeid'], p['blueprint_typeid']) for p in products}

    def _on_product_selected(self, text: str):
        if text in self._product_map:
            self.current_product_id, self.current_bp_typeid = self._product_map[text]
            self.local_strategy = {} # Сбрасываем стратегию для нового продукта
            self._load_bpcs_for_product()

    def _load_bpcs_for_product(self):
        if not self.current_bp_typeid:
            return
        self.combo_bpc.blockSignals(True)
        self.combo_bpc.clear()
        self.combo_bpc.addItem("Select BPC...")

        bpcs = list_user_bpcs_for_bp_with_source(self.current_bp_typeid)
        for b in bpcs:
            source = b.get('source_type', 'copy')
            cost = b.get('base_cost', 0)
            label = f"{b['label']} ({b['max_runs']} runs, {source}, {cost:.0f} ISK)"
            self.combo_bpc.addItem(label, userData=b['id'])

        self.combo_bpc.addItem("-- Create new BPC --")
        self.combo_bpc.setCurrentIndex(0)
        self.combo_bpc.blockSignals(False)

        if bpcs:
            self.lbl_bpc_hint.setText(f"Found {len(bpcs)} BPC(s). Select one.")
        else:
            self.lbl_bpc_hint.setText("No BPCs found. Create new?")

    def _on_bpc_changed(self, index: int):
        if index < 0:
            return
        current_text = self.combo_bpc.currentText()

        if current_text == "Select BPC...":
            self.lbl_bpc_hint.setText("Select BPC or create new")
            self.current_user_bpc_id = None
            self.economy_widget.setVisible(False)
            self.tree_view.setVisible(False)
            self.lbl_tree_placeholder.setVisible(True)
            return

        if current_text == "-- Create new BPC --":
            if not self.current_bp_typeid:
                self.lbl_bpc_hint.setText("Сначала выберите продукт!")
                return
            product_name = self.input_produce.text().strip()
            dialog = NewBPCDialog(product_name, self.current_bp_typeid, self)

            if dialog.exec():
                created_id = dialog.result_bpc_id
                self._load_bpcs_for_product()
                for i in range(self.combo_bpc.count()):
                    if self.combo_bpc.itemData(i) == created_id:
                        self.combo_bpc.setCurrentIndex(i)
                        break
                self.lbl_bpc_hint.setText("BPC saved/selected")
            else:
                self.combo_bpc.blockSignals(True)
                self.combo_bpc.setCurrentIndex(0)
                self.combo_bpc.blockSignals(False)
                self.lbl_bpc_hint.setText("BPC creation cancelled")
        else:
            self.lbl_bpc_hint.setText("Existing BPC selected")
            self.current_user_bpc_id = self.combo_bpc.currentData()
            self._rebuild_visual_tree()
            self._calculate_and_show_economy(update_tree=False)

    def _on_tree_expanded(self, index):
        if self._is_updating_tree: return
        self._handle_tree_toggle(index, expanded=True)

    def _on_tree_collapsed(self, index):
        if self._is_updating_tree: return
        self._handle_tree_toggle(index, expanded=False)

    def _handle_tree_toggle(self, index, expanded: bool):
        """Обновляет локальную стратегию и пересчитывает."""
        node = index.internalPointer()
        if not node or "typeid" not in node.data:
            return

        typeid = node.data["typeid"]

        # Всегда обновляем локальную стратегию
        self.local_strategy[typeid] = expanded

        # Если сценарий сохранен, дублируем в БД
        if self.current_scenario_id:
            set_component_strategy(self.current_scenario_id, typeid, produce_self=expanded)

        # Пересчитываем ТОЛЬКО цифры (дерево не трогаем)
        self._calculate_and_show_economy(update_tree=False)

    def _rebuild_visual_tree(self):
        """Строит ПОЛНОЕ дерево для отрисовки."""
        if not self.current_bp_typeid:
            return

        try:
            total_qty = int(self.input_runs.text() or 1)
            runs = int(self.input_runs.text() or 1)
            me = int(self.input_me.text() or 0)

            bp_row = get_blueprint_row(self.current_bp_typeid)
            if not bp_row:
                return

            # Строим полное дерево
            tree = build_scenario_tree(
                self.current_bp_typeid,
                total_qty,
                me,
                runs,
                strategy_map={},
                depth_limit=6
            )

            self._is_updating_tree = True
            self.tree_model.set_tree_data(tree)

            # Применяем локальную стратегию для визуального сворачивания
            self._apply_strategy_visual_state(self.local_strategy)

            self._is_updating_tree = False

        except Exception:
            self._is_updating_tree = False

    def _apply_strategy_visual_state(self, strategy_map):
        """Раскрывает/сворачивает ветки согласно стратегии."""
        def traverse(node, parent_index):
            for i, child in enumerate(node.children):
                child_index = self.tree_model.index(i, 0, parent_index)
                typeid = child.data.get("typeid")

                if strategy_map.get(typeid) is False:
                    self.tree_view.setExpanded(child_index, False)
                else:
                    self.tree_view.setExpanded(child_index, True)
                    traverse(child, child_index)

        root_index = self.tree_model.index(0, 0, QModelIndex())
        self.tree_view.setExpanded(root_index, True)
        if self.tree_model.root_node.children:
            root_node = self.tree_model.root_node.children[0]
            traverse(root_node, root_index)

    def _on_save_scenario(self):
        if not self.current_product_id or not self.current_bp_typeid:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите продукт и BPC.")
            return

        label = self.input_scenario_name.text().strip()
        if not label:
            QMessageBox.warning(self, "Ошибка", "Введите имя сценария.")
            return

        try:
            runs = int(self.input_runs.text() or 1)
            me = int(self.input_me.text() or 0)
            te = int(self.input_te.text() or 0)
            cost = float(self.input_cost.text() or 0.0)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Проверьте числовые поля.")
            return

        bpc_id = self.combo_bpc.currentData()
        if not bpc_id:
            QMessageBox.warning(self, "Ошибка", "Выберите BPC из списка.")
            return

        try:
            if self.current_scenario_id is None:
                new_id = create_scenario(
                    bp_typeid=self.current_bp_typeid,
                    label=label,
                    total_product_qty=1,
                    bpc_max_runs=runs,
                    me=me,
                    te=te,
                    user_bpc_id=bpc_id,
                    job_cost_per_run=cost,
                    is_invention_scenario=False,
                )
                self.current_scenario_id = new_id
                self.btn_delete.setEnabled(True)
                self.input_scenario_name.setReadOnly(True)

                # Сохраняем локальную стратегию в БД
                for tid, produce in self.local_strategy.items():
                    set_component_strategy(self.current_scenario_id, tid, produce)

                QMessageBox.information(self, "Успех", f"Сценарий создан (ID: {new_id}).")

            self._rebuild_visual_tree()
            self._calculate_and_show_economy(update_tree=False)

        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")

    def _calculate_and_show_economy(self, update_tree=False):
        if not self.current_bp_typeid:
            return

        try:
            try:
                total_qty = int(self.input_runs.text() or 1)
                runs = int(self.input_runs.text() or 1)
                me = int(self.input_me.text() or 0)
                cost = float(self.input_cost.text() or 0.0)
            except ValueError:
                return

            bp_row = get_blueprint_row(self.current_bp_typeid)
            if not bp_row:
                return

            if update_tree:
                self._rebuild_visual_tree()

            # Если сценарий сохранен, берем total_qty из БД
            if self.current_scenario_id:
                scenario_data = get_scenario_by_id(self.current_scenario_id)
                if scenario_data:
                    total_qty = scenario_data['total_product_qty']

            # Строим дерево для расчета, используя ЛОКАЛЬНУЮ стратегию
            calc_tree = build_scenario_tree(
                self.current_bp_typeid,
                total_qty,
                me,
                runs,
                self.local_strategy, # <--- Используем локальную стратегию
                depth_limit=6
            )

            report = calculate_profit(
                tree=calc_tree,
                total_product_qty=total_qty,
                product_typeid=bp_row['product_typeid'],
                scenario_id=self.current_scenario_id,
                price_mode="default",
                job_cost_per_run=cost,
                user_bpc_id=self.combo_bpc.currentData(),
                bpc_max_runs=runs,
                is_invention_scenario=False
            )

            product_name = report.product_name
            profit = report.profit
            margin = report.margin_percent
            color = "#4caf50" if profit >= 0 else "#d94848"

            text = f"""
            <table width='100%' cellspacing='5'>
                <tr>
                    <td><b>Продукт:</b></td>
                    <td>{product_name} (x{total_qty})</td>
                    <td align='right'><b>Выручка:</b></td>
                    <td align='right' style='color: #dcdcdc;'>{report.revenue_net_default:,.0f} ISK</td>
                </tr>
                <tr>
                    <td><b>Количество:</b></td>
                    <td>Runs: {runs} / ME: {me}%</td>
                    <td align='right'><b>Материалы:</b></td>
                    <td align='right' style='color: #888888;'>{report.cost_materials:,.0f} ISK</td>
                </tr>
                <tr>
                    <td></td>
                    <td></td>
                    <td align='right'><b>Стоимость BPC:</b></td>
                    <td align='right' style='color: #888888;'>{report.cost_bpc:,.0f} ISK</td>
                </tr>
                <tr>
                    <td></td>
                    <td></td>
                    <td align='right'><b>Стоимость работ:</b></td>
                    <td align='right' style='color: #888888;'>{report.cost_jobs:,.0f} ISK</td>
                </tr>
                <tr>
                    <td></td>
                    <td></td>
                    <td align='right' style='font-size: 14pt;'><b>ПРИБЫЛЬ:</b></td>
                    <td align='right' style='font-size: 14pt; font-weight: bold; color: {color};'>
                        {profit:,.0f} ISK ({margin:.1f}%)
                    </td>
                </tr>
            </table>
            """
            self.lbl_eco_stats.setText(text)
            self.economy_widget.setVisible(True)
            self.tree_view.setVisible(True)
            self.lbl_tree_placeholder.setVisible(False)

        except Exception:
            self._is_updating_tree = False
            pass

    def load_scenario(self, scenario_id: int):
        """Загружает существующий сценарий в форму."""
        scenario = get_scenario_by_id(scenario_id)
        if not scenario:
            return

        self.current_scenario_id = scenario_id
        self.btn_delete.setEnabled(True)
        self.input_scenario_name.setReadOnly(True)
        self.input_scenario_name.setText(scenario['label'])

        # Загружаем стратегию из БД в локальную
        self.local_strategy = get_strategy_map_for_scenario(scenario_id)

        bp_row = get_blueprint_row(scenario['bp_typeid'])
        if bp_row:
            self.current_product_id = bp_row['product_typeid']
            self.current_bp_typeid = scenario['bp_typeid']
            self.input_produce.setText(get_item_name(self.current_product_id))

            self._load_bpcs_for_product()

            if scenario['user_bpc_id']:
                for i in range(self.combo_bpc.count()):
                    if self.combo_bpc.itemData(i) == scenario['user_bpc_id']:
                        self.combo_bpc.setCurrentIndex(i)
                        break

        self.input_runs.setText(str(scenario['bpc_max_runs']))
        self.input_me.setText(str(scenario['me']))
        self.input_te.setText(str(scenario['te']))
        self.input_cost.setText(f"{scenario['job_cost_per_run']:.2f}")

        self._rebuild_visual_tree()
        self._calculate_and_show_economy(update_tree=False)

    def _on_delete_scenario(self):
        if self.current_scenario_id is None:
            return

        reply = QMessageBox.question(
            self, "Удаление",
            f"Вы уверены, что хотите удалить сценарий #{self.current_scenario_id}?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            with get_connection() as conn:
                conn.execute("DELETE FROM production_scenarios WHERE id = ?", (self.current_scenario_id,))
                conn.commit()

            self.current_scenario_id = None
            self.local_strategy = {}
            self.input_scenario_name.setText("New scenario")
            self.input_scenario_name.setReadOnly(False)
            self.btn_delete.setEnabled(False)
            self.input_produce.clear()
            self.combo_bpc.clear()
            self.lbl_bpc_hint.setText("Select BPC or create new")
            self.input_runs.setText("1")
            self.input_me.setText("0")
            self.input_te.setText("0")
            self.input_cost.setText("0.00")
            self.economy_widget.setVisible(False)
            self.tree_view.setVisible(False)
            self.lbl_tree_placeholder.setVisible(True)
            QMessageBox.information(self, "Удалено", "Сценарий успешно удален.")
            self.scenario_deleted.emit()