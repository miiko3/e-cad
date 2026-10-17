"""Material Design 3: цветовые токены, шрифты и таблица стилей (QSS)."""
from __future__ import annotations

import math
import os
from typing import Dict

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt



class Palette:
    """Токены Material Design 3 (тёмная и светлая схемы)."""

    DARK = {
        "primary": "#d0e4ff",
        "on_primary": "#00325a",
        "primary_container": "#00497f",
        "on_primary_container": "#d0e4ff",
        "secondary": "#bbc7db",
        "on_secondary": "#253141",
        "secondary_container": "#3b4858",
        "on_secondary_container": "#d7e3f7",
        "tertiary": "#d7bde4",
        "on_tertiary": "#3b2948",
        "tertiary_container": "#523f5f",
        "on_tertiary_container": "#f3d9ff",
        "error": "#ffb4ab",
        "on_error": "#690005",
        "error_container": "#93000a",
        "on_error_container": "#ffdad6",
        "background": "#101418",
        "on_background": "#e0e2e8",
        "surface": "#101418",
        "on_surface": "#e0e2e8",
        "surface_variant": "#42474e",
        "on_surface_variant": "#c2c7cf",
        "surface_container_lowest": "#0b0f13",
        "surface_container_low": "#181c20",
        "surface_container": "#1c2024",
        "surface_container_high": "#262a2f",
        "surface_container_highest": "#31353a",
        "outline": "#8c9199",
        "outline_variant": "#42474e",
        "inverse_surface": "#e0e2e8",
        "inverse_on_surface": "#2f3033",
        "inverse_primary": "#00629e",
        "scrim": "#000000",
        "shadow": "#000000",
        "success": "#7ddb9a",
        "warning": "#f5c96a",
        "grid": "#2a2f35",
        "grid_thick": "#3a4149",
        "canvas": "#0a0d10",
        "board": "#14181c",
        "silk": "#e6e9ee",
        "hole": "#0a0d10",
        "selection": "#ff8a00",
        "probe": "#7ddb9a",
    }

    LIGHT = {
        "primary": "#00639b",
        "on_primary": "#ffffff",
        "primary_container": "#cce5ff",
        "on_primary_container": "#001d33",
        "secondary": "#535f70",
        "on_secondary": "#ffffff",
        "secondary_container": "#d7e3f7",
        "on_secondary_container": "#101c2b",
        "tertiary": "#6b5778",
        "on_tertiary": "#ffffff",
        "tertiary_container": "#f3d9ff",
        "on_tertiary_container": "#251431",
        "error": "#ba1a1a",
        "on_error": "#ffffff",
        "error_container": "#ffdad6",
        "on_error_container": "#410002",
        "background": "#f8f9fb",
        "on_background": "#191c20",
        "surface": "#f8f9fb",
        "on_surface": "#191c20",
        "surface_variant": "#dee2ea",
        "on_surface_variant": "#42474e",
        "surface_container_lowest": "#ffffff",
        "surface_container_low": "#f2f3f6",
        "surface_container": "#eceef2",
        "surface_container_high": "#e6e8ed",
        "surface_container_highest": "#e0e2e7",
        "outline": "#72777f",
        "outline_variant": "#c2c7cf",
        "inverse_surface": "#2f3033",
        "inverse_on_surface": "#f0f1f4",
        "inverse_primary": "#99ccff",
        "scrim": "#000000",
        "shadow": "#000000",
        "success": "#2e6b41",
        "warning": "#7a5900",
        "grid": "#dfe3e8",
        "grid_thick": "#c8ced6",
        "canvas": "#eef0f3",
        "board": "#f7f8fa",
        "silk": "#20242a",
        "hole": "#eef0f3",
        "selection": "#b35200",
        "probe": "#1b7f3b",
    }


def tokens(dark: bool = True) -> Dict[str, str]:
    return dict(Palette.DARK if dark else Palette.LIGHT)



_UI_CANDIDATES = ["Segoe UI Variable Display", "Segoe UI", "Inter", "Roboto", "Arial"]
_MONO_CANDIDATES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"]


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    f = QFont()
    for name in _UI_CANDIDATES:
        f.setFamily(name)
        if QFontDatabase.families() and name in QFontDatabase.families():
            break
    f.setPointSize(size)
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


