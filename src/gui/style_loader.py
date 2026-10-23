from pathlib import Path
from src.gui.theme import PALETTE


def load_stylesheet(qss_filename: str) -> str:
    """Загружает QSS-файл и подставляет переменные из PALETTE."""
    qss_path = Path(__file__).resolve().parent / "styles" / qss_filename
    if not qss_path.exists():
        print(f"⚠️ QSS-файл не найден: {qss_path}")
        return ""

    with qss_path.open("r", encoding="utf-8") as f:
        qss = f.read()

    # Сортируем по убыванию длины, чтобы избежать конфликтов (напр. Red и Red_dark)
    for name in sorted(PALETTE.keys(), key=len, reverse=True):
        qss = qss.replace(f"@{name}", PALETTE[name])

    return qss