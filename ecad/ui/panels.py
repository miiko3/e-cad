"""Панели интерфейса: инструменты, настройки слоёв, свойства, DRC, селектор, BOM."""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QIcon, QPainter, QPen,
                             QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter,
                               QTabWidget, QToolBar, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import drc as drc_mod
from ..core.model import (ALL_LAYERS, BOTTOM_KEY, COPPER_KEYS, LAYER_BY_KEY,
                          SILK_KEYS, TOP_KEY, CircleEl, Connection, Element,
                          FillEl, Pad, PolygonEl, RectEl, SmdPad, TextEl, Track)
from .canvas import TOOLS, Canvas, fmt_len
from .theme import icon


def _lbl(text: str, bold: bool = False, small: bool = False,
         wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if bold:
        f = l.font()
        f.setBold(True)
        l.setFont(f)
    if small:
        l.setStyleSheet("color: palette(mid);")
    if wrap:
        l.setWordWrap(True)
        l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    else:
        
        l.setMinimumWidth(0)
        l.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    return l


def _row(*widgets, spacing: int = 6) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for it in widgets:
        if isinstance(it, int):
            h.addSpacing(it)
        elif isinstance(it, str):
            h.addWidget(_lbl(it))
        else:
            h.addWidget(it)
    return w


class ToolPanel(QFrame):
    """Левая панель: инструменты, сетка, мини-карта, кнопки панелей.

    Панель можно свернуть (кнопка «≡») в узкую полосу с иконками.
    """

    toolPicked = Signal(str)
    panelToggled = Signal(str)
    gridChanged = Signal()
    zoomRequested = Signal(str)
    collapsedChanged = Signal(bool)

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("LeftPanel")
        self.collapsed = False
        self.expanded_width = 268
        self.setMinimumWidth(72)
        self.setMaximumWidth(460)
        self.resize(self.expanded_width, 800)
        self.buttons: Dict[str, QToolButton] = {}
        self.tool_names: Dict[str, str] = {}
        self.panel_buttons: Dict[str, QToolButton] = {}
        self._build()
        self.apply_state()

    
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 8, 6, 8)
        outer.setSpacing(6)

        
        head = QHBoxLayout()
        head.setSpacing(4)
        self.lbl_tools = _lbl("Инструменты", True)
        self.lbl_tools.setStyleSheet("font-size: 12px;")
        self.btn_collapse = QToolButton()
        self.btn_collapse.setText("«")
        self.btn_collapse.setToolTip("Свернуть панель инструментов")
        self.btn_collapse.setFixedSize(34, 30)
        f = self.btn_collapse.font()
        f.setPointSize(13)
        f.setBold(True)
        self.btn_collapse.setFont(f)
        self.btn_collapse.clicked.connect(self.toggle_collapsed)
        head.addWidget(self.lbl_tools, 1)
        head.addWidget(self.btn_collapse)
        outer.addLayout(head)

        
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        for i, (key, name, hotkey, ic) in enumerate(TOOLS):
            b = QToolButton()
            b.setObjectName("ToolButton_" + key)
            b.setIcon(icon(ic, "#c8d4e4", 24))
            b.setText(name)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setToolTip(f"{i + 1}. {name}\nКлавиша: {hotkey}")
            b.setCheckable(True)
            b.setMinimumHeight(54)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _c, k=key: self.toolPicked.emit(k))
            self.buttons[key] = b
            self.tool_names[key] = name
            r, c = divmod(i, 2)
            grid.addWidget(b, r, c)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.tool_grid = grid
        outer.addLayout(grid)

        
        gb = QGroupBox("Шаг сетки")
        gv = QVBoxLayout(gb)
        gv.setSpacing(4)
        self.grid_box = QComboBox()
        self.grid_box.setEditable(True)
        self.grid_box.setToolTip("Шаг сетки в мм (можно ввести вручную)")
        self.grid_box.currentTextChanged.connect(self._grid_text)
        self.grid_box.editTextChanged.connect(self._grid_text)
        gv.addWidget(self.grid_box)
        steps = QGridLayout()
        steps.setSpacing(2)
        self.step_buttons: List[QToolButton] = []
        for i in range(9):
            b = QToolButton()
            b.setObjectName("LayerButton")
            b.setText(str(i + 1))
            b.setCheckable(True)
            b.setMinimumWidth(26)
            b.setToolTip("Переключить шаг сетки (клавиши 1…9)")
            b.clicked.connect(lambda _c, n=i: self.set_grid_step(n))
            self.step_buttons.append(b)
            steps.addWidget(b, i // 5, i % 5)
        gv.addLayout(steps)
        self.lbl_thick = _lbl("Утолщение")
        self.grid_thick = QSpinBox()
        self.grid_thick.setRange(1, 50)
        self.grid_thick.setValue(5)
        self.grid_thick.setToolTip("Каждая N-я линия сетки рисуется толще")
        self.grid_thick.valueChanged.connect(self._grid_thick)
        thick_row = QHBoxLayout()
        thick_row.addWidget(self.lbl_thick)
        thick_row.addWidget(self.grid_thick, 1)
        gv.addLayout(thick_row)
        self.snap_btn = QToolButton()
        self.snap_btn.setObjectName("ToggleButton")
        self.snap_btn.setText("Привязка")
        self.snap_btn.setCheckable(True)
        self.snap_btn.setChecked(True)
        self.snap_btn.setToolTip("Привязка к сетке (Ctrl — временно снять)")
        self.snap_btn.clicked.connect(self._snap)
        gv.addWidget(self.snap_btn)
        self.grid_group = gb
        outer.addWidget(gb)

        
        self.minimap = MiniMap(self.canvas)
        self.minimap.setToolTip("Панорама платы: клик — перейти к участку")
        outer.addWidget(self.minimap, 1)

        
        self.lbl_panels = _lbl("Панели", True)
        self.lbl_panels.setStyleSheet("font-size: 12px;")
        outer.addWidget(self.lbl_panels)
        pb = QGridLayout()
        pb.setSpacing(4)
        panels = (("lib", "Библиотека", "lib"), ("props", "Свойства", "props"),
                  ("drc", "DRC", "drc"), ("bom", "Компоненты", "bom"),
                  ("filter", "Фильтр", "filter"), ("photo", "Фотовид", "photo"))
        for i, (key, text, ic) in enumerate(panels):
            b = QToolButton()
            b.setIcon(icon(ic, "#c8d4e4", 20))
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setMinimumHeight(48)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setToolTip(f"Панель «{text}» (вкл/выкл)")
            b.clicked.connect(lambda _c, k=key: self.panelToggled.emit(k))
            self.panel_buttons[key] = b
            pb.addWidget(b, i // 3, i % 3)
        for c in range(3):
            pb.setColumnStretch(c, 1)
        self.panels_grid = pb
        self.panels_host = QWidget()
        self.panels_host.setLayout(pb)
        self.panels_host.setStyleSheet("background: transparent;")
        outer.addWidget(self.panels_host)

        
        self.panels_compact = QWidget()
        pv = QVBoxLayout(self.panels_compact)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)
        for i, (key, _text, _ic) in enumerate(panels):
            b = self.panel_buttons[key]
            b.setParent(self.panels_compact)
            pv.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        pv.addStretch(1)
        self.panels_compact.setStyleSheet("background: transparent;")
        self.panels_compact.setVisible(False)
        outer.addWidget(self.panels_compact)

        z = QHBoxLayout()
        z.setSpacing(4)
        for ic, tip in (("zoomfit", "Вписать всю плату (Home)"),
                        ("photo", "Лупа всех объектов"),
                        ("measure", "Лупа выделенного")):
            b = QToolButton()
            b.setIcon(icon(ic, "#c8d4e4", 20))
            b.setToolTip(tip)
            b.setMinimumHeight(34)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _c, i=ic: self.zoomRequested.emit(i))
            z.addWidget(b)
        outer.addLayout(z)

    
    def toggle_collapsed(self):
        self.collapsed = not self.collapsed
        self.apply_state()
        self.collapsedChanged.emit(self.collapsed)

    def set_collapsed(self, value: bool):
        if self.collapsed != value:
            self.collapsed = value
            self.apply_state()
            self.collapsedChanged.emit(self.collapsed)

    def apply_state(self):
        c = self.collapsed
        self.setMaximumWidth(76 if c else 520)
        self.setMinimumWidth(72 if c else 210)
        self.lbl_tools.setVisible(not c)
        self.lbl_panels.setVisible(not c)
        self.lbl_thick.setVisible(not c)
        self.grid_group.setVisible(not c)
        self.btn_collapse.setText("«" if not c else "»")
        self.btn_collapse.setToolTip("Развернуть панель инструментов" if c
                                     else "Свернуть панель инструментов")
        for b in self.buttons.values():
            if c:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                b.setText("")
                b.setToolTip(b.toolTip().split("\n")[0])
            else:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                key = b.objectName().replace("ToolButton_", "")
                b.setText(self.tool_names.get(key, b.text()))
            if c:
                b.setFixedWidth(32)
            else:
                b.setMinimumWidth(104)
                b.setMaximumWidth(16777215)
        for key, b in self.panel_buttons.items():
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if c
                                else Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            if c:
                b.setFixedWidth(58)
            else:
                b.setMinimumWidth(88)
                b.setMaximumWidth(16777215)
        
        for i, key in enumerate(self.panel_buttons):
            b = self.panel_buttons[key]
            target = self.panels_compact if c else self.panels_host
            if b.parentWidget() is not target:
                old_layout = b.parentWidget().layout() if b.parentWidget() else None
                if old_layout is not None:
                    old_layout.removeWidget(b)
                b.setParent(target)
            if c:
                self.panels_compact.layout().addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            else:
                self.panels_host.layout().addWidget(b, i // 3, i % 3)
        self.panels_host.setVisible(not c)
        self.panels_compact.setVisible(c)
        self.btn_collapse.setFixedSize(34, 30)

    
    def set_tool(self, name: str):
        for k, b in self.buttons.items():
            b.setChecked(k == name)

    def sync_panel_buttons(self, active_index: int = -1):
        keys = list(self.panel_buttons)
        for i, k in enumerate(keys):
            self.panel_buttons[k].setChecked(i == active_index)

    def _grid_text(self, text: str):
        from ..core.geom import parse_len
        v = parse_len(text, self.canvas.settings["grid_step"])
        if v > 0:
            self.canvas.settings["grid_step"] = v
            self.gridChanged.emit()
            self.refresh()

    def _grid_thick(self, v: int):
        self.canvas.settings["grid_thick"] = v
        self.canvas.invalidate(structural=False)

    def _snap(self):
        self.canvas.settings["snap"] = self.snap_btn.isChecked()
        self.canvas.invalidate(structural=False)

    def set_grid_step(self, n: int):
        steps = self.canvas.settings["grid_steps"]
        if 0 <= n < len(steps):
            self.canvas.settings["grid_step"] = steps[n]
            self.gridChanged.emit()
            self.refresh()

    def refresh(self):
        s = self.canvas.settings
        val = f"{s['grid_step']:g}"
        if self.grid_box.currentText() != val:
            self.grid_box.blockSignals(True)
            self.grid_box.setCurrentText(val)
            self.grid_box.blockSignals(False)
        steps = s["grid_steps"]
        for i, b in enumerate(self.step_buttons):
            b.setChecked(abs(steps[i] - s["grid_step"]) < 1e-9)
            b.setToolTip(f"{steps[i]:g} мм (клавиша {i + 1})")
        self.snap_btn.setChecked(s["snap"])
        self.grid_thick.blockSignals(True)
        self.grid_thick.setValue(int(s["grid_thick"]))
        self.grid_thick.blockSignals(False)
        self.minimap.update()


def _tool_text(tip: str) -> str:
    """Имя инструмента из подсказки «N. Имя\nКлавиша: X»."""
    for line in tip.split("\n"):
        line = line.strip()
        if line[:2].rstrip(".").isdigit():
            return line.split(".", 1)[1].strip()
    return tip


class MiniMap(QWidget):
    """Мини-карта платы (панорама)."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setMinimumHeight(90)
        self.setMaximumHeight(160)

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter):
        b = self.canvas.board()
        t = self.canvas.tokens or {}
        p.fillRect(self.rect(), QColor(t.get("surface_container", "#1c2024")))
        box = b.outline_rect()
        w = box[2] - box[0]
        h = box[3] - box[1]
        if w <= 0 or h <= 0:
            return
        s = min(self.width() / w, self.height() / h) * 0.9
        ox = (self.width() - w * s) / 2
        oy = (self.height() - h * s) / 2

        def mp(pt):
            return (ox + (pt[0] - box[0]) * s, oy + (box[3] - pt[1]) * s)

        p.setPen(QPen(QColor(t.get("outline", "#8c9199")), 1))
        p.setBrush(QColor(t.get("board", "#14181c")))
        pts = [mp(pt) for pt in b.outline_points()]
        p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for el in b.elements.values():
            if el.kind in ("fill", "conn"):
                continue
            bb = el.bbox()
            if not bb:
                continue
            a, c = mp((bb[0], bb[3])), mp((bb[2], bb[1]))
            col = QColor(LAYER_BY_KEY.get(el.layer, LAYER_BY_KEY[TOP_KEY]).default_color)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRect(QRectF(min(a[0], c[0]), min(a[1], c[1]),
                              max(abs(c[0] - a[0]), 1), max(abs(c[1] - a[1]), 1)))
        
        f = self.canvas.field_rect()
        vx0 = self.canvas.offset.x()
        vy1 = self.canvas.offset.y() + f.height() / self.canvas.scale
        a = mp((vx0, vy1))
        c = mp((vx0 + f.width() / self.canvas.scale, self.canvas.offset.y()))
        p.setPen(QPen(QColor(t.get("primary", "#d0e4ff")), 1.4))
        p.setBrush(QColor(120, 170, 255, 40))
        p.drawRect(QRectF(a[0], a[1], max(4, abs(c[0] - a[0])), max(4, abs(c[1] - a[1]))))

    def mousePressEvent(self, ev):
        box = self.canvas.board().outline_rect()
        w = box[2] - box[0]
        h = box[3] - box[1]
        s = min(self.width() / w, self.height() / h) * 0.9
        ox = (self.width() - w * s) / 2
        oy = (self.height() - h * s) / 2
        x = box[0] + (ev.position().x() - ox) / s
        y = box[3] - (ev.position().y() - oy) / s
        f = self.canvas.field_rect()
        self.canvas.offset = QPointF(x - f.width() / (2 * self.canvas.scale),
                                     y - f.height() / (2 * self.canvas.scale))
        self.canvas.invalidate(structural=True)


class StatusBar(QFrame):
    """Нижняя панель: координаты, слои, автозахват/эластик/металлизация."""

    layerChanged = Signal(str)
    optionToggled = Signal(str, bool)
    helpRequested = Signal()

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("StatusBar")
        self.setFixedHeight(40)
        self.layer_buttons: Dict[str, QToolButton] = {}
        self._build()

    def _build(self):
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(8)
        self.coords = _lbl("X: 0.000  Y: 0.000")
        self.coords.setMinimumWidth(190)
        self.coords.setStyleSheet("font-family: Consolas, monospace;")
        h.addWidget(self.coords)
        self.units = QToolButton()
        self.units.setText("мм")
        self.units.setToolTip("Единицы: мм / милы")
        self.units.clicked.connect(self._toggle_units)
        h.addWidget(self.units)
        h.addSpacing(10)
        h.addWidget(_lbl("Слои:"))

        layers_box = QWidget()
        lb = QHBoxLayout(layers_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(3)
        for lk in ALL_LAYERS:
            b = QToolButton()
            b.setObjectName("LayerButton")
            b.setText(lk)
            b.setCheckable(True)
            b.setToolTip(LAYER_BY_KEY[lk].name)
            b.clicked.connect(lambda _c, k=lk: self.layerChanged.emit(k))
            self.layer_buttons[lk] = b
            lb.addWidget(b)
        h.addWidget(layers_box)
        h.addStretch(1)

        self.opt_buttons: Dict[str, QToolButton] = {}
        for key, text, tip in (("autograb", "Автозахват", "Курсор притягивается к КП"),
                               ("rubber", "Эластик", "Резиновые дорожки"),
                               ("metallization", "Металлизация", "Авто-земля")):
            b = QToolButton()
            b.setObjectName("ToggleButton")
            b.setText(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c, k=key: self._toggle(k))
            self.opt_buttons[key] = b
            h.addWidget(b)
        b = QToolButton()
        b.setText("?")
        b.setToolTip("Справка по структуре платы")
        b.clicked.connect(self.helpRequested.emit)
        h.addWidget(b)

    def _toggle(self, key: str):
        self.opt_buttons[key].setChecked(not self.opt_buttons[key].isChecked())
        self.optionToggled.emit(key, self.opt_buttons[key].isChecked())

    def _toggle_units(self):
        s = self.canvas.settings
        s["units"] = "mil" if s["units"] == "mm" else "mm"
        self.units.setText("милы" if s["units"] == "mil" else "мм")
        self.canvas.invalidate(structural=False)

    def set_coords(self, x: float, y: float, text: str):
        self.coords.setText(f"X: {text}   Y: {fmt_len(y, self.canvas.settings['units'])}")

    def refresh(self):
        c = self.canvas
        b = c.board()
        for lk, btn in self.layer_buttons.items():
            btn.setText(("● " if lk == c.active_layer else "") + lk)
            btn.setChecked(lk == c.active_layer)
            vis = b.visible.get(lk, True)
            btn.setToolTip(f"{LAYER_BY_KEY[lk].name}\n{'виден' if vis else 'скрыт'}"
                           f"\n{'Многослойная отключена' if lk in ('V1','V2') and not b.multilayer else ''}")
            font = btn.font()
            font.setStrikeOut(not vis)
            btn.setFont(font)
        s = c.settings
        self.opt_buttons["autograb"].setChecked(s["autograb"])
        self.opt_buttons["rubber"].setChecked(s["rubber"] > 0)
        self.opt_buttons["metallization"].setChecked(s["metallization"])
        self.units.setText("милы" if s["units"] == "mil" else "мм")


class PropertiesPanel(QFrame):
    """Панель свойств выделенного элемента (без диалогов)."""

    changed = Signal()
    requestDialog = Signal(str)

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("SidePanel")
        self.host = QWidget()
        self.v = QVBoxLayout(self.host)
        self.v.setContentsMargins(10, 8, 10, 8)
        self.v.setSpacing(6)
        self.area = QVBoxLayout()
        self.area.setSpacing(6)
        self.v.addLayout(self.area)
        self.v.addStretch(1)

        self.title = _lbl("Свойства", True)
        self.title.setStyleSheet("font-size: 15px;")
        self.v.insertWidget(0, self.title)
        self.fields: Dict[str, QWidget] = {}
        self._editing = False

    def _add(self, key: str, label: str, widget: QWidget):
        self.fields[key] = widget
        self.area.addWidget(_row(label, widget))

    def clear(self):
        while self.area.count():
            it = self.area.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.fields = {}

    def _dbl(self, value: float, step: float = 0.05, dec: int = 3) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(dec)
        sp.setRange(0.0, 10000.0)
        sp.setSingleStep(step)
        sp.setValue(value)
        sp.setKeyboardTracking(False)
        sp.valueChanged.connect(lambda _v: self._apply())
        return sp

    def _combo(self, items: Sequence, current=None) -> QComboBox:
        cb = QComboBox()
        cb.addItems([str(i) for i in items])
        if current is not None:
            cb.setCurrentText(str(current))
        cb.currentTextChanged.connect(lambda _v: self._apply())
        return cb

    def _check(self, checked: bool) -> QCheckBox:
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.toggled.connect(lambda _v: self._apply())
        return cb

    def _apply(self):
        if self._editing:
            return
        self._editing = True
        try:
            self._write()
        finally:
            self._editing = False
        self.canvas.touch()
        self.canvas.invalidate()
        self.changed.emit()

    def refresh(self):
        c = self.canvas
        els = [c.board().elements[i] for i in c.selection if i in c.board().elements]
        self.clear()
        if not els:
            self.area.addWidget(_lbl("Ничего не выбрано.\n\nВыделите элемент "
                                      "инструментом «Курсор» (Esc).", False))
            self.area.addStretch(1)
            return
        kinds = {e.kind for e in els}
        self.area.addWidget(_lbl(f"Выбрано: {len(els)}   Тип: "
                                 + ", ".join(sorted(els[0].type_name for _ in [0]) if len(kinds) == 1 else "смешанно")))
        first = els[0]

        def common():
            self._add("layer", "Слой", self._combo(
                [k for k in c.doc.active_layers()], first.layer))

        if len(kinds) == 1 and first.kind == "track":
            common()
            self._add("w", "Ширина", self._dbl(first.width))
            self._add("len", "Длина", _lbl(f"{first.length():.3f} мм"))
            self._add("nodes", "Узлов", _lbl(str(max(0, len(first.points) - 1))))
            self._add("imax", "Imax, А", self._dbl(first.imax, 0.1, 2))
            self._add("sq", "Прямые концы", self._check(first.square_ends))
            self._add("neg", "Негативно (вырез)", self._check(first.negative))
            self._add("rubber", "Резиновая", self._check(first.rubber))
        elif len(kinds) == 1 and first.kind == "pad":
            common()
            self._add("pd", "Диаметр площадки", self._dbl(first.pad_dia))
            self._add("hd", "Диаметр отверстия", self._dbl(first.hole_dia))
            self._add("shape", "Форма", self._combo(["circle", "rect", "oval", "rounded"], first.shape))
            self._add("plated", "С металлизацией", self._check(first.plated))
            self._add("thermal", "Термобарьер", self._check(first.thermal))
            self._add("clr", "Зазор", self._dbl(first.clearance))
            self._add("mask", "Окно маски", self._check(first.mask_open))
        elif len(kinds) == 1 and first.kind == "smd":
            common()
            self._add("w", "Ширина", self._dbl(first.w))
            self._add("h", "Высота", self._dbl(first.h))
            self._add("shape", "Форма", self._combo(["rect", "roundrect", "circle"], first.shape))
            self._add("thermal", "Термобарьер", self._check(first.thermal))
            self._add("clr", "Зазор", self._dbl(first.clearance))
            self._add("mask", "Окно маски", self._check(first.mask_open))
        elif len(kinds) == 1 and first.kind == "circle":
            common()
            self._add("r", "Радиус", self._dbl(first.r))
            self._add("w", "Толщина линии", self._dbl(first.width))
            self._add("fill", "С заливкой", self._check(first.filled))
            self._add("a0", "Угол начала", self._dbl(first.a0, 1, 1))
            self._add("a1", "Угол конца", self._dbl(first.a1, 1, 1))
            self._add("neg", "Негативно (вырез)", self._check(first.negative))
        elif len(kinds) == 1 and first.kind == "poly":
            common()
            self._add("cw", "Ширина контура", self._dbl(first.contour))
            self._add("grid", "Сетка (заливка линиями)", self._check(first.hatched))
            self._add("neg", "Негативно (вырез)", self._check(first.negative))
        elif len(kinds) == 1 and first.kind == "rect":
            common()
            self._add("w", "Толщина линии", self._dbl(first.width))
            self._add("fill", "Залитый", self._check(first.filled))
        elif len(kinds) == 1 and first.kind == "text":
            common()
            self._add("text", "Текст", self._text_widget(first))
            self._add("h", "Высота", self._dbl(first.height))
            self._add("th", "Толщина", self._dbl(first.thickness))
            self._add("st", "Стиль", self._combo(list(range(9)), first.style))
            self._add("ang", "Поворот", self._dbl(first.angle, 15, 1))
            self._add("mir", "Зеркало", self._combo(["", "X", "Y"], first.mirror))
            self._add("auto", "Автонумерация", self._check(first.auto_num))
        else:
            common()
        if len(els) > 1:
            b = QPushButton("Изменить все выделенные")
            b.clicked.connect(self._apply)
            self.area.addWidget(b)
        self.area.addStretch(1)

    def _text_widget(self, el: TextEl) -> QLineEdit:
        le = QLineEdit(el.text)
        le.editingFinished.connect(self._apply)
        return le

    def _write(self):
        c = self.canvas
        els = [c.board().elements[i] for i in c.selection if i in c.board().elements]
        f = self.fields
        if "layer" in f:
            val = f["layer"].currentText()
            for el in els:
                el.layer = val
        if all(isinstance(e, Track) for e in els) and els:
            for el in els:
                el.width = f["w"].value()
                el.imax = f["imax"].value()
                el.square_ends = f["sq"].isChecked()
                el.negative = f["neg"].isChecked()
                el.rubber = f["rubber"].isChecked()
        elif all(isinstance(e, Pad) for e in els) and els:
            for el in els:
                el.pad_dia = f["pd"].value()
                el.hole_dia = f["hd"].value()
                el.shape = f["shape"].currentText()
                if el.shape != "circle":
                    el.size = (el.pad_dia, el.pad_dia)
                el.plated = f["plated"].isChecked()
                el.thermal = f["thermal"].isChecked()
                el.clearance = f["clr"].value()
                el.mask_open = f["mask"].isChecked()
        elif all(isinstance(e, SmdPad) for e in els) and els:
            for el in els:
                el.w = f["w"].value()
                el.h = f["h"].value()
                el.shape = f["shape"].currentText()
                el.thermal = f["thermal"].isChecked()
                el.clearance = f["clr"].value()
                el.mask_open = f["mask"].isChecked()
        elif all(isinstance(e, CircleEl) for e in els) and els:
            for el in els:
                el.r = f["r"].value()
                el.width = f["w"].value()
                el.filled = f["fill"].isChecked()
                el.a0 = f["a0"].value()
                el.a1 = f["a1"].value()
                el.negative = f["neg"].isChecked()
        elif all(isinstance(e, PolygonEl) for e in els) and els:
            for el in els:
                el.contour = f["cw"].value()
                el.hatched = f["grid"].isChecked()
                el.negative = f["neg"].isChecked()
        elif all(isinstance(e, RectEl) for e in els) and els:
            for el in els:
                el.width = f["w"].value()
                el.filled = f["fill"].isChecked()
        elif all(isinstance(e, TextEl) for e in els) and els:
            for el in els:
                el.text = f["text"].text()
                el.height = f["h"].value()
                el.thickness = max(f["th"].value(),
                                   c.settings.get("min_text_thickness", 0.15))
                el.style = int(f["st"].currentText())
                el.angle = f["ang"].value()
                el.mirror = f["mir"].currentText()
                el.auto_num = f["auto"].isChecked()


class DrcPanel(QFrame):
    """Панель проверки условий."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        t = _lbl("Проверка условий (DRC)", True)
        t.setStyleSheet("font-size: 15px;")
        v.addWidget(t)
        row = QHBoxLayout()
        self.btn_all = QPushButton("Вся плата…")
        self.btn_all.setObjectName("Primary")
        self.btn_all.clicked.connect(lambda: self.run(False))
        self.btn_win = QPushButton("Окно…")
        self.btn_win.clicked.connect(lambda: self.run(True))
        self.btn_sel = QPushButton("Выбрать все")
        self.btn_sel.clicked.connect(self._select_all_errors)
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_win)
        row.addWidget(self.btn_sel)
        v.addLayout(row)
        self.rules_box = QGroupBox("Правила")
        rg = QFormLayout(self.rules_box) if False else QVBoxLayout(self.rules_box)
        self.rule_widgets: Dict[str, QWidget] = {}
        defaults = dict(self.canvas.settings["drc_rules"])
        for key, name in drc_mod.RULE_NAMES.items():
            val = defaults.get(key, drc_mod.DEFAULT_RULES[key])
            if isinstance(val, bool):
                w = QCheckBox()
                w.setChecked(val)
                w.setToolTip(name)
            else:
                w = QDoubleSpinBox()
                w.setDecimals(3)
                w.setRange(0.0, 100.0)
                w.setSingleStep(0.05)
                w.setValue(float(val))
            w.setToolTip(name)
            self.rule_widgets[key] = w
            rg.addWidget(_row(name, w))
        v.addWidget(self.rules_box)
        self.summary = _lbl("Проверка не выполнялась")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._jump)
        v.addWidget(self.list, 1)
        self.errors: List = []

    def _jump(self, item: QListWidgetItem):
        idx = self.list.row(item)
        if 0 <= idx < len(self.errors):
            self.canvas.jump_to_error(self.errors[idx])
            self.canvas.select([i for i in self.errors[idx].ids
                                if i in self.canvas.board().elements])

    def _select_all_errors(self):
        ids = sorted({i for e in self.errors for i in e.ids})
        self.canvas.select(ids)
        self.canvas.zoom_objects()

    def run(self, window: bool):
        for k, w in self.rule_widgets.items():
            self.canvas.settings["drc_rules"][k] = (w.isChecked() if isinstance(w, QCheckBox)
                                                    else w.value())
        errs = self.canvas.run_drc(window)
        self.errors = errs
        self.list.clear()
        for e in errs:
            title = drc_mod.RULE_NAMES.get(e.rule, e.rule)
            short = e.text.replace(" < ", " < ")
            it = QListWidgetItem(f"[{e.layer_name()}] {title}")
            it.setToolTip(e.text)
            it.setForeground(QColor(self.canvas.tokens.get("error", "#ffb4ab")))
            self.list.addItem(it)
        self.summary.setText(f"Найдено проблем: {len(errs)}. "
                             f"Двойной щелчок по строке — увеличить участок.")


