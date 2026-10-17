"""e-cad — точка входа. Запуск: python main.py"""
from __future__ import annotations

import os
import sys



for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ecad.ui.about import asset_path
from ecad.ui.main_window import MainWindow
from ecad.ui.theme import app_icon


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("e-cad")
    app.setApplicationDisplayName("e-cad — САПР топологии печатных плат")
    app.setOrganizationName("miiko3")
    logo = asset_path("assets", "logo.png")
    app.setWindowIcon(app_icon(logo))
    if os.path.exists(logo):
        app.setWindowIcon(QIcon(logo))
    win = MainWindow()
    win.restore_session()
    win.show()
    args = sys.argv[1:]
    if args and os.path.exists(args[0]):
        win.open_file(args[0])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())