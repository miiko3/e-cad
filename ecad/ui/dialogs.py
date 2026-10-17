"""Диалоги: текст, фигура, мастер площадок, экспорт CAM, печать, настройки."""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QScrollArea, QSlider,
                               QSpinBox,
                               QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from ..core import drc as drc_mod
from ..core.exporters import (DEFAULT_PNP_COLUMNS, ascii_safe, bom_text,
                              export_excellon, export_gerber_set, excellon, hpgl,
                              pick_and_place)
from ..core.geom import parse_len
from ..core.model import (ALL_LAYERS, COPPER_KEYS, LAYER_BY_KEY, Board,
                          CircleEl, Component, Connection, Element, FillEl, Pad,
                          PolygonEl, RectEl, SmdPad, TextEl, TOP_KEY, Track)
from ..core.tools_lib import WIZARD_TYPES, footprint_wizard
from .canvas import fmt_len
from .theme import icon


def _spin(dec: int = 3, lo: float = 0.0, hi: float = 10000.0, step: float = 0.05,
          val: float = 0.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    s.setKeyboardTracking(False)
    return s


def _row(*widgets, spacing: int = 6) -> QWidget:
    """Горизонтальная строка виджетов в обёртке-QWidget."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for it in widgets:
        if isinstance(it, int):
            h.addSpacing(it)
        elif isinstance(it, str):
            h.addWidget(QLabel(it))
        else:
            h.addWidget(it)
    return w


def _form(*rows) -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    f.setSpacing(8)
    for label, widget in rows:
        if isinstance(label, str):
            f.addRow(label, widget)
        elif widget is None:
            f.addRow(label)          
        else:
            f.addRow(label, widget)
    return f


class BaseDialog(QDialog):
    def __init__(self, canvas, title: str, parent=None, w: int = 460):
        super().__init__(parent)
        self.canvas = canvas
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(w)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(18, 16, 18, 14)
        self.v.setSpacing(10)

    def buttons(self, ok_text: str = "OK", cancel_text: str = "Отмена") -> QDialogButtonBox:
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(cancel_text)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.v.addWidget(bb)
        return bb



class TextDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Текст на схеме", parent)
        b = canvas.board()
        els = [b.elements[i] for i in canvas.selection if isinstance(b.elements.get(i), TextEl)]
        el = els[0] if els else None
        s = canvas.settings
        self.t_edit = QLineEdit(el.text if el else "")
        self.t_h = _spin(2, 0.1, 100, 0.1, el.height if el else s["text_height"])
        self.t_th = _spin(3, 0.05, 10, 0.05, el.thickness if el else s["text_thickness"])
        self.t_st = QComboBox()
        self.t_st.addItems([str(i) for i in range(9)])
        self.t_st.setCurrentText(str(el.style if el else s["text_style"]))
        self.t_ang = _spin(1, -360, 360, 15, el.angle if el else 0)
        self.t_mir = QComboBox()
        self.t_mir.addItems(["нет", "X", "Y"])
        self.t_mir.setCurrentText(el.mirror if el else "")
        self.t_auto = QCheckBox("Автоматически — дописывать возрастающий номер (R1, R2…)")
        self.t_auto.setChecked(el.auto_num if el else s["text_auto"])
        self.t_prefix = QLineEdit(el.prefix if el else "R")
        self.t_x = _spin(3, -10000, 10000, 0.1, el.x if el else canvas.cursor_mm[0])
        self.t_y = _spin(3, -10000, 10000, 0.1, el.y if el else canvas.cursor_mm[1])
        self.preview = TextPreview(canvas)
        self.t_edit.textChanged.connect(lambda _s: self.preview.update())
        self.t_h.valueChanged.connect(lambda _s: self.preview.update())
        self.t_st.currentIndexChanged.connect(lambda _s: self.preview.update())

        self.v.addLayout(_form(("Текст:", self.t_edit),
                               ("Высота, мм:", self.t_h),
                               ("Толщина, мм:", self.t_th),
                               ("Стиль (1-9):", self.t_st),
                               ("Поворот, °:", self.t_ang),
                               ("Зеркало по:", self.t_mir),
                               ("Префикс:", self.t_prefix),
                               ("X, мм:", self.t_x),
                               ("Y, мм:", self.t_y)))
        self.v.addWidget(self.t_auto)
        self.v.addWidget(QLabel("Предпросмотр:"))
        self.v.addWidget(self.preview)
        self.v.addWidget(QLabel("На нижних слоях (М2/К2) текст наносится зеркально; "
                                "двойной щелчок по тексту — правка."))
        self.buttons("Вставить")

    def make_element(self) -> TextEl:
        el = TextEl(layer=self.canvas.active_layer, text=self.t_edit.text(),
                    height=self.t_h.value(), thickness=self.t_th.value(),
                    style=int(self.t_st.currentText()), angle=self.t_ang.value(),
                    mirror="" if self.t_mir.currentText() == "нет" else self.t_mir.currentText(),
                    auto_num=self.t_auto.isChecked(), prefix=self.t_prefix.text() or "R",
                    x=self.t_x.value(), y=self.t_y.value())
        return el


class TextPreview(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.dlg: Optional[TextDialog] = None
        self.setMinimumHeight(56)

    def paintEvent(self, _evt):
        from PySide6.QtGui import QFont, QPainterPath
        p = QPainter(self)
        try:
            t = self.canvas.tokens or {}
            p.fillRect(self.rect(), QColor(t.get("surface_container_highest", "#31353a")))
            d = self.dlg
            if d:
                el = d.make_element()
                col = QColor(LAYER_BY_KEY.get(el.layer, LAYER_BY_KEY[TOP_KEY]).default_color)
                px = 30.0
                f = QFont("Segoe UI")
                f.setPixelSize(int(px))
                f.setBold((el.style // 3) == 1)
                f.setItalic((el.style // 3) == 2)
                path = QPainterPath()
                path.addText(6, px + 6, f, el.text or f"{el.prefix}1")
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawPath(path)
        finally:
            p.end()



class ShapeDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Фигура / массив", parent, 520)
        self.tabs = QTabWidget()
        
        p1 = QWidget()
        f1 = QFormLayout(p1)
        self.poly_n = QSpinBox()
        self.poly_n.setRange(3, 200)
        self.poly_n.setValue(12)
        self.poly_r = _spin(3, 0.1, 1000, 0.1, 5.0)
        self.poly_a = _spin(1, -360, 360, 15, 0)
        self.poly_w = _spin(3, 0.05, 20, 0.05, 0.25)
        self.poly_vertex = QCheckBox("Выделить вершину")
        self.poly_fill = QCheckBox("Залить")
        f1.addRow("Число вершин:", self.poly_n)
        f1.addRow("Радиус (биссектриса), мм:", self.poly_r)
        f1.addRow("Угол, °:", self.poly_a)
        f1.addRow("Ширина линии, мм:", self.poly_w)
        f1.addRow(self.poly_vertex)
        f1.addRow(self.poly_fill)
        self.tabs.addTab(p1, "Правильный многоугольник")

        
        p2 = QWidget()
        f2 = QFormLayout(p2)
        self.sp_type = QComboBox()
        self.sp_type.addItems(["Круглая (из четвертинок)", "Квадратная (дорожкой)"])
        self.sp_r1 = _spin(3, 0.1, 500, 0.1, 2.0)
        self.sp_r2 = _spin(3, 0.1, 500, 0.1, 10.0)
        self.sp_turns = _spin(2, 0.25, 50, 0.25, 4)
        self.sp_w = _spin(3, 0.05, 10, 0.05, 0.3)
        f2.addRow("Тип:", self.sp_type)
        f2.addRow("Начальный радиус, мм:", self.sp_r1)
        f2.addRow("Конечный радиус, мм:", self.sp_r2)
        f2.addRow("Оборотов:", self.sp_turns)
        f2.addRow("Ширина линии, мм:", self.sp_w)
        self.tabs.addTab(p2, "Спираль")

        
        p3 = QWidget()
        f3 = QFormLayout(p3)
        self.ar_rows = QSpinBox()
        self.ar_rows.setRange(1, 200)
        self.ar_cols = QSpinBox()
        self.ar_cols.setRange(1, 200)
        self.ar_cols.setValue(2)
        self.ar_dx = _spin(3, 0.01, 1000, 0.1, 2.54)
        self.ar_dy = _spin(3, 0.01, 1000, 0.1, 2.54)
        self.ar_num = QCheckBox("Нумерация (автоинкремент)")
        f3.addRow("Строки:", self.ar_rows)
        f3.addRow("Столбцы:", self.ar_cols)
        f3.addRow("Шаг X, мм:", self.ar_dx)
        f3.addRow("Шаг Y, мм:", self.ar_dy)
        f3.addRow(self.ar_num)
        self.tabs.addTab(p3, "Матрица (форма)")
        self.v.addWidget(self.tabs)
        self.buttons("Создать")

    def generate(self, layer: str, center) -> List[Element]:
        idx = self.tabs.currentIndex()
        cx, cy = center
        out: List[Element] = []
        if idx == 0:
            n = self.poly_n.value()
            r = self.poly_r.value()
            a0 = math.radians(self.poly_a.value())
            pts = [(cx + r * math.cos(a0 + i * 2 * math.pi / n),
                    cy + r * math.sin(a0 + i * 2 * math.pi / n)) for i in range(n)]
            out.append(PolygonEl(layer=layer, points=pts, contour=self.poly_w.value()))
            if self.poly_fill.isChecked():
                out.append(CircleEl(layer=layer, cx=cx, cy=cy, r=r, filled=True))
            if self.poly_vertex.isChecked():
                out.append(CircleEl(layer=layer, cx=pts[0][0], cy=pts[0][1], r=0.2,
                                    width=0.2))
        elif idx == 1:
            r1, r2 = self.sp_r1.value(), self.sp_r2.value()
            turns = self.sp_turns.value()
            n = max(8, int(turns * 24))
            pts = []
            for i in range(n + 1):
                t = i / n
                a = t * turns * 2 * math.pi
                r = r1 + (r2 - r1) * t
                if self.sp_type.currentIndex() == 0:
                    pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
                else:
                    k = 4 * (a / (2 * math.pi))
                    frac = k - math.floor(k)
                    sx = 1 if (math.floor(k) % 2 == 0) else -1
                    sy = 1 if ((math.floor(k) // 2) % 2 == 0) else -1
                    pts.append((cx + sx * r, cy + sy * r))
            out.append(Track(layer=layer, points=pts, width=self.sp_w.value()))
        else:
            return []   
        return out


class ArrayDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Каскад (массив)", parent)
        self.mode = QComboBox()
        self.mode.addItems(["Каскад (линейный)", "По кругу"])
        self.count = QSpinBox()
        self.count.setRange(2, 5000)
        self.count.setValue(4)
        self.dx = _spin(3, 0.01, 1000, 0.1, 2.54)
        self.dy = _spin(3, 0.01, 1000, 0.1, 2.54)
        self.radius = _spin(3, 0.1, 1000, 0.1, 10.0)
        self.astep = _spin(2, 0.1, 360, 5, 30)
        self.v.addLayout(_form(("Режим:", self.mode),
                               ("Количество:", self.count),
                               ("Шаг X, мм:", self.dx),
                               ("Шаг Y, мм:", self.dy),
                               ("Радиус, мм:", self.radius),
                               ("Шаг по углу, °:", self.astep)))
        self.mode.currentIndexChanged.connect(self._upd)
        self._upd()
        self.buttons("Разложить")

    def _upd(self):
        radial = self.mode.currentIndex() == 1
        self.dx.setEnabled(not radial)
        self.dy.setEnabled(not radial)
        self.radius.setEnabled(radial)
        self.astep.setEnabled(radial)



class WizardDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Мастер площадок (Footprint Wizard)", parent, 520)
        self.type = QComboBox()
        for key, name in WIZARD_TYPES:
            self.type.addItem(name, key)
        self.pads = QSpinBox()
        self.pads.setRange(2, 400)
        self.pads.setValue(8)
        self.pitch = _spin(3, 0.1, 50, 0.05, 2.54)
        self.row_span = _spin(3, 0.1, 100, 0.1, 7.62)
        self.pad_dia = _spin(3, 0.1, 20, 0.1, 1.6)
        self.hole_dia = _spin(3, 0.1, 20, 0.1, 0.9)
        self.smd = QComboBox()
        self.smd.addItems(["THT (сквозной)", "SMD (поверхностный)"])
        self.smd_w = _spin(3, 0.1, 20, 0.1, 0.6)
        self.smd_h = _spin(3, 0.1, 20, 0.1, 1.5)
        self.body_l = _spin(3, 0.1, 200, 0.1, 9.8)
        self.body_w = _spin(3, 0.1, 200, 0.1, 6.0)
        self.radius = _spin(3, 0.5, 200, 0.5, 5.0)
        self.first_sq = QCheckBox("Первый контакт квадратный (вывод №1)")
        self.first_sq.setChecked(True)
        self.btn_def = QPushButton("По умолчанию")
        self.preview = WizardPreview(self)
        self.v.addLayout(_form(("Тип корпуса:", self.type),
                               ("Кол-во выводов:", self.pads),
                               ("Интервал (pitch), мм:", self.pitch),
                               ("Между рядами, мм:", self.row_span),
                               ("Размер КП THT, мм:", self.pad_dia),
                               ("Отверстие, мм:", self.hole_dia),
                               ("Тип контактов:", self.smd),
                               ("SMD ширина/высота:", _form_rows(self.smd_w, self.smd_h)),
                               ("Длина/ширина корпуса:", _form_rows(self.body_l, self.body_w)),
                               ("Радиус кольца:", self.radius)))
        self.v.addWidget(self.first_sq)
        self.v.addWidget(self.btn_def)
        self.v.addWidget(QLabel("Предпросмотр:"))
        self.v.addWidget(self.preview)
        for w in (self.pads, self.pitch, self.row_span, self.pad_dia, self.hole_dia,
                  self.body_l, self.body_w, self.radius):
            w.valueChanged.connect(self.preview.update)
        self.type.currentIndexChanged.connect(self.preview.update)
        self.btn_def.clicked.connect(self._defaults)
        self.buttons("Создать на плате")

    def _defaults(self):
        t = self.type.currentData()
        presets = {"sip": (8, 2.54, 1.6, 0.9, 10.0, 3.0),
                   "dip": (16, 2.54, 7.62, 1.6, 0.9, 20.0, 7.62),
                   "quad": (32, 0.8, 5.0, 0.6, 0.0, 12.0, 12.0),
                   "ring": (8, 2.0, 1.5, 0.8, 5.0, 10.0, 10.0),
                   "ring2": (16, 2.0, 1.5, 0.8, 8.0, 16.0, 16.0)}
        p = presets[t]
        self.pads.setValue(p[0])
        self.pitch.setValue(p[1])
        if t in ("dip",):
            self.row_span.setValue(p[2])
        self.pad_dia.setValue(p[2] if t not in ("dip",) else p[3])
        self.hole_dia.setValue(p[3] if t not in ("dip",) else p[4])
        self.body_l.setValue(p[-2])
        self.body_w.setValue(p[-1])
        self.preview.update()

    def generate(self, layer: str) -> List[Element]:
        t = self.type.currentData()
        is_smd = self.smd.currentIndex() == 1
        if t == "quad":
            self.smd.setCurrentIndex(1)
            is_smd = True
        return footprint_wizard(t, pads=self.pads.value(), pitch=self.pitch.value(),
                                row_span=self.row_span.value(), pad_dia=self.pad_dia.value(),
                                hole_dia=self.hole_dia.value(), smd=is_smd,
                                smd_w=self.smd_w.value(), smd_h=self.smd_h.value(),
                                radius=self.radius.value(), body_l=self.body_l.value(),
                                body_w=self.body_w.value(),
                                first_pad_square=self.first_sq.isChecked(), layer=layer)


def _form_rows(a: QWidget, b: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(a)
    h.addWidget(QLabel("×"))
    h.addWidget(b)
    return w


class WizardPreview(QWidget):
    def __init__(self, dlg: WizardDialog, parent=None):
        super().__init__(parent)
        self.dlg = dlg
        self.setMinimumHeight(190)

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            from PySide6.QtCore import QPoint, QPointF
            from PySide6.QtGui import QPolygonF
            c = self.dlg.canvas
            t = c.tokens or {}
            p.fillRect(self.rect(), QColor(t.get("surface_container_highest", "#31353a")))
            els = self.dlg.generate(TOP_KEY)
            boxes = [e.bbox() for e in els if e.bbox()]
            if not boxes:
                p.setPen(QColor(t.get("on_surface_variant", "#c2c7cf")))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Нет данных")
                return
            x0 = min(b[0] for b in boxes)
            y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes)
            y1 = max(b[3] for b in boxes)
            w = max(0.1, x1 - x0)
            h = max(0.1, y1 - y0)
            s = min(self.width() / w, self.height() / h) * 0.85
            ox = (self.width() - w * s) / 2
            oy = (self.height() - h * s) / 2
            old = (c.scale, QPointF(c.offset), c.field_origin)
            c.scale = s
            c.field_origin = QPoint(0, 0)
            c.offset = QPointF(x0 - ox / s, y1 + oy / s)
            for el in els:
                col = QColor(LAYER_BY_KEY.get(el.layer, LAYER_BY_KEY[TOP_KEY]).default_color)
                c._draw_element(p, el, col, False)
            c.scale, c.offset, c.field_origin = old
        finally:
            p.end()



class GerberExportDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Экспорт в формате Gerber RS-274X", parent, 560)
        self.ch_layers = QListWidget()
        self.ch_layers.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        b = canvas.board()
        for lk in ALL_LAYERS:
            if lk in ("V1", "V2") and not b.multilayer:
                continue
            it = QListWidgetItem(f"{lk} — {LAYER_BY_KEY[lk].name}")
            it.setData(Qt.ItemDataRole.UserRole, lk)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.ch_layers.addItem(it)
        self.ch_mirror = QListWidget()
        self.ch_mirror.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for lk in ALL_LAYERS:
            it = QListWidgetItem(f"Зеркально {lk}")
            it.setData(Qt.ItemDataRole.UserRole, lk)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.ch_mirror.addItem(it)
        s = canvas.settings
        self.ch_outline = QCheckBox("Дописать контур платы (габариты) в файл слоя")
        self.ch_open_holes = QCheckBox("Открыть отверстия (нельзя при металлизированных)")
        self.ch_open_holes.setChecked(True)
        self.ch_center = QCheckBox("Центр отверстия 0,15 мм (керовка)")
        self.ch_mask = QCheckBox("Создать файлы паяльной маски")
        self.ch_mask.setChecked(True)
        self.ch_paste = QCheckBox("Создать трафарет под пасту (SMD)")
        self.ch_paste.setChecked(True)
        self.ch_invert = QCheckBox("Инвертировать маску")
        self.g_tht = _spin(3, 0, 2, 0.01, s["imask_gap_tht"])
        self.g_smd = _spin(3, 0, 2, 0.01, s["mask_gap_smd"])
        self.name = QLineEdit(ascii_safe(b.name) or "board")
        self.protocol = QTextEdit()
        self.protocol.setReadOnly(True)
        self.protocol.setMaximumHeight(150)

        h = QHBoxLayout()
        h.addWidget(self.ch_layers, 1)
        h.addWidget(self.ch_mirror, 1)
        self.v.addLayout(h)
        self.v.addLayout(_form(("Имя файлов:", self.name)))
        g = QGroupBox("Опции")
        gv = QVBoxLayout(g)
        for ch in (self.ch_outline, self.ch_open_holes, self.ch_center, self.ch_mask,
                   self.ch_paste, self.ch_invert):
            gv.addWidget(ch)
        gv.addWidget(_row("Зазор маски THT, мм:", self.g_tht))
        gv.addWidget(_row("Зазор маски SMD, мм:", self.g_smd))
        self.v.addWidget(g)
        self.v.addWidget(QLabel("Протокол:"))
        self.v.addWidget(self.protocol)
        bb = QDialogButtonBox()
        self.btn_make = QPushButton("Создать Gerber-файлы")
        self.btn_make.setObjectName("Primary")
        self.btn_make.clicked.connect(self.run)
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        bb.addButton(self.btn_make, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(self.btn_close, QDialogButtonBox.ButtonRole.AcceptRole)
        self.v.addWidget(bb)

    def _checked(self, w: QListWidget) -> List[str]:
        return [w.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.count())
                if w.item(i).checkState() == Qt.CheckState.Checked]

    def run(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка для Gerber-файлов")
        if not folder:
            return
        self.protocol.append(f"Каталог: {folder}")
        self.protocol.append(f"Плата: {self.canvas.board().name}")
        layers = self._checked(self.ch_layers)
        mirror = tuple(self._checked(self.ch_mirror))
        try:
            made = export_gerber_set(self.canvas.board(), folder, layers,
                                     self.name.text().strip() or "board", mirror=mirror,
                                     add_outline=self.ch_outline.isChecked(),
                                     open_holes=self.ch_open_holes.isChecked(),
                                     hole_center=0.15 if self.ch_center.isChecked() else 0.0,
                                     mask_tht=self.g_tht.value(), mask_smd=self.g_smd.value(),
                                     solder_mask=self.ch_mask.isChecked(),
                                     paste_mask=self.ch_paste.isChecked(),
                                     invert_mask=self.ch_invert.isChecked(),
                                     log=self.protocol.append)
            self.protocol.append(f"Готово: {len(made)} файлов")
            self.canvas.statusMessage.emit(f"Gerber: создано {len(made)} файлов в {folder}")
        except Exception as e:
            self.protocol.append(f"ОШИБКА: {e}")
            QMessageBox.warning(self, "Ошибка экспорта", str(e))



class DrillDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Данные отверстий (Excellon)", parent, 520)
        self.side = QComboBox()
        self.side.addItems(["Сторона 1 (верх)", "Сторона 2 (низ, зеркально)"])
        self.only_plated = QComboBox()
        self.only_plated.addItems(["Только металлизированные", "Все отверстия"])
        self.unit = QComboBox()
        self.unit.addItems(["мм", "дюймы"])
        self.int_d = QSpinBox()
        self.int_d.setRange(1, 6)
        self.int_d.setValue(3)
        self.dec_d = QSpinBox()
        self.dec_d.setRange(1, 6)
        self.dec_d.setValue(3)
        self.strip = QCheckBox("Удалять незначащие нули")
        self.sort = QCheckBox("Сортировать по диаметру (минимум перемещений сверла)")
        self.sort.setChecked(True)
        self.separate = QCheckBox("Раздельно для металлизированных и неметаллизированных")
        self.separate.setChecked(True)
        self.m71 = QCheckBox("Использовать M71/M72 вместо мм/дюйм")
        self.g90 = QCheckBox("Добавить G90 (абсолютные координаты)")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(180)
        self.v.addLayout(_form(("Координаты:", self.side),
                               ("Тип отверстий:", self.only_plated),
                               ("Единица:", self.unit),
                               ("Целых/дробных:", _form_rows(self.int_d, self.dec_d)),
                               (self.strip, None),
                               (self.sort, None),
                               (self.separate, None),
                               (self.m71, None),
                               (self.g90, None)))
        self.v.addWidget(QLabel("Предпросмотр:"))
        self.v.addWidget(self.preview)
        for w in (self.side, self.only_plated, self.unit, self.int_d, self.dec_d):
            w.currentIndexChanged.connect(self.refresh) if hasattr(w, "currentIndexChanged") \
                else w.valueChanged.connect(self.refresh)
        self.refresh()
        bb = QDialogButtonBox()
        b1 = QPushButton("Создать файл сверловки")
        b1.setObjectName("Primary")
        b1.clicked.connect(self.run)
        b2 = QPushButton("Закрыть")
        b2.clicked.connect(self.reject)
        bb.addButton(b1, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b2, QDialogButtonBox.ButtonRole.RejectRole)
        self.v.addWidget(bb)

    def text(self) -> str:
        return excellon(self.canvas.board(),
                        side="top" if self.side.currentIndex() == 0 else "bottom",
                        only_plated=self.only_plated.currentIndex() == 0,
                        unit="mm" if self.unit.currentIndex() == 0 else "inch",
                        int_digits=self.int_d.value(), dec_digits=self.dec_d.value(),
                        strip_zeros=self.strip.isChecked(),
                        sort_by_dia=self.sort.isChecked(),
                        metal_separate=self.separate.isChecked(),
                        m71=self.m71.isChecked(), g90=self.g90.isChecked())

    def refresh(self):
        self.preview.setPlainText(self.text()[:4000])

    def run(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка для файла сверловки")
        if not folder:
            return
        fn = export_excellon(self.canvas.board(), folder,
                             ascii_safe(self.canvas.board().name) or "board",
                             side="top" if self.side.currentIndex() == 0 else "bottom",
                             only_plated=self.only_plated.currentIndex() == 0,
                             unit="mm" if self.unit.currentIndex() == 0 else "inch",
                             int_digits=self.int_d.value(), dec_digits=self.dec_d.value(),
                             strip_zeros=self.strip.isChecked(),
                             metal_separate=self.separate.isChecked(),
                             m71=self.m71.isChecked(), g90=self.g90.isChecked())
        self.canvas.statusMessage.emit(f"Сверловка сохранена: {fn}")



class HpglDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Данные фрезерования (HPGL, *.plt)", parent, 540)
        self.mill = _spin(3, 0.05, 10, 0.05, 1.0)
        self.side = QComboBox()
        self.side.addItems(["М1 — верх", "М2 — низ (зеркально)"])
        self.kerf = QCheckBox("Кернить отверстия (занижать точку сверления)")
        self.passes = QSpinBox()
        self.passes.setRange(1, 20)
        self.overlap = _spin(1, 0, 95, 5, 50)
        self.holes = QComboBox()
        self.holes.addItems(["Фрезеровать все одной фрезой (CI)",
                             "Сверлить PD одним диаметром",
                             "Сверлить PD требуемыми диаметрами"])
        self.contour = QCheckBox("Фрезеровать контур платы по слою О")
        self.contour.setChecked(True)
        self.marks = QSpinBox()
        self.marks.setRange(0, 4)
        self.marks.setValue(2)
        self.marks_dist = _spin(2, 0.5, 50, 0.5, 3.0)
        self.text_mode = QComboBox()
        self.text_mode.addItems(["С контуром", "1 линия по центру"])
        self.only_sel = QCheckBox("Только выделенные элементы")
        self.scale = QCheckBox("Шкала: единица HPGL 0,025 мм")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(150)
        self.v.addLayout(_form(("Диаметр фрезы, мм:", self.mill),
                               ("Сторона:", self.side),
                               (self.kerf, None),
                               ("Число проходов:", self.passes),
                               ("% перекрытия:", self.overlap),
                               ("Отверстия:", self.holes),
                               (self.contour, None),
                               ("Реперные метки:", _form_rows(self.marks, self.marks_dist)),
                               ("Текст:", self.text_mode),
                               (self.only_sel, None),
                               (self.scale, None)))
        self.v.addWidget(QLabel("Предпросмотр операций:"))
        self.v.addWidget(self.preview)
        self.holes_mode_name = ["all_one", "one_dia", "each_dia"]
        self._upd()
        for w in (self.mill, self.passes, self.overlap, self.marks, self.marks_dist):
            w.valueChanged.connect(self._upd)
        self.holes.currentIndexChanged.connect(self._upd)
        self.side.currentIndexChanged.connect(self._upd)
        self.contour.toggled.connect(self._upd)
        self.text_mode.currentIndexChanged.connect(self._upd)
        bb = QDialogButtonBox()
        b1 = QPushButton("Создать файл фрезерования")
        b1.setObjectName("Primary")
        b1.clicked.connect(self.run)
        b2 = QPushButton("Сохранить протокол (*.txt)")
        b2.clicked.connect(self.save_log)
        b3 = QPushButton("Закрыть")
        b3.clicked.connect(self.reject)
        bb.addButton(b1, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b2, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b3, QDialogButtonBox.ButtonRole.RejectRole)
        self.v.addWidget(bb)

    def params(self) -> dict:
        return dict(mill_dia=self.mill.value(),
                    side="top" if self.side.currentIndex() == 0 else "bottom",
                    drill_kerf=self.kerf.isChecked(),
                    passes=self.passes.value(),
                    overlap=self.overlap.value(),
                    holes_mode=self.holes_mode_name[self.holes.currentIndex()],
                    contour=self.contour.isChecked(),
                    marks=self.marks.value(),
                    marks_dist=self.marks_dist.value(),
                    text_mode="contour" if self.text_mode.currentIndex() == 0 else "center",
                    selected=self.canvas.selection if self.only_sel.isChecked() else None,
                    scale_0025=self.scale.isChecked())

    def _upd(self):
        try:
            text, log = hpgl(self.canvas.board(), **self.params())
            self.preview.setPlainText("\n".join(log) + "\n\n" + text[:2000])
        except Exception as e:
            self.preview.setPlainText(f"Ошибка: {e}")

    def run(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка для файла фрезерования")
        if not folder:
            return
        text, log = hpgl(self.canvas.board(), **self.params())
        fn = os.path.join(folder, f"{ascii_safe(self.canvas.board().name) or 'board'}_mill.plt")
        with open(fn, "w", encoding="ascii") as f:
            f.write(text)
        self.canvas.statusMessage.emit(f"Фрезерование сохранено: {fn}")

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить протокол", "mill_ops.txt",
                                              "Текст (*.txt)")
        if not path:
            return
        text, log = hpgl(self.canvas.board(), **self.params())
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(log))
            f.write("\n\n" + text)



class PrintDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Печать (реальный размер 1:1)", parent, 620)
        self.layers = QListWidget()
        self.layers.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        b = canvas.board()
        for lk in ALL_LAYERS:
            if lk in ("V1", "V2") and not b.multilayer:
                continue
            it = QListWidgetItem(lk)
            it.setData(Qt.ItemDataRole.UserRole, lk)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if lk in ("M1", "M2", "O") else
                             Qt.CheckState.Unchecked)
            self.layers.addItem(it)
        self.preset = QComboBox()
        self.preset.addItems(["Свой набор", "ЛУТ (низ)", "ЛУТ (верх)", "ЛУТ (обе стороны)",
                              "Маркировка ЛУТ", "Позитивный фоторезист",
                              "Негативный фоторезист"])
        self.preset.currentIndexChanged.connect(self._preset)
        self.ch_mask = QCheckBox("Маска по припою (увеличить КП)")
        self.ch_holes = QCheckBox("Отверстия (центры «×» + диаметр)")
        self.ch_bw = QCheckBox("Все чёрным")
        self.ch_mirror_all = QCheckBox("Зеркально все слои")
        self.ch_mirror_bottom = QCheckBox("М2, К2, В2 — зеркало")
        self.ch_corners = QCheckBox("Угол платы (перекрестия)")
        self.ch_outline = QCheckBox("Контур платы")
        self.ch_template = QCheckBox("Фоновый рисунок (шаблон)")
        self.ch_negative = QCheckBox("Негатив (для негативного фоторезиста)")
        self.ch_aux = QCheckBox("Вспомогательная сетка")
        self.ch_info = QCheckBox("Информ-строка (файл, плата, масштаб, дата)")
        self.scale = _spin(1, 10, 500, 5, 100)
        self.copies_x = QSpinBox(); self.copies_x.setRange(1, 50); self.copies_x.setValue(1)
        self.copies_y = QSpinBox(); self.copies_y.setRange(1, 50); self.copies_y.setValue(1)
        self.gap = _spin(2, 0, 100, 1, 5)
        self.corr_x = _spin(4, 0.9, 1.1, 0.001, 1.0)
        self.corr_y = _spin(4, 0.9, 1.1, 0.001, 1.0)
        self.preview = PrintPreview(canvas, self)
        self.v.addWidget(_row("Пресет:", self.preset))
        h = QHBoxLayout()
        h.addWidget(self.layers, 1)
        g = QGroupBox("Опции")
        gv = QVBoxLayout(g)
        for ch in (self.ch_mask, self.ch_holes, self.ch_bw, self.ch_mirror_all,
                   self.ch_mirror_bottom, self.ch_corners, self.ch_outline,
                   self.ch_template, self.ch_negative, self.ch_aux, self.ch_info):
            gv.addWidget(ch)
        h.addWidget(g, 1)
        self.v.addLayout(h)
        self.v.addLayout(_form(("Масштаб, %:", self.scale),
                               ("Копии X:", self.copies_x),
                               ("Копии Y:", self.copies_y),
                               ("Интервал, мм:", self.gap),
                               ("Коррекция X:", self.corr_x),
                               ("Коррекция Y:", self.corr_y)))
        self.v.addWidget(QLabel("Предпросмотр (красная рамка — границы печати):"))
        self.v.addWidget(self.preview)
        for w in (self.scale, self.copies_x, self.copies_y, self.gap,
                  self.corr_x, self.corr_y):
            w.valueChanged.connect(self.preview.update)
        for ch in (self.ch_mask, self.ch_holes, self.ch_bw, self.ch_mirror_all,
                   self.ch_mirror_bottom, self.ch_corners, self.ch_outline,
                   self.ch_negative, self.ch_aux, self.ch_info):
            ch.toggled.connect(self.preview.update)
        bb = QDialogButtonBox()
        b1 = QPushButton("Печать")
        b1.setObjectName("Primary")
        b1.clicked.connect(self.do_print)
        b2 = QPushButton("В центр")
        b2.clicked.connect(self.copy_clip)
        b3 = QPushButton("Отмена")
        b3.clicked.connect(self.reject)
        bb.addButton(b1, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b2, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b3, QDialogButtonBox.ButtonRole.RejectRole)
        self.v.addWidget(bb)

    def _preset(self, i):
        def set_layers(keys, mirror=False, bw=False, neg=False, outline=True):
            for j in range(self.layers.count()):
                it = self.layers.item(j)
                k = it.data(Qt.ItemDataRole.UserRole)
                it.setCheckState(Qt.CheckState.Checked if k in keys else Qt.CheckState.Unchecked)
            self.ch_bw.setChecked(bw)
            self.ch_mirror_all.setChecked(mirror)
            self.ch_negative.setChecked(neg)
            self.ch_outline.setChecked(outline)
            self.preview.update()

        if i == 1:
            set_layers({BOTTOM_KEY, "O"}, bw=True)
        elif i == 2:
            set_layers({TOP_KEY, "O"}, bw=True, mirror=True)
        elif i == 3:
            set_layers({TOP_KEY, BOTTOM_KEY, "O"}, bw=True, mirror=True)
        elif i == 4:
            set_layers({"K1", "K2"}, bw=True)
        elif i == 5:
            set_layers({TOP_KEY, BOTTOM_KEY, "O"}, bw=True)
        elif i == 6:
            set_layers({TOP_KEY, BOTTOM_KEY, "O"}, bw=True, mirror=True, neg=True)
        else:
            self.preview.update()

    def checked_layers(self) -> List[str]:
        return [self.layers.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.layers.count())
                if self.layers.item(i).checkState() == Qt.CheckState.Checked]

    def _render(self, painter: QPainter, scale_px: float, offset, dpr: float = 1.0):
        from PySide6.QtCore import QPoint, QPointF
        c = self.canvas
        layers = self.checked_layers()
        old = (c.scale, QPointF(c.offset), c.active_layer, dict(c.tokens),
               dict(self.canvas.board().colors), dict(self.canvas.board().visible),
               c.field_origin)
        c.scale = scale_px
        c.offset = QPointF(offset)
        c.field_origin = QPoint(0, 0)
        c.tokens = dict(c.tokens)
        c.tokens["canvas"] = "#ffffff"
        c.tokens["board"] = "#ffffff"
        for lk in c.board().visible:
            c.board().visible[lk] = lk in layers
        bw = self.ch_bw.isChecked()
        if bw:
            for lk in LAYER_BY_KEY:
                c.board().colors[lk] = "#000000"
        mirror_all = self.ch_mirror_all.isChecked()
        mirror_bottom = self.ch_mirror_bottom.isChecked()
        for lk in layers:
            if not LAYER_BY_KEY[lk].top and (mirror_bottom or mirror_all):
                for el in c.board().elements.values():
                    if el.layer == lk:
                        pass
        painter.save()
        box = c.board().outline_rect()
        pts = c.board().outline_points()
        if mirror_all:
            cx = (box[0] + box[2]) / 2
            for el in c.board().elements.values():
                el.mirror_x((cx, 0))
        if self.ch_outline.isChecked() and "O" not in layers:
            pass
        from ..core.model import draw_sort_key
        for el in sorted((e for e in c.board().elements.values()
                          if e.kind != "conn" and e.layer in layers),
                         key=draw_sort_key):
            mir = not LAYER_BY_KEY[el.layer].top and (mirror_bottom or mirror_all)
            col = QColor("#000000" if bw else LAYER_BY_KEY[el.layer].default_color)
            c._draw_element(painter, el, col, mir)
        if self.ch_holes:
            painter.setPen(QColor("#c00000"))
            for el in c.board().elements.values():
                if isinstance(el, Pad) and el.hole_dia > 0:
                    p = c.to_screen((el.x, el.y))
                    r = el.hole_dia * c.scale / 2
                    painter.drawLine(p.x() - r, p.y(), p.x() + r, p.y())
                    painter.drawLine(p.x(), p.y() - r, p.x(), p.y() + r)
        if self.ch_corners:
            painter.setPen(QColor("#c00000"))
            for (x, y) in c.board().outline_points():
                p = c.to_screen((x, y))
                painter.drawLine(p.x() - 6, p.y(), p.x() + 6, p.y())
                painter.drawLine(p.x(), p.y() - 6, p.x(), p.y() + 6)
        if self.ch_negative:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            painter.fillRect(0, 0, 1000000, 1000000, QColor("#ffffff"))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.restore()
        c.scale, c.offset, c.active_layer, c.tokens = old[0], old[1], old[2], old[3]
        c.field_origin = old[6]
        self.canvas.board().colors = old[4]
        self.canvas.board().visible = old[5]

    def do_print(self):
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QPageLayout, QPageSize
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        from PySide6.QtGui import QPageSetupDialog
        d = QPageSetupDialog(printer)
        d.exec()
        res = printer.pageLayout().paintRectPixels(printer.resolution())
        from PySide6.QtCore import QPointF
        s = printer.resolution() / 25.4 * self.scale.value() / 100.0
        b = self.canvas.board()
        bx = b.outline_rect()
        dx = max(0.0, (res.width() - b.width * s) / 2) / s
        dy = max(0.0, (res.height() - b.height * s) / 2) / s
        off = QPointF(bx[0] - dx, bx[1] - dy)
        painter = QPainter(printer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._render(painter, s, off)
        painter.end()
        printer.setDocName(self.canvas.doc.file or "e-cad")
        self.canvas.statusMessage.emit("Печать отправлена на принтер")

    def copy_clip(self):
        from PySide6.QtGui import QGuiApplication
        img = QImage(2400, 1800, QImage.Format.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        self._render(p, 1200.0 / max(1.0, self.canvas.board().width), QPointF(0, 0))
        p.end()
        QGuiApplication.clipboard().setImage(img)
        self.canvas.statusMessage.emit("Рисунок 1:1 скопирован в буфер обмена")


class PrintPreview(QWidget):
    def __init__(self, canvas, dlg: PrintDialog, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.dlg = dlg
        self.setMinimumHeight(180)

    def paintEvent(self, _e):
        p = QPainter(self)
        from PySide6.QtCore import QPointF, QRectF
        p.fillRect(self.rect(), QColor("#404448"))
        b = self.canvas.board()
        w = max(1.0, b.width)
        h = max(1.0, b.height)
        s = min(self.width() / w, self.height() / h) * 0.8 * self.dlg.scale.value() / 100.0
        bx = b.outline_rect()
        off = QPointF(bx[0] - max(0.0, (self.width() - w * s) / 2) / s,
                      bx[1] - max(0.0, (self.height() - h * s) / 2) / s)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.dlg._render(p, s, off)
        p.setPen(QPen(QColor("#ff5252"), 1, Qt.PenStyle.DashLine))
        p.drawRect(self.rect().adjusted(2, 2, -3, -3))
        p.setPen(QColor("#dddddd"))
        p.drawText(6, self.height() - 6, f"{self.dlg.scale.value():.0f}% · "
                                        f"{len(self.dlg.checked_layers())} слоёв")
        p.end()



class ImageExportDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Экспорт в изображение", parent, 460)
        self.fmt = QComboBox()
        self.fmt.addItems(["PNG (растр)", "JPG (растр, качество)", "GIF", "BMP",
                           "PDF (векторный)"])
        self.dpi = QSpinBox()
        self.dpi.setRange(20, 2400)
        self.dpi.setValue(600)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality.setEnabled(False)
        self.fmt.currentIndexChanged.connect(
            lambda i: self.quality.setEnabled(i in (1, 3)))
        self.layers = QListWidget()
        self.layers.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for lk in ALL_LAYERS:
            it = QListWidgetItem(f"{lk} — {LAYER_BY_KEY[lk].name}")
            it.setData(Qt.ItemDataRole.UserRole, lk)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.layers.addItem(it)
        self.v.addLayout(_form(("Формат:", self.fmt),
                               ("Разрешение, dpi:", self.dpi),
                               ("Качество / чёрно-белое:", self.quality)))
        self.v.addWidget(QLabel("Слои (для мультислойной печати — как в меню «Печать»):"))
        self.v.addWidget(self.layers, 1)
        self.buttons("Сохранить")

    def checked(self) -> List[str]:
        return [self.layers.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.layers.count())
                if self.layers.item(i).checkState() == Qt.CheckState.Checked]

    def run(self):
        ext = {0: "png", 1: "jpg", 2: "gif", 3: "bmp", 4: "pdf"}[self.fmt.currentIndex()]
        base = ascii_safe(self.canvas.board().name) or "board"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить изображение",
                                              f"{base}.{ext}",
                                              f"{ext.upper()} (*.{ext})")
        if not path:
            return
        from .render import render_image
        img = render_image(self.canvas, self.checked(), dpi=self.dpi.value(),
                           grayscale=self.fmt.currentIndex() == 3)
        if self.fmt.currentIndex() == 4:
            img.save(path, "PDF")
        else:
            q = self.quality.value()
            if self.fmt.currentIndex() == 1:
                img.save(path, "JPG", q)
            elif self.fmt.currentIndex() == 3:
                img.setGrayscale(300) if hasattr(img, "setGrayscale") else None
                img.save(path, "BMP")
            else:
                img.save(path)
        self.canvas.statusMessage.emit(f"Изображение сохранено: {path}")



class PnpDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Данные Pick+Place / спецификация", parent, 560)
        self.cols = QListWidget()
        for title, key in DEFAULT_PNP_COLUMNS:
            it = QListWidgetItem(title)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.cols.addItem(it)
        self.sep = QLineEdit("\t")
        self.dec = QSpinBox()
        self.dec.setRange(0, 6)
        self.dec.setValue(3)
        self.units = QComboBox()
        self.units.addItems(["мм", "mil"])
        self.rot_prefix = QLineEdit("R")
        self.layer_names = QComboBox()
        self.layer_names.addItems(["Top/Bottom", "ВЕР/НИЗ", "1/2"])
        self.smd_mark = QCheckBox("Указатель «+» на плате для SMD (установка центров)")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(220)
        self.v.addLayout(_form(("Разделитель:", self.sep),
                               ("Знаков после запятой:", self.dec),
                               ("Единицы координат:", self.units),
                               ("Префикс вращения:", self.rot_prefix),
                               ("Обозначения слоёв:", self.layer_names)))
        self.v.addWidget(self.smd_mark)
        self.v.addWidget(QLabel("Колонки (порядок = перетаскивание):"))
        self.v.addWidget(self.cols, 1)
        self.v.addWidget(QLabel("Предпросмотр:"))
        self.v.addWidget(self.preview)
        self.sep.textChanged.connect(self.refresh)
        self.dec.valueChanged.connect(self.refresh)
        self.refresh()
        self.buttons("Сохранить .txt")

    def columns(self):
        out = []
        for i in range(self.cols.count()):
            it = self.cols.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append((it.text(), it.data(Qt.ItemDataRole.UserRole)))
        return out

    def text(self) -> str:
        units = "mm" if self.units.currentIndex() == 0 else "mil"
        return pick_and_place(self.canvas.board(), self.columns(),
                              separator=self.sep.text() or "\t",
                              decimals=self.dec.value(),
                              rot_prefix=self.rot_prefix.text(), units=units)

    def refresh(self):
        self.preview.setPlainText(self.text()[:5000])

    def run(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить Pick+Place",
                                              "pick_place.txt", "Текст (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.text())
        self.canvas.statusMessage.emit(f"Pick+Place сохранён: {path}")



class ComponentDialog(BaseDialog):
    def __init__(self, canvas, comp: Component, parent=None):
        super().__init__(canvas, "Свойства компонента", parent)
        self.comp = comp
        self.ref = QLineEdit(comp.refdes)
        self.val = QLineEdit(comp.value)
        self.comm = QLineEdit(comp.comment)
        self.side = QComboBox()
        self.side.addItems(["Верх (Top)", "Низ (Bottom)"])
        self.side.setCurrentIndex(0 if comp.side == "top" else 1)
        self.layer = QComboBox()
        self.layer.addItems(canvas.doc.active_layers())
        self.layer.setCurrentText(comp.layer)
        self.fp = QLineEdit(comp.footprint)
        self.rot = _spin(1, -360, 360, 90, comp.rotation)
        self.v.addLayout(_form(("Обозначение (RefDes):", self.ref),
                               ("Номинал (Value):", self.val),
                               ("Комментарий:", self.comm),
                               ("Корпус:", self.fp),
                               ("Сторона установки:", self.side),
                               ("Слой подписи:", self.layer),
                               ("Вращение, °:", self.rot)))
        self.buttons("Сохранить")

    def apply(self):
        c = self.comp
        c.refdes = self.ref.text()
        c.value = self.val.text()
        c.comment = self.comm.text()
        c.footprint = self.fp.text()
        c.side = "top" if self.side.currentIndex() == 0 else "bottom"
        c.layer = self.layer.currentText()
        c.rotation = self.rot.value()



class OptionsDialog(BaseDialog):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, "Общие настройки (Опции)", parent, 620)
        s = canvas.settings
        self.tabs = QTabWidget()
        
        t1 = QWidget()
        f1 = QFormLayout(t1)
        self.units = QComboBox()
        self.units.addItems(["миллиметры", "милы (1/1000 дюйма)"])
        self.units.setCurrentIndex(0 if s["units"] == "mm" else 1)
        self.hole_color = QComboBox()
        self.hole_color.addItems(["тёмные (прозрачные)", "белые", "чёрные"])
        self.hole_color.setCurrentIndex({"dark": 0, "white": 1, "black": 2}.get(s["hole_color"], 0))
        self.undo_depth = QSpinBox()
        self.undo_depth.setRange(1, 500)
        self.undo_depth.setValue(s["undo_depth"])
        self.min_th = _spin(3, 0.05, 1, 0.05, s["min_text_thickness"])
        self.blink = QCheckBox()
        self.blink.setChecked(s["probe_blink"])
        self.probe_virt = QCheckBox("Учитывать виртуальные связи в режиме контроля")
        self.probe_virt.setChecked(s["probe_virtual"])
        self.origin = QCheckBox("Показывать начало координат в углу поля")
        self.origin.setChecked(s["show_origin"])
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 120)
        self.autosave.setValue(s["autosave_min"])
        f1.addRow("Единицы:", self.units)
        f1.addRow("Цвет сквозных отверстий:", self.hole_color)
        f1.addRow("Глубина Отмени/Восстановить:", self.undo_depth)
        f1.addRow("Мин. толщина шрифта, мм:", self.min_th)
        f1.addRow("Мерцание подсветки:", self.blink)
        f1.addRow(self.probe_virt)
        f1.addRow(self.origin)
        f1.addRow("Автосохранение, мин (0 — выкл):", self.autosave)
        self.tabs.addTab(t1, "Основные")
        
        t2 = QWidget()
        g = QGridLayout(t2)
        self.color_buttons = {}
        for i, lk in enumerate(ALL_LAYERS):
            b = QPushButton(lk)
            b.clicked.connect(lambda _c, k=lk: self._pick_color(k))
            self.color_buttons[lk] = b
            g.addWidget(b, i // 2, i % 2)
        self.v.addWidget(self.tabs)
        t2.setLayout(g)
        self.tabs.addTab(t2, "Цвета слоёв")
        
        t3 = QWidget()
        f3 = QFormLayout(t3)
        self.f_clr = _spin(3, 0, 10, 0.05, s["clearance"])
        self.f_per = QCheckBox("Задавать зазор отдельно для каждого элемента")
        self.f_per.setChecked(s["fill_per_element"])
        self.f_gap = _spin(3, 0.05, 5, 0.05, s["thermal_gap"])
        self.f_spoke = _spin(3, 0.05, 5, 0.05, s["thermal_spoke"])
        self.f_dirs = QWidget()
        h = QHBoxLayout(self.f_dirs)
        h.setContentsMargins(0, 0, 0, 0)
        self.dir_checks = []
        for name in ("←", "→", "↓", "↑"):
            cb = QCheckBox(name)
            cb.setChecked(s["thermal_dirs"][len(self.dir_checks)])
            self.dir_checks.append(cb)
            h.addWidget(cb)
        self.f_dim = QCheckBox("Затемнять металлизацию")
        self.f_dim.setChecked(s["fill_dim"])
        self.f_through = QCheckBox("Отображать металлизацию сквозь слои")
        self.f_through.setChecked(s["fill_through"])
        self.f_auto = QCheckBox("Пересчитывать заливку автоматически после правок")
        self.f_auto.setChecked(s["auto_fill_on_edit"])
        f3.addRow("Зазор заливки, мм:", self.f_clr)
        f3.addRow(self.f_per)
        f3.addRow("Термобарьер: зазор кольца, мм:", self.f_gap)
        f3.addRow("Термобарьер: ширина лучей, мм:", self.f_spoke)
        f3.addRow("Направления лучей:", self.f_dirs)
        f3.addRow(self.f_dim)
        f3.addRow(self.f_through)
        f3.addRow(self.f_auto)
        self.tabs.addTab(t3, "Металлизация")
        
        t4 = QWidget()
        f4 = QFormLayout(t4)
        self.key_buttons = {}
        for key, name, hot, _ic in self.canvas_tools():
            b = QPushButton(hot)
            b.clicked.connect(lambda _c, k=key: self._pick_key(k))
            self.key_buttons[key] = b
            f4.addRow(name, b)
        self.tabs.addTab(t4, "Клавиши")
        
        t5 = QWidget()
        f5 = QFormLayout(t5)
        self.imax_cu = _spin(1, 10, 200, 5, s["imax_cu"])
        self.imax_t = _spin(1, -50, 150, 5, s["imax_temp"])
        f5.addRow("Толщина слоя меди, мкм:", self.imax_cu)
        f5.addRow("Температура, °C:", self.imax_t)
        self.tabs.addTab(t5, "Imax")
        self.buttons("Сохранить")
        self._update_colors()

    def canvas_tools(self):
        from .canvas import TOOLS
        return TOOLS

    def _pick_color(self, lk: str):
        b = self.canvas.board()
        cur = b.colors.get(lk) or LAYER_BY_KEY[lk].default_color
        c = QColorDialog.getColor(QColor(cur), self, f"Цвет слоя {lk}")
        if c.isValid():
            b.colors[lk] = c.name()
            self._update_colors()
            self.canvas.invalidate(structural=False)

    def _update_colors(self):
        b = self.canvas.board()
        for lk, btn in self.color_buttons.items():
            col = b.colors.get(lk) or LAYER_BY_KEY[lk].default_color
            btn.setStyleSheet(f"background:{col}; color:#fff; border-radius:8px;"
                              f"padding:6px; border:1px solid #666;")

    def _pick_key(self, tool_key: str):
        dlg = KeyCaptureDialog(self)
        if dlg.exec() and dlg.key:
            self.canvas.settings["keys"][dlg.key] = tool_key
            self.key_buttons[tool_key].setText(dlg.key)

    def apply(self):
        s = self.canvas.settings
        s["units"] = "mm" if self.units.currentIndex() == 0 else "mil"
        s["hole_color"] = ["dark", "white", "black"][self.hole_color.currentIndex()]
        s["undo_depth"] = self.undo_depth.value()
        s["min_text_thickness"] = self.min_th.value()
        s["probe_blink"] = self.blink.isChecked()
        s["probe_virtual"] = self.probe_virt.isChecked()
        s["show_origin"] = self.origin.isChecked()
        s["autosave_min"] = self.autosave.value()
        s["clearance"] = self.f_clr.value()
        s["fill_per_element"] = self.f_per.isChecked()
        s["thermal_gap"] = self.f_gap.value()
        s["thermal_spoke"] = self.f_spoke.value()
        s["thermal_dirs"] = [c.isChecked() for c in self.dir_checks]
        s["fill_dim"] = self.f_dim.isChecked()
        s["fill_through"] = self.f_through.isChecked()
        s["auto_fill_on_edit"] = self.f_auto.isChecked()
        s["imax_cu"] = self.imax_cu.value()
        s["imax_temp"] = self.imax_t.value()
        self.canvas.invalidate()
        self.canvas.viewChanged.emit()


class KeyCaptureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self.setWindowTitle("Назначение клавиши")
        self.setMinimumWidth(320)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Нажмите желаемую клавишу:"))
        self.lbl = QLabel("…")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setStyleSheet("font-size: 20px; padding: 20px;")
        v.addWidget(self.lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def keyPressEvent(self, ev):
        self.key = QKeySequence(ev.key()).toString()
        self.lbl.setText(self.key)