def mono_font(size: int = 9) -> QFont:
    f = QFont()
    for name in _MONO_CANDIDATES:
        f.setFamily(name)
        if QFontDatabase.families() and name in QFontDatabase.families():
            break
    f.setPointSize(size)
    return f



def stylesheet(t: Dict[str, str]) -> str:
    """Таблица стилей MD3 по токенам."""
    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 12px;
}}
QWidget {{
    background-color: {t['surface']};
    color: {t['on_surface']};
}}
QMainWindow, QDialog {{
    background-color: {t['surface']};
}}

/* --- верхняя панель приложения --- */
QFrame#TopBar {{
    background-color: {t['surface_container']};
    border: none;
}}
QLabel#AppTitle {{
    font-size: 17px;
    font-weight: 600;
    color: {t['on_surface']};
}}
QLabel#AppSubtitle {{
    color: {t['on_surface_variant']};
    font-size: 11px;
}}
QToolButton#LogoButton {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 2px;
}}
QToolButton#LogoButton:hover {{
    background-color: {t['surface_container_high']};
}}

/* --- меню --- */
QMenuBar {{
    background-color: {t['surface_container']};
    color: {t['on_surface']};
    padding: 2px 6px;
    border-bottom: 1px solid {t['outline_variant']};
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 11px;
    border-radius: 6px;
    margin: 1px 2px;
}}
QMenuBar::item:selected {{ background-color: {t['secondary_container']};
                            color: {t['on_secondary_container']}; }}
QMenu {{
    background-color: {t['surface_container_high']};
    color: {t['on_surface']};
    border: 1px solid {t['outline_variant']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 7px;
    margin: 1px 2px;
}}
QMenu::item:selected {{ background-color: {t['secondary_container']};
                         color: {t['on_secondary_container']}; }}
QMenu::item:disabled {{ color: {t['outline']}; }}
QMenu::separator {{
    height: 1px;
    background: {t['outline_variant']};
    margin: 5px 10px;
}}

/* --- панели --- */
QFrame#SidePanel, QFrame#LeftPanel {{
    background-color: {t['surface_container_low']};
    border: none;
}}
QFrame#LeftPanel {{ border-right: 1px solid {t['outline_variant']}; }}
QFrame#SidePanel {{ border-left: 1px solid {t['outline_variant']}; }}
QFrame#StatusBar {{
    background-color: {t['surface_container']};
    border-top: 1px solid {t['outline_variant']};
}}
QFrame#ToolRail {{
    background-color: {t['surface_container_low']};
    border: none;
}}
QTabWidget::pane {{
    border: 1px solid {t['outline_variant']};
    border-radius: 10px;
    background: {t['surface_container_low']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {t['on_surface_variant']};
    padding: 6px 10px;
    border-radius: 8px;
    margin: 2px;
    min-width: 54px;
}}
QTabBar::scroller::add-button, QTabBar::scroller::sub-button {{
    background: transparent; border: none; width: 14px;
}}
QTabBar::tab:selected {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
}}

/* --- инструменты --- */
QToolButton {{
    background-color: transparent;
    color: {t['on_surface_variant']};
    border: none;
    border-radius: 10px;
    padding: 6px 8px;
    min-width: 32px;
}}
QToolButton:hover {{ background-color: {t['surface_container_high']}; }}
QToolButton:checked {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
}}
QToolButton#ToolButton {{
    border-radius: 12px;
    padding: 6px 4px;
    min-width: 44px;
    min-height: 54px;
    font-size: 11px;
    qproperty-textElideMode: ElideRight;
}}
QToolButton#ToolButton:checked {{
    background-color: {t['primary_container']};
    color: {t['on_primary_container']};
}}
QToolButton#LayerButton {{
    border-radius: 9px;
    min-width: 30px;
    padding: 3px 8px;
}}
QToolButton#LayerButton:checked {{
    background-color: {t['primary_container']};
    color: {t['on_primary_container']};
}}
QPushButton#ToggleButton:checked {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
}}