class SelectorPanel(QFrame):
    """Селектор / фильтр поиска элементов с массовым редактированием."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        t = _lbl("Селектор / фильтр", True)
        t.setStyleSheet("font-size: 15px;")
        v.addWidget(t)
        self.cb_type = QComboBox()
        self.cb_type.addItems(["Все элементы", "Дорожки", "Контакты THT", "Контакты SMD",
                               "Круги/дуги", "Полигоны", "Тексты", "Прямоугольники",
                               "Линии связи", "Металлизация"])
        self.cb_sort = QComboBox()
        self.cb_sort.addItems(["Без сортировки", "По ширине", "По длине", "По диаметру отверстия",
                               "По площади", "По слою"])
        self.cb_layer = QComboBox()
        self.cb_layer.addItems(["Все слои"] + ALL_LAYERS)
        for cb in (self.cb_type, self.cb_sort, self.cb_layer):
            cb.currentIndexChanged.connect(self.refresh)
        v.addWidget(_row("Элементы", self.cb_type))
        v.addWidget(_row("Сортировать по", self.cb_sort))
        v.addWidget(_row("Слои", self.cb_layer))
        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)
        v.addWidget(self.list, 1)
        self.btn_sel = QPushButton("Выделить группу")
        self.btn_sel.clicked.connect(self.select_group)
        self.btn_zoom = QPushButton("Лупа выделенного")
        self.btn_zoom.clicked.connect(self.canvas.zoom_objects)
        v.addWidget(self.btn_sel)
        v.addWidget(self.btn_zoom)
        self.groups: List[List[str]] = []
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(50)
        self.slider.valueChanged.connect(self._scale)
        v.addWidget(_row("Масштаб", self.slider))
        self.info = _lbl("")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.refresh()

    def _scale(self, v: int):
        s = 0.2 + v / 100 * 6
        self.canvas.set_scale(s)

    def refresh(self):
        c = self.canvas
        b = c.board()
        tmap = {"Дорожки": "track", "Контакты THT": "pad", "Контакты SMD": "smd",
                "Круги/дуги": "circle", "Полигоны": "poly", "Тексты": "text",
                "Прямоугольники": "rect", "Линии связи": "conn", "Металлизация": "fill"}
        kind = tmap.get(self.cb_type.currentText())
        layer = None if self.cb_layer.currentIndex() == 0 else self.cb_layer.currentText()
        els = [el for el in b.elements.values()
               if (kind is None or el.kind == kind)
               and (layer is None or el.layer == layer)]
        sort = self.cb_sort.currentText()
        key = None
        if sort == "По ширине":
            key = lambda e: getattr(e, "width", getattr(e, "w", getattr(e, "pad_dia", 0)))
        elif sort == "По длине":
            key = lambda e: e.length() if isinstance(e, Track) else 0
        elif sort == "По диаметру отверстия":
            key = lambda e: getattr(e, "hole_dia", 0)
        elif sort == "По площади":
            key = lambda e: (e.bbox()[2] - e.bbox()[0]) * (e.bbox()[3] - e.bbox()[1]) if e.bbox() else 0
        if key:
            els.sort(key=key)
        self.list.clear()
        for el in els:
            txt = f"{el.type_name}"
            if isinstance(el, Track):
                txt += f"  {el.width:.2f}×{el.length():.1f} мм  [{el.layer}]"
            elif isinstance(el, Pad):
                txt += f"  отв. {el.hole_dia:.2f} пл. {el.pad_dia:.2f} [{el.layer}]"
            elif isinstance(el, SmdPad):
                txt += f"  {el.w:.2f}×{el.h:.2f} мм [{el.layer}]"
            elif isinstance(el, CircleEl):
                txt += f"  R{el.r:.2f} [{el.layer}]"
            elif isinstance(el, TextEl):
                txt += f"  «{el.display_text()}» [{el.layer}]"
            self.list.addItem(QListWidgetItem(txt))
        self._els = els
        self.info.setText(f"Найдено элементов: {len(els)}")

    def _pick(self, item):
        i = self.list.row(item)
        if 0 <= i < len(getattr(self, "_els", [])):
            el = self._els[i]
            self.canvas.select([el.id])
            bb = el.bbox()
            if bb:
                self.canvas._zoom_to_box(bb, pad=18)

    def select_group(self):
        kind = {"Дорожки": "track", "Контакты THT": "pad", "Контакты SMD": "smd",
                "Круги/дуги": "circle", "Полигоны": "poly", "Тексты": "text",
                "Прямоугольники": "rect", "Линии связи": "conn",
                "Металлизация": "fill"}.get(self.cb_type.currentText())
        layer = None if self.cb_layer.currentIndex() == 0 else self.cb_layer.currentText()
        ids = [el.id for el in self.canvas.board().elements.values()
               if (kind is None or el.kind == kind) and (layer is None or el.layer == layer)]
        self.canvas.select(ids)

    def change_selected(self, attr: str, value):
        els = [self.canvas.board().elements[i] for i in self.canvas.selection
               if i in self.canvas.board().elements]
        if not els:
            return
        self.canvas.push_undo()
        for el in els:
            if hasattr(el, attr):
                setattr(el, attr, value)
        self.canvas.touch()
        self.canvas.invalidate()
        self.refresh()


class ComponentsPanel(QFrame):
    """Лист компонентов (BOM) с двусторонней связью и экспортом Pick+Place."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        t = _lbl("Лист компонентов (BOM)", True)
        t.setStyleSheet("font-size: 15px;")
        v.addWidget(t)
        h = QHBoxLayout()
        b1 = QPushButton("Из компонента…")
        b1.setObjectName("Primary")
        b1.clicked.connect(self.make_component)
        b2 = QPushButton("Редактировать…")
        b2.clicked.connect(self.edit_component)
        b3 = QPushButton("Удалить компонент")
        b3.setObjectName("Danger")
        b3.clicked.connect(self.remove_component)
        h.addWidget(b1)
        h.addWidget(b2)
        h.addWidget(b3)
        v.addLayout(h)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        v.addWidget(self.list, 1)
        h2 = QHBoxLayout()
        b4 = QPushButton("Экспорт Pick+Place…")
        b4.clicked.connect(self.export_pnp)
        b5 = QPushButton("Спецификация (BOM)")
        b5.clicked.connect(self.export_bom)
        h2.addWidget(b4)
        h2.addWidget(b5)
        v.addLayout(h2)
        b6 = QPushButton("Выровнять текст автоматически")
        b6.clicked.connect(self.auto_align_text)
        v.addWidget(b6)
        self.refresh()

    def refresh(self):
        b = self.canvas.board()
        self.list.clear()
        for c in b.components:
            txt = c.refdes or "(без обозначения)"
            if c.value:
                txt += f"  {c.value}"
            txt += f"   [{'верх' if c.side == 'top' else 'низ'}]  {len(c.ids)} эл."
            self.list.addItem(QListWidgetItem(txt))

    def _select(self, row: int):
        b = self.canvas.board()
        if 0 <= row < len(b.components):
            self.canvas.select(b.components[row].ids)

    def make_component(self):
        from ..core.tools_lib import assign_component, auto_refdes
        b = self.canvas.board()
        if not self.canvas.selection:
            self.canvas.statusMessage.emit("Сначала выделите элементы компонента")
            return
        ref = auto_refdes(b, "R")
        c = assign_component(b, self.canvas.selection, refdes=ref)
        self.refresh()

    def edit_component(self):
        from ..core.tools_lib import component_of
        from .dialogs import ComponentDialog
        b = self.canvas.board()
        row = self.list.currentRow()
        if not (0 <= row < len(b.components)):
            return
        c = b.components[row]
        dlg = ComponentDialog(self.canvas, c)
        if dlg.exec():
            dlg.apply()
            self.canvas.touch()
            self.canvas.invalidate()
            self.refresh()

    def remove_component(self):
        b = self.canvas.board()
        row = self.list.currentRow()
        if 0 <= row < len(b.components):
            del b.components[row]
            self.canvas.touch()
            self.canvas.invalidate()
            self.refresh()

    def auto_align_text(self):
        self.canvas.statusMessage.emit("Подписи остаются читаемыми при вращении "
                                        "(включено в настройках)")

    def export_pnp(self):
        from .dialogs import PnpDialog
        PnpDialog(self.canvas).exec()

    def export_bom(self):
        from ..core.exporters import bom_text
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        b = self.canvas.board()
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить спецификацию",
                                              f"{b.name or 'bom'}.txt", "Текст (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(bom_text(b))
        self.canvas.statusMessage.emit(f"Спецификация сохранена: {path}")


