from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame
)
from PySide6.QtCore import Qt
from src.gui.pages.overview import OverviewPage
from src.gui.pages.scenario_editor import ScenarioEditorPage
from src.gui.window_chrome import enable_dark_title_bar

# Единый отступ для левого края логотипа и текста навигации
MARGIN_LEFT = 24
SIDEBAR_WIDTH = 240

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCSD Flow")
        self.resize(1200, 800)

        enable_dark_title_bar(self)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ==========================================
        # 1. ЕДИНАЯ ШАПКА (на всю ширину)
        # ==========================================
        top_nav = QFrame()
        top_nav.setObjectName("TopNav")
        top_nav.setFixedHeight(64)

        # Слой внутри шапки
        nav_layout = QHBoxLayout(top_nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        # Левая часть шапки (по ширине совпадает с сайдбаром)
        nav_left = QWidget()
        nav_left.setFixedWidth(SIDEBAR_WIDTH)
        nav_left_layout = QHBoxLayout(nav_left)
        nav_left_layout.setContentsMargins(MARGIN_LEFT, 0, 0, 0)

        logo = QLabel("OCSD Flow")
        logo.setObjectName("LogoText")
        logo.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        nav_left_layout.addWidget(logo)

        # Правая часть шапки (Контент)
        nav_right = QWidget()
        nav_right_layout = QHBoxLayout(nav_right)
        nav_right_layout.setContentsMargins(MARGIN_LEFT, 0, 0, 0)

        self.nav_label = QLabel("Industry | Scenarios | New")
        self.nav_label.setObjectName("NavText")
        self.nav_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        nav_right_layout.addWidget(self.nav_label)
        nav_right_layout.addStretch()

        nav_layout.addWidget(nav_left)
        nav_layout.addWidget(nav_right)

        root_layout.addWidget(top_nav)

        # ==========================================
        # 2. НИЖНЯЯ ЧАСТЬ (Сайдбар + Контент)
        # ==========================================
        body_widget = QWidget()
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # --- Сайдбар ---
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 0)
        sidebar_layout.setSpacing(0)

        self.btn_overview = QPushButton("Overview")
        self.btn_overview.setProperty("class", "SidebarBtn")
        self.btn_overview.setCheckable(True)

        self.btn_scenarios = QPushButton("Scenarios")
        self.btn_scenarios.setProperty("class", "SidebarBtn")
        self.btn_scenarios.setCheckable(True)

        self.btn_blueprints = QPushButton("Blueprints")
        self.btn_blueprints.setProperty("class", "SidebarBtn")
        self.btn_blueprints.setCheckable(True)

        lbl_industry = QLabel("Industry")
        lbl_industry.setProperty("class", "SidebarGroup")

        sidebar_layout.addWidget(lbl_industry)
        sidebar_layout.addWidget(self.btn_overview)
        sidebar_layout.addWidget(self.btn_scenarios)
        sidebar_layout.addWidget(self.btn_blueprints)

        lbl_trade = QLabel("Trade")
        lbl_trade.setProperty("class", "SidebarGroup")
        sidebar_layout.addWidget(lbl_trade)

        sidebar_layout.addStretch()
        body_layout.addWidget(sidebar)

        # --- Контент ---
        self.stack = QStackedWidget()
        self.stack.setObjectName("ContentArea")

        self.page_overview = OverviewPage()
        self.page_editor = ScenarioEditorPage()

        # Связываем Овервью с Редактором
        self.page_overview.scenario_selected.connect(self._open_scenario_editor)
        self.page_editor.scenario_deleted.connect(self._on_scenario_deleted)

        self.stack.addWidget(self.page_overview)
        self.stack.addWidget(self.page_editor)

        body_layout.addWidget(self.stack)
        root_layout.addWidget(body_widget)

        # Связи
        self.btn_overview.clicked.connect(lambda: self._switch_page(0, "Industry | Overview"))
        self.btn_scenarios.clicked.connect(lambda: self._switch_page(1, "Industry | Scenarios | New"))

        self._switch_page(1, "Industry | Scenarios | New")
        self.btn_scenarios.setChecked(True)

    def _switch_page(self, index: int, nav_text: str):
        self.stack.setCurrentIndex(index)
        self.nav_label.setText(nav_text)

        for btn in (self.btn_overview, self.btn_scenarios, self.btn_blueprints):
            btn.setChecked(False)

        if index == 0:
            self.btn_overview.setChecked(True)
        elif index == 1:
            self.btn_scenarios.setChecked(True)

        if index == 0:
            self.btn_overview.setChecked(True)
            self.page_overview.refresh_data() # <-- Обновляем при переходе

    def _open_scenario_editor(self, scenario_id: int):
        """Переключается на редактор и загружает выбранный сценарий."""
        self._switch_page(1, "Industry | Scenarios | Edit") # Переключаем вкладку
        self.btn_scenarios.setChecked(True)
        self.page_editor.load_scenario(scenario_id) # Загружаем данные

    def _on_scenario_deleted(self):
        """Вызывается, когда сценарий удален. Возвращаемся в Овервью."""
        self._switch_page(0, "Industry | Overview")
        self.btn_overview.setChecked(True)
        # Овервью само обновится при переключении (мы это добавили ранее)