/* --- кнопки --- */
QPushButton {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
    border: none;
    border-radius: 9px;
    padding: 8px 14px;
    font-weight: 600;
    min-height: 20px;
}}
QPushButton#Flat {{ padding: 4px 8px; }}
QPushButton#Small {{ padding: 4px 8px; font-size: 11px; }}
QPushButton:hover  {{ background-color: {t['tertiary_container']};
                      color: {t['on_tertiary_container']}; }}
QPushButton:pressed{{ background-color: {t['primary_container']};
                      color: {t['on_primary_container']}; }}
QPushButton:disabled {{ background-color: {t['surface_container_high']};
                        color: {t['outline']}; }}
QPushButton#Primary {{
    background-color: {t['primary']};
    color: {t['on_primary']};
}}
QPushButton#Primary:hover {{ background-color: {t['primary_container']};
                             color: {t['on_primary_container']}; }}
QPushButton#Tonal {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
}}
QPushButton#Outline {{
    background-color: transparent;
    color: {t['primary']};
    border: 1px solid {t['outline']};
}}
QPushButton#Outline:hover {{ background-color: {t['surface_container_high']}; }}
QPushButton#Flat {{
    background-color: transparent;
    color: {t['primary']};
    font-weight: 500;
}}
QPushButton#Flat:hover {{ background-color: {t['surface_container_high']}; }}
QPushButton#Danger {{
    background-color: {t['error_container']};
    color: {t['on_error_container']};
}}

/* --- поля ввода --- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit {{
    background-color: {t['surface_container_highest']};
    color: {t['on_surface']};
    border: 1px solid {t['outline_variant']};
    border-radius: 9px;
    padding: 6px 9px;
    selection-background-color: {t['primary']};
    selection-color: {t['on_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {t['primary']};
    padding: 5px 8px;
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {t['outline']};
    background-color: {t['surface_container_high']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView::item {{ padding: 5px 6px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background-color: {t['surface_container_high']};
    color: {t['on_surface']};
    selection-background-color: {t['secondary_container']};
    selection-color: {t['on_secondary_container']};
    border: 1px solid {t['outline_variant']};
    border-radius: 8px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 16px;
}}

/* --- списки и таблицы --- */
QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget, QTableView {{
    background-color: {t['surface_container']};
    border: 1px solid {t['outline_variant']};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item, QTableWidget::item {{
    padding: 5px 7px;
    border-radius: 6px;
    margin: 1px 3px;
}}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {t['secondary_container']};
    color: {t['on_secondary_container']};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {t['surface_container_high']};
}}
QHeaderView::section {{
    background-color: {t['surface_container_high']};
    color: {t['on_surface_variant']};
    padding: 5px 7px;
    border: none;
    font-weight: 600;
}}

/* --- флажки / переключатели --- */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px;
    border: 2px solid {t['outline']};
    background: {t['surface_container_highest']};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {t['primary']};
    border-color: {t['primary']};
}}

/* --- скроллбары --- */
QScrollBar:vertical {{
    background: transparent; width: 12px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t['outline_variant']};
    border-radius: 6px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['outline']}; }}
