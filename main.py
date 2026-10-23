import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont, QGuiApplication
from PySide6.QtCore import Qt

from src.gui.main_window import MainWindow
from src.gui.style_loader import load_stylesheet


def load_roboto_font():
    base_dir = Path(__file__).resolve().parent
    font_dir = base_dir / "assets" / "fonts"
    font_files = ["Roboto-Regular.ttf", "Roboto-Medium.ttf"]
    loaded_ids = []

    for font_file in font_files:
        font_path = font_dir / font_file
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                loaded_ids.append(font_id)

    if loaded_ids:
        families = QFontDatabase.applicationFontFamilies(loaded_ids[0])
        if families:
            app_font = QFont(families[0], 10)
            QApplication.instance().setFont(app_font)


def main():
    app = QApplication(sys.argv)

    # === ВАРИАНТ 1: Официальный API Qt (тёмная схема) ===
    # Работает на Qt 6.8+ (у тебя 6.12). Устанавливает тёмную схему для приложения.
    # Это должно заставить Qt попросить Windows перерисовать шапку в тёмном режиме.
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)

    # На Windows стандартный стиль "windowsvista" может игнорировать тёмную схему.
    # Переключаем на "Fusion", который корректно работает с палитрами и тёмными темами.
    app.setStyle("Fusion")

    load_roboto_font()

    # Загружаем стили
    qss = load_stylesheet("main.qss")
    app.setStyleSheet(qss)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()