class PhotoPanel(QFrame):
    """Панель фотовида."""

    changed = Signal()

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        t = _lbl("Фотовид", True)
        t.setStyleSheet("font-size: 15px;")
        v.addWidget(t)
        v.addWidget(_lbl("Вид «как изготовленная»: без сетки и маркировки."))
        self.side = QComboBox()
        self.side.addItems(["Верх", "Низ"])
        self.side.currentIndexChanged.connect(self._side)
        v.addWidget(_row("Сторона", self.side))
        self.ch_comp = QCheckBox("С компонентами")
        self.ch_comp.toggled.connect(self._comp)
        self.ch_trans = QCheckBox("Полупрозрачный")
        self.ch_trans.toggled.connect(self._trans)
        v.addWidget(self.ch_comp)
        v.addWidget(self.ch_trans)
        v.addWidget(_lbl("Цвета:"))
        self.c_board = QPushButton("Плата…")
        self.c_solder = QPushButton("Паяная маска…")
        self.c_board.clicked.connect(self._color_board)
        self.c_solder.clicked.connect(self._color_solder)
        v.addWidget(self.c_board)
        v.addWidget(self.c_solder)
        note = _lbl("Печать из фотовида невозможна (как в Sprint-Layout).")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)

    def _side(self, i):
        self.canvas.photo_side = "top" if i == 0 else "bottom"
        self.canvas.invalidate(structural=True)

    def _comp(self, v):
        self.canvas.photo_components = v
        self.canvas.invalidate(structural=True)

    def _trans(self, v):
        self.canvas.photo_transparent = v
        self.canvas.invalidate(structural=True)

    def _color_board(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor("#c9a227"), self, "Цвет платы")
        if c.isValid():
            self.canvas.photo_board_color = c.name()
            self.canvas.invalidate(structural=True)

    def _color_solder(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor("#0f6b3a"), self, "Цвет паяной маски")
        if c.isValid():
            self.canvas.photo_solder_color = c.name()
            self.canvas.invalidate(structural=True)


