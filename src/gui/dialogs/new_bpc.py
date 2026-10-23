from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator

from src.db.db_manager import create_user_bpc


class NewBPCDialog(QDialog):
    def __init__(self, product_name: str, bp_typeid: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New BPC")
        self.setModal(True)
        self.setFixedSize(500, 260)
        self.setObjectName("NewBPCDialog")

        self.product_name = product_name
        self.bp_typeid = bp_typeid
        self.result_bpc_id = None  # ID созданного BPC

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        form_layout = QGridLayout()
        form_layout.setSpacing(10)

        form_layout.setColumnStretch(0, 0)
        for i in range(1, 6):
            form_layout.setColumnStretch(i, 1)

        # Product (read-only)
        lbl_product = QLabel("Product:")
        lbl_product.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.addWidget(lbl_product, 0, 0)

        self.input_product = QLineEdit(self.product_name)
        self.input_product.setReadOnly(True)
        self.input_product.setStyleSheet("color: #888888;")
        form_layout.addWidget(self.input_product, 0, 1, 1, 5)

        # Runs, ME, TE
        lbl_runs = QLabel("Runs:")
        lbl_runs.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.addWidget(lbl_runs, 1, 0)

        self.input_runs = QLineEdit("1")
        self.input_runs.setValidator(QIntValidator(1, 999999, self))
        form_layout.addWidget(self.input_runs, 1, 1)

        lbl_me = QLabel("ME:")
        lbl_me.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.addWidget(lbl_me, 1, 2)

        self.input_me = QLineEdit("0")
        self.input_me.setValidator(QIntValidator(0, 20, self))
        form_layout.addWidget(self.input_me, 1, 3)

        lbl_te = QLabel("TE:")
        lbl_te.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.addWidget(lbl_te, 1, 4)

        self.input_te = QLineEdit("0")
        self.input_te.setValidator(QIntValidator(0, 20, self))
        form_layout.addWidget(self.input_te, 1, 5)

        # Cost
        lbl_cost = QLabel("BPC cost:")
        lbl_cost.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form_layout.addWidget(lbl_cost, 2, 0)

        self.input_cost = QLineEdit("0.00")
        self.input_cost.setValidator(QDoubleValidator(0.0, 1e15, 2, self))
        form_layout.addWidget(self.input_cost, 2, 1)

        lbl_hint = QLabel("Calculate copy from BPO")
        lbl_hint.setStyleSheet("color: #2d6cdf; font-style: italic;")
        form_layout.addWidget(lbl_hint, 2, 2, 1, 4)

        layout.addLayout(form_layout)
        layout.addStretch()

        # Кнопка Save
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_save = QPushButton("Save")
        self.btn_save.setProperty("class", "primary")
        self.btn_save.setFixedWidth(120)
        self.btn_save.clicked.connect(self._on_save)

        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _on_save(self):
        runs = int(self.input_runs.text() or 0)
        me = int(self.input_me.text() or 0)
        te = int(self.input_te.text() or 0)
        cost = float(self.input_cost.text() or 0.0)

        if runs <= 0:
            QMessageBox.warning(self, "Ошибка", "Runs должен быть больше 0.")
            return

        bpc_label = f"{self.product_name} (Runs: {runs}, ME: {me}%)"

        # create_user_bpc сам проверит на дубликат
        new_id = create_user_bpc(
            bp_typeid=self.bp_typeid,
            label=bpc_label,
            me=me,
            te=te,
            max_runs=runs,
            is_t2=False,
            source_type="market" if cost > 0 else "copy",
            base_cost=cost,
        )

        if new_id:
            self.result_bpc_id = new_id
            self.accept()
        else:
            QMessageBox.warning(
                self, "Ошибка",
                "Не удалось создать BPC (возможно, конфликт имён)."
            )