QScrollBar:horizontal {{
    background: transparent; height: 12px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t['outline_variant']};
    border-radius: 6px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --- прочее --- */
QGroupBox {{
    border: 1px solid {t['outline_variant']};
    border-radius: 10px;
    margin-top: 10px;
    padding: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 11px;
    padding: 0 5px;
    color: {t['on_surface_variant']};
}}
QSplitter::handle {{ background: {t['outline_variant']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QToolTip {{
    background-color: {t['inverse_surface']};
    color: {t['inverse_on_surface']};
    border: none;
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12px;
}}
QLabel {{ background: transparent; }}
QGroupBox {{ font-weight: 600; }}
QStatusBar {{ background: {t['surface_container']}; color: {t['on_surface_variant']}; }}
QProgressBar {{
    border: none; background: {t['surface_container_highest']};
    border-radius: 5px; height: 8px; text-align: center;
}}
QProgressBar::chunk {{ background: {t['primary']}; border-radius: 5px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['surface_container_highest']}; }}
QSlider::handle:horizontal {{
    background: {t['primary']}; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px;
}}
QSlider::sub-page:horizontal {{ background: {t['primary']}; border-radius: 2px; }}
"""



def _pixmap(size: int, color: str) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def icon(name: str, color: str = "#e0e2e8", size: int = 24) -> QIcon:
    """Векторные иконки в стиле Material Symbols (упрощённые)."""
    pm = _pixmap(size, color)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor(color)
    pen = QPen(color)
    pen.setWidthF(max(1.4, size / 16.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    u = size / 24.0

    def R(x, y, w, h):
        return QRectF(x * u, y * u, w * u, h * u)

    def L(*pts):
        path = [(pts[i] * u, pts[i + 1] * u) for i in range(0, len(pts), 2)]
        for i in range(len(path) - 1):
            p.drawLine(QPointF(*path[i]), QPointF(*path[i + 1]))

    def dot(x, y, r=1.7):
        p.setBrush(pen.color())
        p.drawEllipse(QPointF(x * u, y * u), r * u, r * u)
        p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "cursor":
        p.setBrush(pen.color())
        poly = QPolygon([QPoint(5, 3), QPoint(5, 19), QPoint(9, 15), QPoint(12, 21),
                         QPoint(14, 20), QPoint(11, 14), QPoint(16, 13)])
        p.drawPolygon(poly)
    elif name == "zoom":
        p.drawEllipse(R(4, 4, 11, 11))
        L(16, 16, 21, 21)
        L(7, 9.5, 12, 9.5)
        L(9.5, 7, 9.5, 12)
    elif name == "track":
        L(4, 20, 9, 15, 15, 15, 20, 10)
        dot(4, 20); dot(20, 10)
    elif name == "pad":
        p.drawEllipse(R(5, 5, 14, 14))
        p.drawEllipse(R(10, 10, 4, 4))
    elif name == "smd":
        p.setBrush(pen.color())
        p.drawRect(R(4, 8, 7, 8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(R(13, 8, 7, 8))
    elif name == "circle":
        p.drawEllipse(R(4, 4, 16, 16))
    elif name == "polygon":
        pp = QPolygon([QPoint(12, 3), QPoint(21, 9), QPoint(18, 20), QPoint(6, 20), QPoint(3, 9)])
        p.drawPolygon(pp)
    elif name == "text":
        L(5, 6, 19, 6)
        L(12, 6, 12, 19)
        L(8, 19, 16, 19)
    elif name == "rect":
        p.drawRect(R(4, 6, 16, 12))
    elif name == "shape":
        p.drawPolygon(QPolygon([QPoint(12, 3), QPoint(21, 12), QPoint(12, 21), QPoint(3, 12)]))
        p.drawPolygon(QPolygon([QPoint(12, 8), QPoint(17, 12), QPoint(12, 16), QPoint(7, 12)]))
    elif name == "mask":
        p.drawRect(R(3, 5, 18, 14))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(R(8, 9, 8, 6))
    elif name == "conn":
        L(4, 18, 10, 12)
        L(14, 8, 20, 4)
        dot(4, 18); dot(20, 4)
        L(12, 10, 12, 14)
    elif name == "route":
        L(4, 19, 9, 14, 15, 14, 20, 9)
        dot(4, 19); dot(20, 9)
        pen2 = QPen(QColor(color))
        pen2.setWidthF(1.0)
        p.setPen(pen2)
        L(9, 14, 15, 14)
    elif name == "probe":
        p.drawEllipse(R(3, 3, 12, 12))
        L(13, 13, 21, 21)
        dot(9, 9, 2.4)
    elif name == "measure":
        p.drawRect(R(3, 8, 18, 8))
        L(7, 8, 7, 12)
        L(12, 8, 12, 13)
        L(17, 8, 17, 12)
    elif name == "photo":
        p.drawRect(R(3, 6, 18, 13))
        p.drawEllipse(R(8, 9, 8, 7))
        dot(17, 9, 1.1)
    elif name == "lib":
        p.drawRect(R(4, 4, 16, 16))
        L(4, 9, 20, 9)
        L(12, 4, 12, 20)
    elif name == "props":
        L(4, 7, 14, 7); L(18, 7, 20, 7)
        p.drawEllipse(R(13, 4.5, 5, 5))
        L(4, 17, 9, 17); L(13, 17, 20, 17)
        p.drawEllipse(R(8, 14.5, 5, 5))
    elif name == "drc":
        p.drawEllipse(R(3, 3, 18, 18))
        L(8, 12, 11, 16, 16, 8)
    elif name == "bom":
        p.drawRect(R(4, 3, 16, 18))
        L(4, 8, 20, 8)
        L(4, 13, 20, 13)
        L(9, 3, 9, 21)
    elif name == "filter":
        p.drawPolygon(QPolygon([QPoint(3, 5), QPoint(21, 5), QPoint(14, 13),
                                QPoint(14, 20), QPoint(10, 17), QPoint(10, 13)]))
    elif name == "save":
        p.drawRect(R(4, 4, 16, 16))
        p.drawRect(R(8, 4, 8, 8))
        p.drawRect(R(8, 14, 16, 8))
    elif name == "open":
        p.drawLine(QPointF(3 * u, 19 * u), QPointF(3 * u, 6 * u))
        L(3, 6, 10, 6, 12, 9, 21, 9, 21, 19, 3, 19)
    elif name == "new":
        p.drawRect(R(4, 4, 16, 16))
        L(12, 8, 12, 16); L(8, 12, 16, 12)
    elif name == "print":
        p.drawRect(R(7, 3, 17, 8))
        p.drawRect(R(4, 11, 20, 8))
        p.drawRect(R(7, 16, 17, 5))
    elif name == "export":
        L(12, 3, 12, 15)
        L(7, 11, 12, 16, 17, 11)
        L(4, 20, 20, 20)
    elif name == "import":
        L(12, 16, 12, 4)
        L(7, 8, 12, 3, 17, 8)
        L(4, 20, 20, 20)
    elif name == "undo":
        p.drawArc(R(4, 5, 16, 16), 30 * 16, 280 * 16)
        L(4, 10, 4, 5, 9, 5)
    elif name == "redo":
        p.drawArc(R(4, 5, 16, 16), 130 * 16, 280 * 16)
        L(20, 10, 20, 5, 15, 5)
    elif name == "help":
        p.drawArc(R(4, 3, 16, 12), 200 * 16, 300 * 16)
        L(10, 11, 12, 15)
        dot(12, 19, 1.6)
    elif name == "info":
        p.drawEllipse(R(3, 3, 18, 18))
        dot(12, 8, 1.2)
        L(12, 11, 12, 17)
    elif name == "zoomfit":
        p.drawRect(R(4, 6, 16, 12))
        L(8, 12, 11, 9, 14, 12, 16, 10)
    elif name == "earth":
        p.drawEllipse(R(3, 3, 18, 18))
        p.drawEllipse(R(8, 3, 8, 18))
        L(3, 12, 21, 12)
        p.drawArc(R(4, 6, 16, 12), 0, 180 * 16)
    elif name == "grid":
        L(4, 4, 4, 20); L(12, 4, 12, 20); L(20, 4, 20, 20)
        L(4, 4, 20, 4); L(4, 12, 20, 12); L(4, 20, 20, 20)
    elif name == "gear":
        p.drawEllipse(R(9, 9, 6, 6))
        for a in range(8):
            ang = math.radians(a * 45)
            p.drawLine(QPointF(12 + 7 * math.cos(ang), 12 + 7 * math.sin(ang)),
                       QPointF(12 + 9.5 * math.cos(ang), 12 + 9.5 * math.sin(ang)))
    elif name == "wizard":
        L(5, 19, 12, 5, 19, 19, 5, 19)
        L(9, 15, 15, 15)
    else:
        p.drawEllipse(R(5, 5, 14, 14))
    p.end()
    return QIcon(pm)


def app_icon(logo_path: str = "", size: int = 32) -> QIcon:
    if logo_path and os.path.exists(logo_path):
        pm = QPixmap(logo_path)
        if not pm.isNull():
            return QIcon(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))
    return icon("props", "#7ab6ff", size)