class LibraryPanel(QFrame):
    """Библиотека макросов: сворачиваемые группы, предпросмотр, клик — размещение."""

    placeMacro = Signal(object)
    saveMacroRequested = Signal()

    def __init__(self, canvas: Canvas, library, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.library = library
        self.setObjectName("SidePanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        h = QHBoxLayout()
        t = _lbl("Библиотека макросов", True)
        t.setStyleSheet("font-size: 15px;")
        b_refresh = QToolButton()
        b_refresh.setIcon(icon("filter", "#c8d4e4", 18))
        b_refresh.setToolTip("Обновить список")
        b_refresh.clicked.connect(self.refresh)
        h.addWidget(t)
        h.addStretch(1)
        h.addWidget(b_refresh)
        v.addLayout(h)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск макроса…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        v.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemSelectionChanged.connect(self._preview)
        v.addWidget(self.tree, 1)

        self.preview = MacroPreview(canvas)
        v.addWidget(self.preview)

        h2 = QHBoxLayout()
        self.btn_rot = QPushButton("Поворот 90°")
        self.btn_rot.setToolTip("Повернуть размещаемый макрос на 90°")
        self.btn_rot.clicked.connect(self._rotate)
        self.btn_side = QPushButton("Сторона: ВЕР")
        self.btn_side.setToolTip("Разместить на нижней стороне платы")
        self.btn_side.clicked.connect(self._flip_side)
        self.btn_import = QPushButton("Загрузить макрос…")
        self.btn_import.setObjectName("Primary")
        self.btn_import.setToolTip("Добавить макрос из файла в библиотеку")
        self.btn_import.clicked.connect(self.import_macro)
        h2.addWidget(self.btn_rot)
        h2.addWidget(self.btn_side)
        v.addLayout(h2)
        v.addWidget(self.btn_import)

        h3 = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить макрос")
        self.btn_save.clicked.connect(self.saveMacroRequested.emit)
        self.btn_del = QPushButton("Удалить")
        self.btn_del.setObjectName("Danger")
        self.btn_del.clicked.connect(self._delete)
        h3.addWidget(self.btn_save)
        h3.addWidget(self.btn_del)
        v.addLayout(h3)
        self.refresh()

    def current_macro(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def refresh(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        text = self.search.text().strip().lower()
        groups: Dict[str, list] = {}
        for m in self.library.macros:
            if text and text not in m.name.lower() and text not in m.group.lower():
                continue
            groups.setdefault(m.group, []).append(m)
        for g in sorted(groups):
            head = QTreeWidgetItem([g])
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setForeground(0, QBrush(QColor("#9ecbff")))
            self.tree.addTopLevelItem(head)
            for m in sorted(groups[g], key=lambda x: x.name):
                it = QTreeWidgetItem([m.name])
                it.setData(0, Qt.ItemDataRole.UserRole, m)
                head.addChild(it)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _preview(self):
        self.preview.show_macro(self.current_macro())

    def _on_item_clicked(self, item, _col):
        m = item.data(0, Qt.ItemDataRole.UserRole)
        if m is not None:
            self.preview.show_macro(m)
            self.placeMacro.emit(m)

    def _rotate(self):
        self.canvas.macro_rot = (self.canvas.macro_rot + 90) % 360
        self.canvas.statusMessage.emit(f"Поворот макроса: {self.canvas.macro_rot}°")

    def _flip_side(self):
        self.canvas.macro_bottom = not self.canvas.macro_bottom
        self.btn_side.setText("Сторона: НИЗ" if self.canvas.macro_bottom else "Сторона: ВЕР")

    def _delete(self):
        m = self.current_macro()
        if m:
            self.canvas.push_undo()
            self.library.delete(m)
            self.library.scan()
            self.refresh()

    def import_macro(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Загрузить макрос в библиотеку", "",
            "Макросы e-cad (*.ecadm *.json);;Все файлы (*)")
        if not path:
            return
        try:
            import json
            from ..core.tools_lib import Macro
            with open(path, "r", encoding="utf-8") as f:
                m = Macro.from_dict(json.load(f))
            if not m.elements:
                raise ValueError("в файле нет элементов")
            m.group = m.group or "Импорт"
            m.name = m.name or os.path.splitext(os.path.basename(path))[0]
            m.path = None
            self.library.save(m)
            self.library.scan()
            self.refresh()
            self.canvas.statusMessage.emit(f"Макрос загружен: {m.name} ({len(m.elements)} эл.)")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Импорт макроса", f"Не удалось загрузить:\n{e}")


class MacroPreview(QWidget):
    """Предпросмотр макроса."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.macro = None
        self.setMinimumHeight(110)
        self.setMaximumHeight(170)

    def show_macro(self, macro):
        self.macro = macro
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter):
        t = self.canvas.tokens or {}
        p.fillRect(self.rect(), QColor(t.get("surface_container", "#1c2024")))
        if self.macro is None or not self.macro.elements:
            p.setPen(QColor(t.get("on_surface_variant", "#c2c7cf")))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Нет макроса")
            return
        bb = self.macro.bbox()
        w = max(0.1, bb[2] - bb[0])
        h = max(0.1, bb[3] - bb[1])
        s = min(self.width() / w, self.height() / h) * 0.85
        ox = (self.width() - w * s) / 2
        oy = (self.height() - h * s) / 2
        c = self.canvas
        old = (c.scale, QPointF(c.offset), c.field_origin)
        c.scale = s
        c.field_origin = QPoint(0, 0)
        c.offset = QPointF(bb[0] + (0 - ox) / s, bb[3] + (0 - oy) / s)
        for el in self.macro.elements:
            col = QColor(LAYER_BY_KEY.get(el.layer, LAYER_BY_KEY[TOP_KEY]).default_color)
            c._draw_element(p, el, col, False)
        c.scale, c.offset, c.field_origin = old
        p.setPen(QPen(QColor(t.get("outline", "#8c9199")), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
