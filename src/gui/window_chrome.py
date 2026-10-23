import sys
import ctypes
from PySide6.QtWidgets import QWidget

def enable_dark_title_bar(window: QWidget) -> None:
    """Включает тёмную системную шапку на Windows. На других ОС ничего не делает."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        # Атрибут для тёмной шапки. Значение 20 работает на Win10 2004+ и Win11.
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass  # Если не получилось (старая Windows) — просто останется светлая шапка