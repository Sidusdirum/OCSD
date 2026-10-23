from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from src.core.bpc_management import group_scenarios_by_product
from src.db.db_manager import get_item_name
from src.gui.theme import PALETTE


class OverviewPage(QWidget):
    scenario_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.refresh_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        header = QLabel("📊 Овервью производства")
        header.setStyleSheet("font-size: 18pt; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; }")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.addStretch()

        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll, stretch=1)

    def refresh_data(self):
        """Загружает данные из БД и перерисовывает список."""
        # Очищаем старые виджеты
        while self.scroll_layout.count() > 1: # Оставляем stretch в конце
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        groups = group_scenarios_by_product()

        if not groups:
            lbl = QLabel("У вас пока нет сохранённых сценариев.")
            lbl.setStyleSheet("color: #888888; font-size: 12pt;")
            lbl.setAlignment(Qt.AlignCenter)
            self.scroll_layout.insertWidget(0, lbl)
            return

        for product_id, scenarios in groups.items():
            product_name = scenarios[0].get('product_name') or get_item_name(product_id)

            # Создаем карточку продукта
            card = QFrame()
            card.setObjectName("ProductCard")
            card.setStyleSheet("""
                #ProductCard {
                    background-color: #1e1e24;
                    border: 1px solid #2a2a35;
                    border-radius: 6px;
                }
            """)

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 15, 15, 15)
            card_layout.setSpacing(10)

            # Заголовок карточки (имя продукта)
            lbl_product = QLabel(f"📦 {product_name}")
            lbl_product.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff; background: transparent;")
            card_layout.addWidget(lbl_product)

            # Список сценариев внутри карточки
            for s in scenarios:
                scen_row = QFrame()
                scen_row.setStyleSheet("""
                    QFrame {
                        background-color: #121218;
                        border-radius: 4px;
                    }
                """)
                row_layout = QHBoxLayout(scen_row)
                row_layout.setContentsMargins(10, 8, 10, 8)

                # Инфо о сценарии
                status = s['status']
                is_active = "✅" if s['is_active'] else "  "
                type_str = "Инвент" if s['is_invention_scenario'] else "BPC"

                # Кликабельное название сценария
                lbl_name = QLabel(s['label'])
                color_normal = PALETTE["AccentColorBlueLight"]
                color_hover = PALETTE["AccentColorBlue"]

                lbl_name.setStyleSheet(f"""
                    QLabel {{
                        color: {color_normal}; 
                        font-weight: bold; 
                        font-size: 11pt; 
                        background: transparent;
                    }}
                    QLabel:hover {{
                        color: {color_hover};
                    }}
                """)
                lbl_name.setCursor(QCursor(Qt.PointingHandCursor))
                lbl_name.mousePressEvent = lambda event, sid=s['id']: self.scenario_selected.emit(sid)

                # Остальная информация
                info_text = (
                    f"{is_active} | Status: {status} | ME: {s['me']}% | "
                    f"Qty: {s['total_product_qty']} | "
                    f"BPC Runs: {s['bpc_max_runs']} | "
                    f"Type: {type_str}"
                )
                lbl_info = QLabel(info_text)
                lbl_info.setStyleSheet("color: #888888; font-size: 10pt; background: transparent;")

                row_layout.addWidget(lbl_name)
                row_layout.addWidget(lbl_info, stretch=1)

                card_layout.addWidget(scen_row)

            # Вставляем карточку перед stretch
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)